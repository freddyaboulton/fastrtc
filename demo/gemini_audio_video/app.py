# https://huggingface.co/spaces/freddyaboulton/gemini-audio-video-chat
# related demos: https://github.com/freddyaboulton/gradio-webrtc

import asyncio
import base64
import os
import time
import logging
import traceback
import cv2

import gradio as gr
import numpy as np
from google import genai
from fastrtc import (
    AsyncAudioVideoStreamHandler,
    WebRTC,
    async_aggregate_bytes_to_16bit,
    VideoEmitType,
    AudioEmitType,
    get_twilio_turn_credentials,
)
import requests  # Use requests for synchronous Twilio check

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global State ---
twilio_available = None  # Will be set *before* Gradio initialization
gemini_connected = False


# --- Helper Functions ---
def encode_audio(data: np.ndarray) -> dict:
    if not isinstance(data, np.ndarray):
        raise TypeError("encode_audio expected a numpy.ndarray")
    try:
        return {"mime_type": "audio/pcm", "data": base64.b64encode(data.tobytes()).decode("UTF-8")}
    except Exception as e:
        logger.error(f"Error encoding audio: {e}")
        raise

def encode_image(data: np.ndarray, quality: int = 85) -> dict:
    """
    Encodes a NumPy array (image) to a JPEG, Base64-encoded UTF-8 string using OpenCV.
    Handles various input data types.

    Args:
        data: A NumPy array of shape (n, n, 3).
        quality: JPEG quality (0-100).

    Returns:
        A dictionary with keys "mime_type" and "data".

    Raises:
        TypeError: If input is not a NumPy array.
        ValueError: If input shape is incorrect or contains NaN/Inf.
        Exception: If JPEG encoding fails.
    """

    # Input Validation (shape and dimensions)
    if not isinstance(data, np.ndarray):
        raise TypeError("Input must be a NumPy array.")
    if data.ndim != 3 or data.shape[2] != 3:
        raise ValueError("Input array must have shape (n, n, 3).")
    if 0 in data.shape:
        raise ValueError("Input array cannot have a dimension of size 0.")

    # Handle NaN/Inf (regardless of data type)
    if np.any(np.isnan(data)) or np.any(np.isinf(data)):
        raise ValueError("Input array contains NaN or Inf")

    # Normalize and convert to uint8
    if np.issubdtype(data.dtype, np.floating) or np.issubdtype(data.dtype, np.integer):
        scaled_data = cv2.normalize(data, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    else:
        raise TypeError("Input array must have a floating-point or integer data type.")

    # JPEG Encoding (with quality control and error handling)
    try:
        retval, buf = cv2.imencode(".jpg", scaled_data, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not retval:
            raise Exception("cv2.imencode failed")
    except Exception as e:
        raise Exception(f"JPEG encoding failed: {e}")

    # Base64 Encoding
    jpeg_bytes = np.array(buf).tobytes()
    base64_str = base64.b64encode(jpeg_bytes).decode('utf-8')

    return {"mime_type": "image/jpeg", "data": base64_str}

def check_twilio_availability_sync() -> bool:
    """Checks Twilio TURN server availability (synchronous version)."""
    global twilio_available
    retries = 3
    delay = 2

    for attempt in range(retries):
        try:
            logger.info(f"Attempting to get Twilio credentials (attempt {attempt + 1})...")
            credentials = get_twilio_turn_credentials()
            logger.info(f"Twilio credentials response: {credentials}")
            if credentials:
                twilio_available = True
                logger.info("Twilio TURN server available.")
                return True
        except requests.exceptions.RequestException as e:
            logger.warning(f"Attempt {attempt + 1}: {e}")
            logger.warning(traceback.format_exc())
            if attempt < retries - 1:
                time.sleep(delay)
        except Exception as e:
            logger.exception(f"Unexpected error checking Twilio: {e}")
            twilio_available = False
            return False

    twilio_available = False
    logger.warning("Twilio TURN server unavailable.")
    return False



# --- Gemini Handler Class ---
class GeminiHandler(AsyncAudioVideoStreamHandler):
    def __init__(
        self, expected_layout="mono", output_sample_rate=24000, output_frame_size=480
    ) -> None:
        super().__init__(
            expected_layout,
            output_sample_rate,
            output_frame_size,
            input_sample_rate=16000,
        )
        self.audio_queue = asyncio.Queue()
        self.video_queue = asyncio.Queue()
        self.quit = asyncio.Event()
        self.session = None
        self.last_frame_time = 0

    def copy(self) -> "GeminiHandler":
        return GeminiHandler(
            expected_layout=self.expected_layout,
            output_sample_rate=self.output_sample_rate,
            output_frame_size=self.output_frame_size,
        )

    async def video_receive(self, frame: np.ndarray):
        if self.session:
            try:
                if time.time() - self.last_frame_time > 1:
                    self.last_frame_time = time.time()
                    await self.session.send(encode_image(frame))
                    if self.latest_args[2] is not None:
                        await self.session.send(encode_image(self.latest_args[2]))
            except Exception as e:
                logger.error(f"Error sending video frame: {e}")
                gr.Warning("Error sending video to Gemini.")
        self.video_queue.put_nowait(frame)

    async def video_emit(self) -> VideoEmitType:
        try:
            return await self.video_queue.get()
        except asyncio.CancelledError:
            logger.info("Video emit cancelled.")
            return None
        except Exception as e:
            logger.exception(f"Error in video_emit: {e}")
            return None

    async def connect(self, api_key: str):
        global gemini_connected
        if self.session is None:
            try:
                client = genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
                config = {"response_modalities": ["AUDIO"]}
                async with client.aio.live.connect(
                    model="gemini-2.0-flash-exp", config=config
                ) as session:
                    self.session = session
                    gemini_connected = True
                    asyncio.create_task(self.receive_audio())
                    await self.quit.wait()
            except Exception as e:
                logger.error(f"Error connecting to Gemini: {e}")
                gemini_connected = False
                self.shutdown()
                gr.Warning(f"Failed to connect to Gemini: {e}")
            finally:
                update_gemini_status_sync()

    async def generator(self):
        if not self.session:
            logger.warning("Gemini session is not initialized.")
            return

        while not self.quit.is_set():
            try:
                await asyncio.sleep(0)  # Yield to the event loop
                if self.quit.is_set():
                    break
                turn = self.session.receive()
                async for response in turn:
                    if self.quit.is_set():
                        break # Exit inner loop if quit is set.
                    if data := response.data:
                        yield data
            except Exception as e:
                logger.error(f"Error receiving from Gemini: {e}")
                self.quit.set() # set quit if we error.
                break

    async def receive_audio(self):
        try:
            async for audio_response in async_aggregate_bytes_to_16bit(self.generator()):
                self.audio_queue.put_nowait(audio_response)
        except Exception as e:
            logger.exception(f"Error in receive_audio: {e}")

    async def receive(self, frame: tuple[int, np.ndarray]) -> None:
        _, array = frame
        array = array.squeeze()
        try:
            audio_message = encode_audio(array)
            if self.session:
                await self.session.send(audio_message)
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
            gr.Warning("Error sending audio to Gemini.")

    async def emit(self) -> AudioEmitType:
        if not self.args_set.is_set():
            await self.wait_for_args()
        if self.session is None:
            asyncio.create_task(self.connect(self.latest_args[1]))

        try:
            array = await self.audio_queue.get()
            return (self.output_sample_rate, array)
        except asyncio.CancelledError:
            logger.info("Audio emit cancelled.")
            return (self.output_sample_rate, np.array([]))
        except Exception as e:
            logger.exception(f"Error in emit: {e}")
            return (self.output_sample_rate, np.array([]))

    def shutdown(self) -> None:
        global gemini_connected
        gemini_connected = False
        logger.info("Shutting down GeminiHandler.")
        if self.session:
            try:
                #  await self.session.close()  # There is no async close
                pass
            except Exception:
                pass
        self.quit.set()  # Set quit *after* attempting to close the session
        self.connection = None
        self.args_set.clear()

        self.quit.clear()
        update_gemini_status_sync()


def update_gemini_status_sync():
    """Updates the Gemini status message (synchronous version)."""
    status = "✅ Gemini: Connected" if gemini_connected else "❌ Gemini: Disconnected"
    if 'demo' in locals() and demo.running:
        gr.update(value=status)



# --- Gradio UI ---
css = """
#video-source {max-width: 600px !important; max-height: 600 !important;}
"""

# Perform Twilio check *before* Gradio UI definition (synchronously)
if __name__ == "__main__":
    check_twilio_availability_sync()


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
    twilio_status_message = gr.Markdown("❓ Twilio: Checking...")
    gemini_status_message = gr.Markdown("❓ Gemini: Checking...")

    with gr.Row() as api_key_row:
        api_key = gr.Textbox(
            label="API Key",
            type="password",
            placeholder="Enter your API Key",
            value=os.getenv("GOOGLE_API_KEY"),
        )
    with gr.Row(visible=False) as row:
        with gr.Column():
            # Set rtc_configuration based on the *pre-checked* twilio_available
            rtc_config = get_twilio_turn_credentials() if twilio_available else None
            # Explicitly specify codecs (example - you might need to adjust)
            if rtc_config:
                rtc_config['codecs'] = ['VP8', 'H264']  # Prefer VP8, then H.264
            webrtc = WebRTC(
                label="Video Chat",
                modality="audio-video",
                mode="send-receive",
                elem_id="video-source",
                rtc_configuration=rtc_config,
                icon="https://www.gstatic.com/lamda/images/gemini_favicon_f069958c85030456e93de685481c559f160ea06b.png",
                pulse_color="rgb(35, 157, 225)",
                icon_button_color="rgb(35, 157, 225)",
            )
        with gr.Column():
            image_input = gr.Image(label="Image", type="numpy", sources=["upload", "clipboard"])


    def update_twilio_status_ui():
        if twilio_available:
            message = "✅ Twilio: Available"
        else:
            message = "❌ Twilio: Unavailable (connection may be less reliable)"
        return gr.update(value=message)

    demo.load(update_twilio_status_ui, [], [twilio_status_message])

    handler = GeminiHandler()
    webrtc.stream(
        handler,
        inputs=[webrtc, api_key, image_input],
        outputs=[webrtc],
        time_limit=90,
        concurrency_limit=None,
    )


    def check_api_key(api_key_str):
        if not api_key_str:
            return (
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(value="Please enter a valid API key"),
                gr.update(value="❓ Gemini: Checking..."),
            )
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(value=""),
            gr.update(value="❓ Gemini: Checking..."),
        )

    api_key.submit(
        check_api_key,
        [api_key],
        [api_key_row, row, twilio_status_message, gemini_status_message],
    )

    # If API key is already set via environment variables, hide the API key row and show content
    if os.getenv("GOOGLE_API_KEY"):
        demo.load(
            lambda: (gr.update(visible=False), gr.update(visible=True)),
            None,
            [api_key_row, row],
        )

demo.launch()
