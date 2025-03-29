"""WebRTC tracks."""

from __future__ import annotations

import asyncio
import fractions
import functools
import inspect
import logging
import threading
import time
import traceback
import warnings
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import (
    Any,
    Generator,
    Literal,
    Tuple,
    TypeAlias,
    Union,
    cast,
)

import anyio.to_thread
import av
import numpy as np
from aiortc import (
    AudioStreamTrack,
    MediaStreamTrack,
    VideoStreamTrack,
)
from aiortc.contrib.media import AudioFrame, VideoFrame  # type: ignore
from aiortc.mediastreams import VIDEO_CLOCK_RATE, VIDEO_TIME_BASE, MediaStreamError
from numpy import typing as npt

from fastrtc.utils import (
    AdditionalOutputs,
    CloseStream,
    Context,
    DataChannel,
    WebRTCError,
    create_message,
    current_channel,
    current_context,
    player_worker_decode,
    split_output,
)

logger = logging.getLogger(__name__)

VideoNDArray: TypeAlias = Union[
    np.ndarray[Any, np.dtype[np.uint8]],
    np.ndarray[Any, np.dtype[np.uint16]],
    np.ndarray[Any, np.dtype[np.float32]],
]

VideoEmitType = (
    VideoNDArray
    | tuple[VideoNDArray, AdditionalOutputs]
    | tuple[VideoNDArray, CloseStream]
    | AdditionalOutputs
    | CloseStream
)
VideoEventGenerator = Generator[VideoEmitType, None, None]
VideoEventHandler = Callable[[npt.ArrayLike], VideoEmitType | VideoEventGenerator]


@dataclass
class VideoStreamHandler:
    callable: VideoEventHandler
    fps: int = 30
    skip_frames: bool = False


class VideoCallback(VideoStreamTrack):
    """
    This works for streaming input and output
    """

    kind = "video"

    def __init__(
        self,
        track: MediaStreamTrack,
        event_handler: VideoEventHandler,
        context: Context,
        channel: DataChannel | None = None,
        set_additional_outputs: Callable | None = None,
        mode: Literal["send-receive", "send"] = "send-receive",
        fps: int = 30,
        skip_frames: bool = False,
    ) -> None:
        super().__init__()
        self.track = track
        self.event_handler = event_handler
        self.latest_args: str | list[Any] = "not_set"
        self.channel = channel
        self.set_additional_outputs = set_additional_outputs
        self.thread_quit = asyncio.Event()
        self.mode = mode
        self.channel_set = asyncio.Event()
        self.has_started = False
        self.fps = fps
        self.frame_ptime = 1.0 / fps
        self.skip_frames = skip_frames
        self.frame_queue: asyncio.Queue[VideoFrame] = asyncio.Queue()
        self.latest_frame = None
        self.context = context

    def set_channel(self, channel: DataChannel):
        self.channel = channel
        current_channel.set(channel)
        current_context.set(self.context)
        self.channel_set.set()

    def set_args(self, args: list[Any]):
        self.latest_args = ["__webrtc_value__"] + list(args)

    def add_frame_to_payload(
        self, args: list[Any], frame: np.ndarray | None
    ) -> list[Any]:
        new_args = []
        for val in args:
            if isinstance(val, str) and val == "__webrtc_value__":
                new_args.append(frame)
            else:
                new_args.append(val)
        return new_args

    def array_to_frame(self, array: np.ndarray) -> VideoFrame:
        return VideoFrame.from_ndarray(array, format="bgr24")

    async def process_frames(self):
        while not self.thread_quit.is_set():
            try:
                await self.recv()
            except TimeoutError:
                continue

    async def start(
        self,
    ):
        asyncio.create_task(self.process_frames())

    def stop(self):
        super().stop()
        logger.debug("video callback stop")
        self.thread_quit.set()

    async def wait_for_channel(self):
        current_context.set(self.context)
        if not self.channel_set.is_set():
            await self.channel_set.wait()
        if current_channel.get() != self.channel:
            current_channel.set(self.channel)

    async def accept_input(self):
        self.has_started = True
        while not self.thread_quit.is_set():
            try:
                frame = cast(VideoFrame, await self.track.recv())
                self.latest_frame = frame
                self.frame_queue.put_nowait(frame)
            except MediaStreamError:
                self.stop()
                return

    def accept_input_in_background(self):
        if not self.has_started:
            asyncio.create_task(self.accept_input())

    async def recv(self):  # type: ignore
        self.accept_input_in_background()
        try:
            frame = await self.frame_queue.get()
            if self.skip_frames:
                frame = self.latest_frame
            await self.wait_for_channel()
            frame_array = frame.to_ndarray(format="bgr24")  # type: ignore
            if self.latest_args == "not_set":
                return frame

            args = self.add_frame_to_payload(cast(list, self.latest_args), frame_array)
            array, outputs = split_output(self.event_handler(*args))
            if isinstance(outputs, CloseStream):
                cast(DataChannel, self.channel).send(
                    create_message("end_stream", outputs.msg)
                )
                self.stop()
                return None
            if (
                isinstance(outputs, AdditionalOutputs)
                and self.set_additional_outputs
                and self.channel
            ):
                self.set_additional_outputs(outputs)
                self.channel.send(create_message("fetch_output", []))
            if array is None and self.mode == "send":
                return

            new_frame = self.array_to_frame(array)
            if frame:
                new_frame.pts = frame.pts
                new_frame.time_base = frame.time_base
            else:
                pts, time_base = await self.next_timestamp()
                new_frame.pts = pts
                new_frame.time_base = time_base
            return new_frame
        except Exception as e:
            logger.debug("exception %s", e)
            exec = traceback.format_exc()
            logger.debug("traceback %s", exec)
            if isinstance(e, WebRTCError):
                raise e
            else:
                raise WebRTCError(str(e)) from e

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        """Override to control frame rate"""
        if self.readyState != "live":
            raise MediaStreamError

        if hasattr(self, "_timestamp"):
            self._timestamp += int(self.frame_ptime * VIDEO_CLOCK_RATE)
            wait = self._start + (self._timestamp / VIDEO_CLOCK_RATE) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        else:
            self._start = time.time()
            self._timestamp = 0
        return self._timestamp, VIDEO_TIME_BASE


