import asyncio
import logging
import re
from typing import Callable, Literal

import numpy as np

from .reply_on_pause import (
    AlgoOptions,
    AppState,
    ModelOptions,
    PauseDetectionModel,
    ReplyFnGenerator,
    ReplyOnPause,
)
from .speech_to_text import get_stt_model, stt_for_chunks
from .utils import audio_to_float32, create_message

logger = logging.getLogger(__name__)


class ReplyOnStopWordsState(AppState):
    stop_word_detected: bool = False
    post_stop_word_buffer: np.ndarray | None = None
    started_talking_pre_stop_word: bool = False

    def new(self):
        return ReplyOnStopWordsState()


class ReplyOnStopWords(ReplyOnPause):
    def __init__(
        self,
        fn: ReplyFnGenerator,
        stop_words: list[str],
        startup_fn: Callable | None = None,
        algo_options: AlgoOptions | None = None,
        model_options: ModelOptions | None = None,
        can_interrupt: bool = True,
        expected_layout: Literal["mono", "stereo"] = "mono",
        output_sample_rate: int = 24000,
        output_frame_size: int | None = None,  # Deprecated
        input_sample_rate: int = 48000,
        model: PauseDetectionModel | None = None,
    ):
        super().__init__(
            fn,
            algo_options=algo_options,
            startup_fn=startup_fn,
            model_options=model_options,
            can_interrupt=can_interrupt,
            expected_layout=expected_layout,
            output_sample_rate=output_sample_rate,
            output_frame_size=output_frame_size,
            input_sample_rate=input_sample_rate,
            model=model,
        )
        self.stop_words = stop_words
        self.state = ReplyOnStopWordsState()
        self.stt_model = get_stt_model("moonshine/base")

    def stop_word_detected(self, text: str) -> bool:
        for stop_word in self.stop_words:
            stop_word = stop_word.lower().strip().split(" ")
            if bool(
                re.search(
                    r"\b" + r"\s+".join(map(re.escape, stop_word)) + r"[.,!?]*\b",
                    text.lower(),
                )
            ):
                logger.debug("Stop word detected: %s", stop_word)
                return True
        return False

    async def _send_stopword(
        self,
    ):
        if self.channel:
            self.channel.send(create_message("stopword", ""))
            logger.debug("Sent stopword")

    def send_stopword(self):
        asyncio.run_coroutine_threadsafe(self._send_stopword(), self.loop)

    def determine_pause(  # type: ignore
        self, audio: np.ndarray, sampling_rate: int, state: ReplyOnStopWordsState
    ) -> bool:
        """Take in the stream, determine if a pause happened"""
        import librosa

        duration = len(audio) / sampling_rate

        if duration >= self.algo_options.audio_chunk_duration:
            if not state.stop_word_detected:
                audio_f32 = audio_to_float32((sampling_rate, audio))
                audio_rs = librosa.resample(
                    audio_f32, orig_sr=sampling_rate, target_sr=16000
                )
                if state.post_stop_word_buffer is None:
                    state.post_stop_word_buffer = audio_rs
                else:
                    state.post_stop_word_buffer = np.concatenate(
                        (state.post_stop_word_buffer, audio_rs)
                    )
                if len(state.post_stop_word_buffer) / 16000 > 2:
                    state.post_stop_word_buffer = state.post_stop_word_buffer[-32000:]
                dur_vad, chunks = self.model.vad(
                    (16000, state.post_stop_word_buffer),
                    self.model_options,
                )
                text = stt_for_chunks(
                    self.stt_model, (16000, state.post_stop_word_buffer), chunks
                )
                logger.debug(f"STT: {text}")
                state.stop_word_detected = self.stop_word_detected(text)
                if state.stop_word_detected:
                    logger.debug("Stop word detected")
                    self.send_stopword()
                state.buffer = None
            else:
                dur_vad, _ = self.model.vad((sampling_rate, audio), self.model_options)
                logger.debug("VAD duration: %s", dur_vad)
                if (
                    dur_vad > self.algo_options.started_talking_threshold
                    and not state.started_talking
                    and state.stop_word_detected
                ):
                    state.started_talking = True
                    logger.debug("Started talking")
                if state.started_talking:
                    if state.stream is None:
                        state.stream = audio
                    else:
                        state.stream = np.concatenate((state.stream, audio))
                state.buffer = None
                if (
                    dur_vad < self.algo_options.speech_threshold
                    and state.started_talking
                    and state.stop_word_detected
                ):
                    return True
        return False

    def reset(self):
        super().reset()
        self.generator = None
        self.event.clear()
        self.state = ReplyOnStopWordsState()

    def copy(self):
        return ReplyOnStopWords(
            self.fn,
            self.stop_words,
            self.startup_fn,
            self.algo_options,
            self.model_options,
            self.can_interrupt,
            self.expected_layout,
            self.output_sample_rate,
            self.output_frame_size,
            self.input_sample_rate,
            self.model,
        )
