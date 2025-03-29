import asyncio
import base64
import os
from pathlib import Path
from typing import AsyncGenerator

import librosa
import numpy as np
from dotenv import load_dotenv
from fastrtc import (
    AsyncStreamHandler,
    Stream,
    get_tts_model,
    wait_for_item,
)
from fastrtc.utils import audio_to_int16
from google import genai
from google.genai.types import (
    Content,
    LiveConnectConfig,
    Part,
    PrebuiltVoiceConfig,
    SpeechConfig,
    VoiceConfig,
)

load_dotenv()

cur_dir = Path(__file__).parent

SAMPLE_RATE = 24000

tts_model = get_tts_model()


class GeminiHandler(AsyncStreamHandler):
    """Handler for the Gemini API"""

    def __init__(
        self,
    ) -> None:
        super().__init__(
            expected_layout="mono",
            output_sample_rate=24000,
            input_sample_rate=24000,
        )
        self.input_queue: asyncio.Queue = asyncio.Queue()
        self.output_queue: asyncio.Queue = asyncio.Queue()
        self.quit: asyncio.Event = asyncio.Event()

    def copy(self) -> "GeminiHandler":
        return GeminiHandler()

    async def start_up(self):
        voice_name = "Charon"
        client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"api_version": "v1alpha"},
        )

        config = LiveConnectConfig(
            response_modalities=["AUDIO"],  # type: ignore
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
            system_instruction=Content(
                parts=[Part(text="You are a helpful assistant.")],
                role="system",
            ),
        )
        async with client.aio.live.connect(
            model="gemini-2.0-flash-exp", config=config
        ) as session:
            async for audio in session.start_stream(
                stream=self.stream(), mime_type="audio/pcm"
            ):
                if audio.data:
                    array = np.frombuffer(audio.data, dtype=np.int16)
                    self.output_queue.put_nowait((self.output_sample_rate, array))

    async def stream(self) -> AsyncGenerator[bytes, None]:
        while not self.quit.is_set():
            try:
                audio = await asyncio.wait_for(self.input_queue.get(), 0.1)
                yield audio
            except (asyncio.TimeoutError, TimeoutError):
                pass

    async def receive(self, frame: tuple[int, np.ndarray]) -> None:
        _, array = frame
        array = array.squeeze()
        audio_message = base64.b64encode(array.tobytes()).decode("UTF-8")
        self.input_queue.put_nowait(audio_message)

    async def emit(self) -> tuple[int, np.ndarray] | None:
        return await wait_for_item(self.output_queue)

    def shutdown(self) -> None:
        self.quit.set()


class GeminiHandler2(GeminiHandler):
    async def start_up(self):
        starting_message = tts_model.tts("Can you help me make an omelette?")
        starting_message = librosa.resample(
            starting_message[1],
            orig_sr=starting_message[0],
            target_sr=self.output_sample_rate,
        )
        starting_message = audio_to_int16((self.output_sample_rate, starting_message))
        await self.output_queue.put((self.output_sample_rate, starting_message))
        voice_name = "Puck"
        client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"api_version": "v1alpha"},
        )

        config = LiveConnectConfig(
            response_modalities=["AUDIO"],  # type: ignore
            speech_config=SpeechConfig(
                voice_config=VoiceConfig(
                    prebuilt_voice_config=PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
            system_instruction=Content(
                parts=[
                    Part(
                        text="You are a cooking student who wants to learn how to make an omelette."
                    ),
                    Part(
                        text="You are currently in the kitchen with a teacher who is helping you make an omelette."
                    ),
                    Part(
                        text="Please wait for the teacher to tell you what to do next. Follow the teacher's instructions carefully."
                    ),
                ],
                role="system",
            ),
        )
        async with client.aio.live.connect(
            model="gemini-2.0-flash-exp", config=config
        ) as session:
            async for audio in session.start_stream(
                stream=self.stream(), mime_type="audio/pcm"
            ):
                if audio.data:
                    array = np.frombuffer(audio.data, dtype=np.int16)
                    self.output_queue.put_nowait((self.output_sample_rate, array))

    def copy(self) -> "GeminiHandler2":
        return GeminiHandler2()


gemini_stream = Stream(
    GeminiHandler(),
    modality="audio",
    mode="send-receive",
    ui_args={
        "title": "Gemini Teacher",
        "icon": "https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png",
        "pulse_color": "rgb(74, 138, 213)",
        "icon_button_color": "rgb(255, 255, 255)",
    },
)

gemini_stream_2 = Stream(
    GeminiHandler2(),
    modality="audio",
    mode="send-receive",
    ui_args={
        "title": "Gemini Student",
        "icon": "https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png",
        "pulse_color": "rgb(132, 112, 196)",
        "icon_button_color": "rgb(255, 255, 255)",
    },
)

if __name__ == "__main__":
    import gradio as gr
    from gradio.utils import get_space

    if not get_space():
        with gr.Blocks() as demo:
            gr.HTML(
                """
                <div style="display: flex; justify-content: center; align-items: center;">
                <h1>Gemini Conversation</h1>                
                </div>
                """
            )
            gr.Markdown(
                """# How to run this demo
                
                - Clone the repo - top right of the page click the vertical three dots and select "Clone repository"
                - Open the repo in a terminal and install the dependencies
                - Get a gemini API key [here](https://ai.google.dev/gemini-api/docs/api-key)
                - Create a `.env` file in the root of the repo and add the following:
                ```
                GEMINI_API_KEY=<your_gemini_api_key>
                ```
                - Run the app with `python app.py`
                - This will print the two URLs of the agents running locally
                - Use ngrok to exponse one agent to the internet. This is so that you can acces it from your phone
                - Use the ngrok URL to access the agent from your phone
                - Now, start the "teacher gemini" agent first. Then, start the "student gemini" agent. The student gemini will start talking to the teacher gemini. And the teacher gemini will respond!

                Important:
                - Make sure the audio sources are not too close to each other or too loud. Sometimes that causes them to talk over each other..
                - Feel free to modify the `system_instruction` to change the behavior of the agents.
                - You can also modify the `voice_name` to change the voice of the agents.
                - Have fun!
                """
            )
        demo.launch()

    import time

    _ = gemini_stream.ui.launch(server_port=7860, prevent_thread_lock=True)
    _ = gemini_stream_2.ui.launch(server_port=7861, prevent_thread_lock=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gemini_stream.ui.close()
        gemini_stream_2.ui.close()