class StreamHandlerBase(ABC):
    def __init__(
        self,
        expected_layout: Literal["mono", "stereo"] = "mono",
        output_sample_rate: int = 24000,
        output_frame_size: int | None = None,
        input_sample_rate: int = 48000,
        fps: int = 30,
    ) -> None:
        self.expected_layout = expected_layout
        self.output_sample_rate = output_sample_rate
        self.input_sample_rate = input_sample_rate
        self.fps = fps
        self.latest_args: list[Any] = []
        self._resampler = None
        self._channel: DataChannel | None = None
        self._loop: asyncio.AbstractEventLoop
        self.args_set = asyncio.Event()
        self.channel_set = asyncio.Event()
        self._phone_mode = False
        self._clear_queue: Callable | None = None

        sample_rate_to_frame_size_coef = 50
        if output_sample_rate % sample_rate_to_frame_size_coef != 0:
            raise ValueError(
                "output_sample_rate must be a multiple of "
                f"{sample_rate_to_frame_size_coef}, got {output_sample_rate}"
            )

        actual_output_frame_size = output_sample_rate // sample_rate_to_frame_size_coef
        if (
            output_frame_size is not None
            and output_frame_size != actual_output_frame_size
        ):
            warnings.warn(
                "The output_frame_size parameter is deprecated and will be removed "
                "in a future release. The value passed in will be ignored. "
                f"The actual output frame size is {actual_output_frame_size}, "
                f"corresponding to {1 / sample_rate_to_frame_size_coef:.2f}s "
                f"at {output_sample_rate=}Hz.",
                # DeprecationWarning is filtered out by default, so use UserWarning
                UserWarning,
                stacklevel=2,  # So that the warning points to the user's code
            )
        self.output_frame_size = actual_output_frame_size

    @property
    def clear_queue(self) -> Callable:
        return cast(Callable, self._clear_queue)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return cast(asyncio.AbstractEventLoop, self._loop)

    @property
    def channel(self) -> DataChannel | None:
        return self._channel

    @property
    def phone_mode(self) -> bool:
        return self._phone_mode

    @phone_mode.setter
    def phone_mode(self, value: bool):
        self._phone_mode = value

    def set_channel(self, channel: DataChannel):
        self._channel = channel
        self.channel_set.set()

    async def fetch_args(
        self,
    ):
        if self.channel:
            self.channel.send(create_message("send_input", []))
            logger.debug("Sent send_input")

    async def wait_for_args(self):
        if not self.phone_mode:
            await self.fetch_args()
            await self.args_set.wait()
        else:
            self.args_set.set()

    def wait_for_args_sync(self):
        try:
            asyncio.run_coroutine_threadsafe(self.wait_for_args(), self.loop).result()
        except Exception:
            import traceback

            traceback.print_exc()

    async def send_message(self, msg: str):
        if self.channel:
            self.channel.send(msg)
            logger.debug("Sent msg %s", msg)

    def send_message_sync(self, msg: str):
        try:
            asyncio.run_coroutine_threadsafe(self.send_message(msg), self.loop).result()
            logger.debug("Sent msg %s", msg)
        except Exception as e:
            logger.debug("Exception sending msg %s", e)

    def set_args(self, args: list[Any]):
        logger.debug("setting args in audio callback %s", args)
        self.latest_args = ["__webrtc_value__"] + list(args)
        self.args_set.set()

    def reset(self):
        self.args_set.clear()

    def shutdown(self):
        pass

    def resample(self, frame: AudioFrame) -> Generator[AudioFrame, None, None]:
        if self._resampler is None:
            self._resampler = av.AudioResampler(  # type: ignore
                format="s16",
                layout=self.expected_layout,
                rate=self.input_sample_rate,
                frame_size=frame.samples,
            )
        yield from self._resampler.resample(frame)


