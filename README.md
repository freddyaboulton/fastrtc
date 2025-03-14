<div style='text-align: center; margin-bottom: 1rem; display: flex; justify-content: center; align-items: center;'>
    <h1 style='color: white; margin: 0;'>FastRTC</h1>
    <img src='https://huggingface.co/datasets/freddyaboulton/bucket/resolve/main/fastrtc_logo_small.png'
         alt="FastRTC Logo" 
         style="margin-right: 10px;">
</div>

<div style="display: flex; flex-direction: row; justify-content: center">
<img style="display: block; padding-right: 5px; height: 20px;" alt="Static Badge" src="https://img.shields.io/pypi/v/fastrtc"> 
<a href="https://github.com/freddyaboulton/fastrtc" target="_blank"><img alt="Static Badge" src="https://img.shields.io/badge/github-white?logo=github&logoColor=black"></a>
</div>

<h3 style='text-align: center'>
The Real-Time Communication Library for Python. 
</h3>

Turn any python function into a real-time audio and video stream over WebRTC or WebSockets.

## Installation

```bash
pip install fastrtc
```

to use built-in pause detection (see [ReplyOnPause](https://fastrtc.org/userguide/audio/#reply-on-pause)), and text to speech (see [Text To Speech](https://fastrtc.org/userguide/audio/#text-to-speech)), install the `vad` and `tts` extras:

```bash
pip install "fastrtc[vad, tts]"
```

## Key Features

- 🗣️ Automatic Voice Detection and Turn Taking built-in, only worry about the logic for responding to the user.
- 💻 Automatic UI - Use the `.ui.launch()` method to launch the webRTC-enabled built-in Gradio UI.
- 🔌 Automatic WebRTC Support - Use the `.mount(app)` method to mount the stream on a FastAPI app and get a webRTC endpoint for your own frontend! 
- ⚡️ Websocket Support - Use the `.mount(app)` method to mount the stream on a FastAPI app and get a websocket endpoint for your own frontend! 
- 📞 Automatic Telephone Support - Use the `fastphone()` method of the stream to launch the application and get a free temporary phone number!
- 🤖 Completely customizable backend - A `Stream` can easily be mounted on a FastAPI app so you can easily extend it to fit your production application. See the [Talk To Claude](https://huggingface.co/spaces/fastrtc/talk-to-claude) demo for an example on how to serve a custom JS frontend.

## Docs

[https://fastrtc.org](https://fastrtc.org)

## Examples
See the [Cookbook](https://fastrtc.org/cookbook/) for examples of how to use the library.

<table>
<tr>
<td width="50%">
<h3>🗣️👀 Gemini Audio Video Chat</h3>
<p>Stream BOTH your webcam video and audio feeds to Google Gemini. You can also upload images to augment your conversation!</p>
<video width="100%" src="https://github.com/user-attachments/assets/9636dc97-4fee-46bb-abb8-b92e69c08c71" controls></video>
<p>
<a href="https://huggingface.co/spaces/freddyaboulton/gemini-audio-video-chat">Demo</a> |
<a href="https://huggingface.co/spaces/freddyaboulton/gemini-audio-video-chat/blob/main/app.py">Code</a>
</p>
</td>
<td width="50%">
<h3>🗣️ Google Gemini Real Time Voice API</h3>
<p>Talk to Gemini in real time using Google's voice API.</p>
<video width="100%" src="https://github.com/user-attachments/assets/ea6d18cb-8589-422b-9bba-56332d9f61de" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/talk-to-gemini">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/talk-to-gemini/blob/main/app.py">Code</a>
</p>
</td>
</tr>

<tr>
<td width="50%">
<h3>🗣️ OpenAI Real Time Voice API</h3>
<p>Talk to ChatGPT in real time using OpenAI's voice API.</p>
<video width="100%" src="https://github.com/user-attachments/assets/178bdadc-f17b-461a-8d26-e915c632ff80" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/talk-to-openai">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/talk-to-openai/blob/main/app.py">Code</a>
</p>
</td>
<td width="50%">
<h3>🤖 Hello Computer</h3>
<p>Say computer before asking your question!</p>
<video width="100%" src="https://github.com/user-attachments/assets/afb2a3ef-c1ab-4cfb-872d-578f895a10d5" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/hello-computer">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/hello-computer/blob/main/app.py">Code</a>
</p>
</td>
</tr>

<tr>
<td width="50%">
<h3>🤖 Llama Code Editor</h3>
<p>Create and edit HTML pages with just your voice! Powered by SambaNova systems.</p>
<video width="100%" src="https://github.com/user-attachments/assets/98523cf3-dac8-4127-9649-d91a997e3ef5" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/llama-code-editor">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/llama-code-editor/blob/main/app.py">Code</a>
</p>
</td>
<td width="50%">
<h3>🗣️ Talk to Claude</h3>
<p>Use the Anthropic and Play.Ht APIs to have an audio conversation with Claude.</p>
<video width="100%" src="https://github.com/user-attachments/assets/fb6ef07f-3ccd-444a-997b-9bc9bdc035d3" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/talk-to-claude">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/talk-to-claude/blob/main/app.py">Code</a>
</p>
</td>
</tr>

<tr>
<td width="50%">
<h3>🎵 Whisper Transcription</h3>
<p>Have whisper transcribe your speech in real time!</p>
<video width="100%" src="https://github.com/user-attachments/assets/87603053-acdc-4c8a-810f-f618c49caafb" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/whisper-realtime">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/whisper-realtime/blob/main/app.py">Code</a>
</p>
</td>
<td width="50%">
<h3>📷 Yolov10 Object Detection</h3>
<p>Run the Yolov10 model on a user webcam stream in real time!</p>
<video width="100%" src="https://github.com/user-attachments/assets/f82feb74-a071-4e81-9110-a01989447ceb" controls></video>
<p>
<a href="https://huggingface.co/spaces/fastrtc/object-detection">Demo</a> |
<a href="https://huggingface.co/spaces/fastrtc/object-detection/blob/main/app.py">Code</a>
</p>
</td>
</tr>

<tr>
<td width="50%">
<h3>🗣️ Kyutai Moshi</h3>
<p>Kyutai's moshi is a novel speech-to-speech model for modeling human conversations.</p>
<video width="100%" src="https://github.com/user-attachments/assets/becc7a13-9e89-4a19-9df2-5fb1467a0137" controls></video>
<p>
<a href="https://huggingface.co/spaces/freddyaboulton/talk-to-moshi">Demo</a> |
<a href="https://huggingface.co/spaces/freddyaboulton/talk-to-moshi/blob/main/app.py">Code</a>
</p>
</td>
<td width="50%">
<h3>🗣️ Hello Llama: Stop Word Detection</h3>
<p>A code editor built with Llama 3.3 70b that is triggered by the phrase "Hello Llama". Build a Siri-like coding assistant in 100 lines of code!</p>
<video width="100%" src="https://github.com/user-attachments/assets/3e10cb15-ff1b-4b17-b141-ff0ad852e613" controls></video>
<p>
<a href="https://huggingface.co/spaces/freddyaboulton/hey-llama-code-editor">Demo</a> |
<a href="https://huggingface.co/spaces/freddyaboulton/hey-llama-code-editor/blob/main/app.py">Code</a>
</p>
</td>
</tr>
</table>

## Usage

This is an shortened version of the official [usage guide](https://freddyaboulton.github.io/gradio-webrtc/user-guide/). 

- `.ui.launch()`: Launch a built-in UI for easily testing and sharing your stream. Built with [Gradio](https://www.gradio.app/).
- `.fastphone()`: Get a free temporary phone number to call into your stream. Hugging Face token required.
- `.mount(app)`: Mount the stream on a [FastAPI](https://fastapi.tiangolo.com/) app. Perfect for integrating with your already existing production system.


## Quickstart

### Echo Audio

```python
from fastrtc import Stream, ReplyOnPause
import numpy as np

def echo(audio: tuple[int, np.ndarray]):
    # The function will be passed the audio until the user pauses
    # Implement any iterator that yields audio
    # See "LLM Voice Chat" for a more complete example
    yield audio

stream = Stream(
    handler=ReplyOnPause(echo),
    modality="audio", 
    mode="send-receive",
)
```

### LLM Voice Chat

```py
from fastrtc import (
    ReplyOnPause, AdditionalOutputs, Stream,
    audio_to_bytes, aggregate_bytes_to_16bit
)
import gradio as gr
from groq import Groq
import anthropic
from elevenlabs import ElevenLabs

groq_client = Groq()
claude_client = anthropic.Anthropic()
tts_client = ElevenLabs()


# See "Talk to Claude" in Cookbook for an example of how to keep 
# track of the chat history.
def response(
    audio: tuple[int, np.ndarray],
):
    prompt = groq_client.audio.transcriptions.create(
        file=("audio-file.mp3", audio_to_bytes(audio)),
        model="whisper-large-v3-turbo",
        response_format="verbose_json",
    ).text
    response = claude_client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    response_text = " ".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    )
    iterator = tts_client.text_to_speech.convert_as_stream(
        text=response_text,
        voice_id="JBFqnCBsd6RMkjVDRZzb",
        model_id="eleven_multilingual_v2",
        output_format="pcm_24000"
        
    )
    for chunk in aggregate_bytes_to_16bit(iterator):
        audio_array = np.frombuffer(chunk, dtype=np.int16).reshape(1, -1)
        yield (24000, audio_array)

stream = Stream(
    modality="audio",
    mode="send-receive",
    handler=ReplyOnPause(response),
)
```

### Webcam Stream

```python
from fastrtc import Stream
import numpy as np


def flip_vertically(image):
    return np.flip(image, axis=0)


stream = Stream(
    handler=flip_vertically,
    modality="video",
    mode="send-receive",
)
```

### Object Detection

```python
from fastrtc import Stream
import gradio as gr
import cv2
from huggingface_hub import hf_hub_download
from .inference import YOLOv10

model_file = hf_hub_download(
    repo_id="onnx-community/yolov10n", filename="onnx/model.onnx"
)

# git clone https://huggingface.co/spaces/fastrtc/object-detection
# for YOLOv10 implementation
model = YOLOv10(model_file)

def detection(image, conf_threshold=0.3):
    image = cv2.resize(image, (model.input_width, model.input_height))
    new_image = model.detect_objects(image, conf_threshold)
    return cv2.resize(new_image, (500, 500))

stream = Stream(
    handler=detection,
    modality="video", 
    mode="send-receive",
    additional_inputs=[
        gr.Slider(minimum=0, maximum=1, step=0.01, value=0.3)
    ]
)
```

## Running the Stream

Run:

### Gradio

```py
stream.ui.launch()
```

### Telephone (Audio Only)

    ```py
    stream.fastphone()
    ```

### FastAPI

```py
app = FastAPI()
stream.mount(app)

# Optional: Add routes
@app.get("/")
async def _():
    return HTMLResponse(content=open("index.html").read())

# uvicorn app:app --host 0.0.0.0 --port 8000
```

# Star History

[![Star History Chart](https://api.star-history.com/svg?repos=freddyaboulton/fastrtc&type=Date)](https://star-history.com/#freddyaboulton/fastrtc&Date)