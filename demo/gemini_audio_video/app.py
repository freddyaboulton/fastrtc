import asyncio
import base64
import os
import time
from io import BytesIO

import gradio as gr
import numpy as np
from dotenv import load_dotenv
from fastrtc import (
    AsyncAudioVideoStreamHandler,
    Stream,
    WebRTC,
    get_twilio_turn_credentials,
)
from google import genai
from gradio.utils import get_space
from PIL import Image

load_dotenv()


def encode_audio(data: np.ndarray) -> dict:
    """Encode Audio data to send to the server"""
    return {
        "mime_type": "audio/pcm",
        "data": base64.b64encode(data.tobytes()).decode("UTF-8"),
    }


def encode_image(data: np.ndarray) -> dict:
    with BytesIO() as output_bytes:
        pil_image = Image.fromarray(data)
        pil_image.save(output_bytes, "JPEG")
        bytes_data = output_bytes.getvalue()
    base64_str = str(base64.b64encode(bytes_data), "utf-8")
    return {"mime_type": "image/jpeg", "data": base64_str}


class GeminiHandler(AsyncAudioVideoStreamHandler):
    def __init__(
        self,
    ) -> None:
        super().__init__(
            "mono",
            output_sample_rate=24000,
            input_sample_rate=16000,
        )
        self.audio_queue = asyncio.Queue()
        self.video_queue = asyncio.Queue()
        self.session = None
        self.last_frame_time = 0
        self.quit = asyncio.Event()

    def copy(self) -> "GeminiHandler":
        return GeminiHandler()

    async def start_up(self):
        client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"), http_options={"api_version": "v1alpha"}
        )
        config = {"response_modalities": ["AUDIO"]}
        async with client.aio.live.connect(
            model="gemini-2.0-flash-exp", config=config
        ) as session:
            self.session = session
            print("set session")
            while not self.quit.is_set():
                turn = self.session.receive()
                async for response in turn:
                    if data := response.data:
                        audio = np.frombuffer(data, dtype=np.int16).reshape(1, -1)
                        self.audio_queue.put_nowait(audio)

    async def video_receive(self, frame: np.ndarray):
        if self.session:
            # send image every 1 second
            print(time.time() - self.last_frame_time)
            if time.time() - self.last_frame_time > 1:
                self.last_frame_time = time.time()
                await self.session.send(input=encode_image(frame))
                if self.latest_args[1] is not None:
                    await self.session.send(input=encode_image(self.latest_args[1]))

        self.video_queue.put_nowait(frame)

    async def video_emit(self):
        return await self.video_queue.get()

    async def receive(self, frame: tuple[int, np.ndarray]) -> None:
        _, array = frame
        array = array.squeeze()
        audio_message = encode_audio(array)
        if self.session:
            await self.session.send(input=audio_message)

    async def emit(self):
        array = await self.audio_queue.get()
        return (self.output_sample_rate, array)

    async def shutdown(self) -> None:
        if self.session:
            self.quit.set()
            await self.session._websocket.close()
            self.quit.clear()


stream = Stream(
    handler=GeminiHandler(),
    modality="audio-video",
    mode="send-receive",
    rtc_configuration=get_twilio_turn_credentials()
    if get_space() == "spaces"
    else None,
    time_limit=90 if get_space() else None,
    additional_inputs=[
        gr.Image(label="Image", type="numpy", sources=["upload", "clipboard"])
    ],
    ui_args={
        "icon": "https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png",
        "pulse_color": "rgb(255, 255, 255)",
        "icon_button_color": "rgb(255, 255, 255)",
        "title": "Gemini Audio Video Chat",
    },
)

css = """
#video-source {max-width: 600px !important; max-height: 600 !important;}
"""

with gr.Blocks(css=css) as demo:
    gr.HTML(
        """
    <div style='display: flex; align-items: center; justify-content: center; gap: 20px'>
        <div style="background-color: var(--block-background-fill); border-radius: 8px">
            <img src="https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png" style="width: 100px; height: 100px;">
        </div>
        <div>
            <h1>Gen AI SDK Voice Chat</h1>
            <p>Speak with Gemini using real-time audio + video streaming</p>
            <p>Powered by <a href="https://gradio.app/">Gradio</a> and <a href=https://freddyaboulton.github.io/gradio-webrtc/">WebRTC</a>⚡️</p>
            <p>Get an API Key <a href="https://support.google.com/googleapi/answer/6158862?hl=en">here</a></p>
        </div>
    </div>
    """
    )
    with gr.Row() as row:
        with gr.Column():
            webrtc = WebRTC(
                label="Video Chat",
                modality="audio-video",
                mode="send-receive",
                elem_id="video-source",
                rtc_configuration=get_twilio_turn_credentials()
                if get_space() == "spaces"
                else None,
                icon="https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png",
                pulse_color="rgb(255, 255, 255)",
                icon_button_color="rgb(255, 255, 255)",
            )
        with gr.Column():
            image_input = gr.Image(
                label="Image", type="numpy", sources=["upload", "clipboard"]
            )

        webrtc.stream(
            GeminiHandler(),
            inputs=[webrtc, image_input],
            outputs=[webrtc],
            time_limit=60 if get_space() else None,
            concurrency_limit=2 if get_space() else None,
        )

stream.ui = demo


if __name__ == "__main__":
    if (mode := os.getenv("MODE")) == "UI":
        stream.ui.launch(server_port=7860)
    elif mode == "PHONE":
        raise ValueError("Phone mode not supported for this demo")
    else:
        stream.ui.launch(server_port=7860)