EmitType: TypeAlias = (
    tuple[int, npt.NDArray[np.int16 | np.float32]]
    | tuple[int, npt.NDArray[np.int16 | np.float32], Literal["mono", "stereo"]]
    | AdditionalOutputs
    | tuple[tuple[int, npt.NDArray[np.int16 | np.float32]], AdditionalOutputs]
    | None
)
AudioEmitType = EmitType


class StreamHandler(StreamHandlerBase):
    @abstractmethod
    def receive(self, frame: tuple[int, npt.NDArray[np.int16]]) -> None:
        pass

    @abstractmethod
    def emit(self) -> EmitType:
        pass

    @abstractmethod
    def copy(self) -> StreamHandler:
        pass

    def start_up(self):
        pass


class AsyncStreamHandler(StreamHandlerBase):
    @abstractmethod
    async def receive(self, frame: tuple[int, npt.NDArray[np.int16]]) -> None:
        pass

    @abstractmethod
    async def emit(self) -> EmitType:
        pass

    @abstractmethod
    def copy(self) -> AsyncStreamHandler:
        pass

    async def start_up(self):
        pass


StreamHandlerImpl = StreamHandler | AsyncStreamHandler


class AudioVideoStreamHandler(StreamHandler):
    @abstractmethod
    def video_receive(self, frame: VideoFrame) -> None:
        pass

    @abstractmethod
    def video_emit(self) -> VideoEmitType:
        pass

    @abstractmethod
    def copy(self) -> AudioVideoStreamHandler:
        pass


class AsyncAudioVideoStreamHandler(AsyncStreamHandler):
    @abstractmethod
    async def video_receive(self, frame: npt.NDArray[np.float32]) -> None:
        pass

    @abstractmethod
    async def video_emit(self) -> VideoEmitType:
        pass

    @abstractmethod
    def copy(self) -> AsyncAudioVideoStreamHandler:
        pass


VideoStreamHandlerImpl = AudioVideoStreamHandler | AsyncAudioVideoStreamHandler
AudioVideoStreamHandlerImpl = AudioVideoStreamHandler | AsyncAudioVideoStreamHandler
AsyncHandler = AsyncStreamHandler | AsyncAudioVideoStreamHandler

HandlerType = (
    StreamHandlerImpl
    | VideoStreamHandlerImpl
    | VideoEventHandler
    | Callable
    | VideoStreamHandler
)


