import asyncio
import base64
import json
from pathlib import Path

import aiohttp  # pip install aiohttp
import gradio as gr
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastrtc import (
    AdditionalOutputs,
    AsyncStreamHandler,
    Stream,
    get_twilio_turn_credentials,
    wait_for_item,
)
from gradio.utils import get_space

load_dotenv()
cur_dir = Path(__file__).parent
load_dotenv("key.env")
# sd.default.device = (3, 3)  # (Input-Gerät, Output-Gerät)

# print(f"Used Mic: {sd.query_devices(3)['name']}")
# print(f"Used Speaker: {sd.query_devices(3)['name']}")
SAMPLE_RATE = 24000

instruction = """
<Role>
You a helpful assistant.
"""


class AzureAudioHandler(AsyncStreamHandler):
    def __init__(self) -> None:
        super().__init__(
            expected_layout="mono",
            output_sample_rate=SAMPLE_RATE,
            input_sample_rate=SAMPLE_RATE,
        )
        self.ws = None
        self.session = None
        self.output_queue = asyncio.Queue()
        # This internal buffer is not used directly in receive_messages.
        # Instead, multiple audio chunks are collected in the emit() method.
        # If needed, a continuous buffer can also be implemented here.
        # self.audio_buffer = bytearray()

    def copy(self):
        return AzureAudioHandler()

    async def start_up(self):
        """Connects to the Azure Real-time Audio API via WebSocket using aiohttp."""
        # Replace the following placeholders with your actual Azure values:
        azure_api_key = "your-api-key"  # e.g., "your-api-key"
        azure_resource_name = "your-resource-name"  # e.g., "aigdopenai"
        deployment_id = "your-deployment-id"  # e.g., "gpt-4o-realtime-preview"
        api_version = "2024-10-01-preview"
        azure_endpoint = (
            f"wss://{azure_resource_name}.openai.azure.com/openai/realtime"
            f"?api-version={api_version}&deployment={deployment_id}"
        )
        headers = {"api-key": azure_api_key}

        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(azure_endpoint, headers=headers)
        # Send initial session parameters
        session_update_message = {
            "type": "session.update",
            "session": {
                "turn_detection": {"type": "server_vad"},
                "instructions": instruction,
                "voice": "ballad",  # Possible voices see  https://platform.openai.com/docs/guides/realtime-model-capabilities#voice-options
            },
        }

        await self.ws.send_str(json.dumps(session_update_message))
        # Start receiving messages asynchronously
        asyncio.create_task(self.receive_messages())

    async def receive_messages(self):
        """Handles incoming WebSocket messages and processes them accordingly."""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                print("Received event:", msg.data)  # Debug output
                event = json.loads(msg.data)
                event_type = event.get("type")
                if event_type in ["final", "response.audio_transcript.done"]:
                    transcript = event.get("transcript", "")

                    # Wrap the transcript in an object with a .transcript attribute
                    class TranscriptEvent:
                        pass

                    te = TranscriptEvent()
                    te.transcript = transcript
                    await self.output_queue.put(AdditionalOutputs(te))
                elif event_type == "partial":
                    print("Partial transcript:", event.get("transcript", ""))
                elif event_type == "response.audio.delta":
                    audio_message = event.get("delta")
                    if audio_message:
                        try:
                            audio_bytes = base64.b64decode(audio_message)
                            # Assuming 16-bit PCM (int16)
                            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                            # Interpret as mono audio:
                            audio_array = audio_array.reshape(1, -1)
                            # Instead of playing the audio, add the chunk to the output queue
                            await self.output_queue.put(
                                (self.output_sample_rate, audio_array)
                            )
                        except Exception as e:
                            print("Error processing audio data:", e)
                else:
                    print("Unknown event:", event)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break

    async def receive(self, frame: tuple[int, np.ndarray]) -> None:
        """Sends received audio frames to the WebSocket."""
        if not self.ws or self.ws.closed:
            return
        try:
            _, array = frame
            array = array.squeeze()
            audio_message = base64.b64encode(array.tobytes()).decode("utf-8")
            message = {"type": "input_audio_buffer.append", "audio": audio_message}
            await self.ws.send_str(json.dumps(message))
        except aiohttp.ClientConnectionError as e:
            print("Connection closed while sending:", e)
            return

    async def emit(self) -> tuple[int, np.ndarray] | AdditionalOutputs | None:
        """
        Collects multiple audio chunks from the queue before returning them as a single contiguous audio array.
        This helps smooth playback.
        """
        item = await wait_for_item(self.output_queue)
        # If it's a transcript event, return it immediately.
        if not isinstance(item, tuple):
            return item
        # Otherwise, it is an audio chunk (sample_rate, audio_array)
        sample_rate, first_chunk = item
        audio_chunks = [first_chunk]
        # Define a minimum length (e.g., 0.1 seconds)
        min_samples = int(SAMPLE_RATE * 0.1)  # 0.1 sec
        # Collect more audio chunks until we have enough samples
        while audio_chunks and audio_chunks[0].shape[1] < min_samples:
            try:
                extra = self.output_queue.get_nowait()
                if isinstance(extra, tuple):
                    _, chunk = extra
                    audio_chunks.append(chunk)
                else:
                    # If it's not an audio chunk, put it back
                    await self.output_queue.put(extra)
                    break
            except asyncio.QueueEmpty:
                break
        # Concatenate collected chunks along the time axis (axis=1)
        full_audio = np.concatenate(audio_chunks, axis=1)
        return (sample_rate, full_audio)

    async def shutdown(self) -> None:
        """Closes the WebSocket and session properly."""
        if self.ws:
            await self.ws.close()
            self.ws = None
        if self.session:
            await self.session.close()
            self.session = None


def update_chatbot(chatbot: list[dict], response) -> list[dict]:
    """Appends the AI assistant's transcript response to the chatbot messages."""
    chatbot.append({"role": "assistant", "content": response.transcript})
    return chatbot


chatbot = gr.Chatbot(type="messages")
latest_message = gr.Textbox(type="text", visible=False)
stream = Stream(
    AzureAudioHandler(),
    mode="send-receive",
    modality="audio",
    additional_inputs=[chatbot],
    additional_outputs=[chatbot],
    additional_outputs_handler=update_chatbot,
    rtc_configuration=get_twilio_turn_credentials() if get_space() else None,
    concurrency_limit=5 if get_space() else None,
    time_limit=90 if get_space() else None,
)

app = FastAPI()
stream.mount(app)


@app.get("/")
async def _():
    rtc_config = get_twilio_turn_credentials() if get_space() else None
    html_content = (cur_dir / "index.html").read_text()
    html_content = html_content.replace("__RTC_CONFIGURATION__", json.dumps(rtc_config))
    return HTMLResponse(content=html_content)


@app.get("/outputs")
def _(webrtc_id: str):
    async def output_stream():
        import json

        async for output in stream.output_stream(webrtc_id):
            s = json.dumps({"role": "assistant", "content": output.args[0].transcript})
            yield f"event: output\ndata: {s}\n\n"

    return StreamingResponse(output_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import os

    if (mode := os.getenv("MODE")) == "UI":
        stream.ui.launch(server_port=7860)
    elif mode == "PHONE":
        stream.fastphone(host="0.0.0.0", port=7860)
    else:
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=7860)