class VideoStreamHandler_(VideoCallback):
    async def process_frames(self):
        while not self.thread_quit.is_set():
            try:
                await self.channel_set.wait()
                frame = cast(VideoFrame, await self.track.recv())
                frame_array = frame.to_ndarray(format="bgr24")
                handler = cast(VideoStreamHandlerImpl, self.event_handler)
                if inspect.iscoroutinefunction(handler.video_receive):
                    await handler.video_receive(frame_array)
                else:
                    handler.video_receive(frame_array)  # type: ignore
            except MediaStreamError:
                self.stop()

    async def start(self):
        if not self.has_started:
            asyncio.create_task(self.process_frames())
            self.has_started = True

    async def recv(self):  # type: ignore
        await self.start()
        try:
            handler = cast(VideoStreamHandlerImpl, self.event_handler)
            if inspect.iscoroutinefunction(handler.video_emit):
                outputs = await handler.video_emit()
            else:
                outputs = handler.video_emit()

            array, outputs = split_output(outputs)
            if (
                isinstance(outputs, AdditionalOutputs)
                and self.set_additional_outputs
                and self.channel
            ):
                self.set_additional_outputs(outputs)
                self.channel.send(create_message("fetch_output", []))
            if isinstance(outputs, CloseStream):
                cast(DataChannel, self.channel).send(
                    create_message("end_stream", outputs.msg)
                )
                self.stop()
                return
            if array is None and self.mode == "send":
                return

            new_frame = self.array_to_frame(array)

            # Will probably have to give developer ability to set pts and time_base
            pts, time_base = await self.next_timestamp()
            new_frame.pts = pts
            new_frame.time_base = time_base

            return new_frame
        except Exception as e:
            logger.debug("exception %s", e)
            exec = traceback.format_exc()
            logger.debug("traceback %s", exec)


class AudioCallback(AudioStreamTrack):
    kind = "audio"

    def __init__(
        self,
        track: MediaStreamTrack,
        event_handler: StreamHandlerBase,
        context: Context,
        channel: DataChannel | None = None,
        set_additional_outputs: Callable | None = None,
    ) -> None:
        super().__init__()
        self.track = track
        self.event_handler = cast(StreamHandlerImpl, event_handler)
        self.event_handler._clear_queue = self.clear_queue
        self.current_timestamp = 0
        self.latest_args: str | list[Any] = "not_set"
        self.queue = asyncio.Queue()
        self.thread_quit = asyncio.Event()
        self._start: float | None = None
        self.has_started = False
        self.last_timestamp = 0
        self.channel = channel
        self.set_additional_outputs = set_additional_outputs
        self.context = context

    def clear_queue(self):
        logger.debug("clearing queue")
        logger.debug("queue size: %d", self.queue.qsize())
        i = 0
        while not self.queue.empty():
            self.queue.get_nowait()
            i += 1
        logger.debug("popped %d items from queue", i)
        self._start = None

    async def wait_for_channel(self):
        current_context.set(self.context)
        if not self.event_handler.channel_set.is_set():
            await self.event_handler.channel_set.wait()
        if current_channel.get() != self.event_handler.channel:
            current_channel.set(self.event_handler.channel)

    def set_channel(self, channel: DataChannel):
        self.channel = channel
        self.event_handler.set_channel(channel)

    def set_args(self, args: list[Any]):
        self.event_handler.set_args(args)

    def event_handler_receive(self, frame: tuple[int, np.ndarray]) -> None:
        current_channel.set(self.event_handler.channel)
        return cast(Callable, self.event_handler.receive)(frame)

    def event_handler_emit(self) -> EmitType:
        current_channel.set(self.event_handler.channel)
        current_context.set(self.context)
        return cast(Callable, self.event_handler.emit)()

    async def process_input_frames(self) -> None:
        while not self.thread_quit.is_set():
            try:
                frame = cast(AudioFrame, await self.track.recv())
                for frame in self.event_handler.resample(frame):
                    numpy_array = frame.to_ndarray()
                    if isinstance(self.event_handler, AsyncHandler):
                        await self.event_handler.receive(
                            (frame.sample_rate, numpy_array)  # type: ignore
                        )
                    else:
                        await anyio.to_thread.run_sync(
                            self.event_handler_receive, (frame.sample_rate, numpy_array)
                        )
            except MediaStreamError:
                logger.debug("MediaStreamError in process_input_frames")
                break

    async def start(self):
        if not self.has_started:
            loop = asyncio.get_running_loop()
            await self.wait_for_channel()
            if isinstance(self.event_handler, AsyncHandler):
                callable = self.event_handler.emit
                start_up = self.event_handler.start_up()
                if not inspect.isawaitable(start_up):
                    raise WebRTCError(
                        "In AsyncStreamHandler, start_up must be a coroutine (async def)"
                    )

            else:
                callable = functools.partial(
                    loop.run_in_executor, None, self.event_handler_emit
                )
                start_up = anyio.to_thread.run_sync(self.event_handler.start_up)
            self.process_input_task = asyncio.create_task(self.process_input_frames())
            self.process_input_task.add_done_callback(
                lambda _: logger.debug("process_input_done")
            )
            self.start_up_task = asyncio.create_task(start_up)
            self.start_up_task.add_done_callback(
                lambda _: logger.debug("start_up_done")
            )
            self.decode_task = asyncio.create_task(
                player_worker_decode(
                    callable,
                    self.queue,
                    self.thread_quit,
                    lambda: self.channel,
                    self.set_additional_outputs,
                    False,
                    self.event_handler.output_sample_rate,
                    self.event_handler.output_frame_size,
                )
            )
            self.decode_task.add_done_callback(lambda _: logger.debug("decode_done"))
            self.has_started = True

    async def recv(self):  # type: ignore
        try:
            if self.readyState != "live":
                raise MediaStreamError

            if not self.event_handler.channel_set.is_set():
                await self.event_handler.channel_set.wait()
            if current_channel.get() != self.event_handler.channel:
                current_channel.set(self.event_handler.channel)
            await self.start()

            frame = await self.queue.get()
            if isinstance(frame, CloseStream):
                cast(DataChannel, self.channel).send(
                    create_message("end_stream", frame.msg)
                )
                self.stop()
                return
            logger.debug("frame %s", frame)

            data_time = frame.time

            if time.time() - self.last_timestamp > 10 * (
                self.event_handler.output_frame_size
                / self.event_handler.output_sample_rate
            ):
                self._start = None

            # control playback rate
            if self._start is None:
                self._start = time.time() - data_time  # type: ignore
            else:
                wait = self._start + data_time - time.time()
                await asyncio.sleep(wait)
            self.last_timestamp = time.time()
            return frame
        except Exception as e:
            logger.debug("exception %s", e)
            exec = traceback.format_exc()
            logger.debug("traceback %s", exec)

    def stop(self):
        logger.debug("audio callback stop")
        self.thread_quit.set()
        super().stop()


class ServerToClientVideo(VideoStreamTrack):
    """
    This works for streaming input and output
    """

    kind = "video"

    def __init__(
        self,
        event_handler: Callable,
        context: Context,
        channel: DataChannel | None = None,
        set_additional_outputs: Callable | None = None,
        fps: int = 30,
    ) -> None:
        super().__init__()  # don't forget this!
        self.event_handler = event_handler
        self.args_set = asyncio.Event()
        self.latest_args: str | list[Any] = "not_set"
        self.generator: Generator[Any, None, Any] | None = None
        self.channel = channel
        self.set_additional_outputs = set_additional_outputs
        self.fps = fps
        self.frame_ptime = 1.0 / fps
        self.context = context

    def array_to_frame(self, array: np.ndarray) -> VideoFrame:
        return VideoFrame.from_ndarray(array, format="bgr24")

    def set_channel(self, channel: DataChannel):
        self.channel = channel

    def set_args(self, args: list[Any]):
        self.latest_args = list(args)
        self.args_set.set()

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        """Override to control frame rate"""
        if self.readyState != "live":
            raise MediaStreamError

        if hasattr(self, "_timestamp"):
            self._timestamp += int(self.frame_ptime * VIDEO_CLOCK_RATE)
            wait = self._start + (self._timestamp / VIDEO_CLOCK_RATE) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        else:
            self._start = time.time()
            self._timestamp = 0
        return self._timestamp, VIDEO_TIME_BASE

    async def recv(self):  # type: ignore
        try:
            pts, time_base = await self.next_timestamp()
            await self.args_set.wait()
            current_channel.set(self.channel)
            current_context.set(self.context)
            if self.generator is None:
                self.generator = cast(
                    Generator[Any, None, Any], self.event_handler(*self.latest_args)
                )
            try:
                next_array, outputs = split_output(next(self.generator))
                if isinstance(outputs, CloseStream):
                    cast(DataChannel, self.channel).send(
                        create_message("end_stream", outputs.msg)
                    )
                    self.stop()
                    return
                if (
                    isinstance(outputs, AdditionalOutputs)
                    and self.set_additional_outputs
                    and self.channel
                ):
                    self.set_additional_outputs(outputs)
                    self.channel.send(create_message("fetch_output", []))
            except StopIteration:
                self.stop()
                return

            next_frame = self.array_to_frame(next_array)
            next_frame.pts = pts
            next_frame.time_base = time_base
            return next_frame
        except Exception as e:
            logger.debug("exception %s", e)
            exec = traceback.format_exc()
            logger.debug("traceback %s %s", e, exec)
            if isinstance(e, WebRTCError):
                raise e
            else:
                raise WebRTCError(str(e)) from e


class ServerToClientAudio(AudioStreamTrack):
    kind = "audio"

    def __init__(
        self,
        event_handler: Callable,
        context: Context,
        channel: DataChannel | None = None,
        set_additional_outputs: Callable | None = None,
    ) -> None:
        self.generator: Generator[Any, None, Any] | None = None
        self.event_handler = event_handler
        self.event_handler._clear_queue = self.clear_queue
        self.current_timestamp = 0
        self.latest_args: str | list[Any] = "not_set"
        self.args_set = threading.Event()
        self.queue = asyncio.Queue()
        self.thread_quit = asyncio.Event()
        self.channel = channel
        self.set_additional_outputs = set_additional_outputs
        self.has_started = False
        self._start: float | None = None
        self.context = context
        super().__init__()

    def clear_queue(self):
        while not self.queue.empty():
            self.queue.get_nowait()
        self._start = None

    def set_channel(self, channel: DataChannel):
        self.channel = channel

    def set_args(self, args: list[Any]):
        self.latest_args = list(args)
        self.args_set.set()

    def next(self) -> tuple[int, np.ndarray] | None:
        current_context.set(self.context)
        self.args_set.wait()
        current_channel.set(self.channel)
        if self.generator is None:
            self.generator = self.event_handler(*self.latest_args)
        if self.generator is not None:
            try:
                frame = next(self.generator)
                return frame
            except StopIteration:
                self.thread_quit.set()

    async def start(self):
        if not self.has_started:
            loop = asyncio.get_running_loop()
            callable = functools.partial(loop.run_in_executor, None, self.next)
            asyncio.create_task(
                player_worker_decode(
                    callable,
                    self.queue,
                    self.thread_quit,
                    lambda: self.channel,
                    self.set_additional_outputs,
                    True,
                )
            )
            self.has_started = True

    async def recv(self):  # type: ignore
        try:
            if self.readyState != "live":
                raise MediaStreamError

            await self.start()
            data = await self.queue.get()
            if isinstance(data, CloseStream):
                cast(DataChannel, self.channel).send(
                    create_message("end_stream", data.msg)
                )
                self.stop()
                return
            if data is None:
                self.stop()
                return

            data_time = data.time

            # control playback rate
            if data_time is not None:
                if self._start is None:
                    self._start = time.time() - data_time  # type: ignore
                else:
                    wait = self._start + data_time - time.time()
                    await asyncio.sleep(wait)

            return data
        except Exception as e:
            logger.debug("exception %s", e)
            exec = traceback.format_exc()
            logger.debug("traceback %s", exec)
            if isinstance(e, WebRTCError):
                raise e
            else:
                raise WebRTCError(str(e)) from e

    def stop(self):
        logger.debug("audio-to-client stop callback")
        self.thread_quit.set()
        super().stop()
