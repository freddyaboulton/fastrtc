
Any of the parameters for the `Stream` class can be passed to the [`WebRTC`](../userguide/gradio) component directly.

## Track Constraints


You can specify the `track_constraints` parameter to control how the data is streamed to the server. The full documentation on track constraints is [here](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackConstraints#constraints).

For example, you can control the size of the frames captured from the webcam like so:

```python
track_constraints = {
    "width": {"exact": 500},
    "height": {"exact": 500},
    "frameRate": {"ideal": 30},
}
webrtc = Stream(
    handler=...,
    track_constraints=track_constraints,
    modality="video",
    mode="send-receive")
```


!!! warning

    WebRTC may not enforce your constraints. For example, it may rescale your video
    (while keeping the same resolution) in order to maintain the desired frame rate (or reach a better one). If you really want to enforce height, width and resolution constraints, use the `rtp_params` parameter as set `"degradationPreference": "maintain-resolution"`. 

    ```python
    image = Stream(
        modality="video",
        mode="send",
        track_constraints=track_constraints,
        rtp_params={"degradationPreference": "maintain-resolution"}
    )
    ```

## The RTC Configuration

You can configure how the connection is created on the client by passing an `rtc_configuration` parameter to the `WebRTC` component constructor.
See the list of available arguments [here](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/RTCPeerConnection#configuration).

!!! warning
    When deploying on a remote server, the `rtc_configuration` parameter must be passed in. See [Deployment](../deployment).

## Reply on Pause Voice-Activity-Detection

The `ReplyOnPause` class runs a Voice Activity Detection (VAD) algorithm to determine when a user has stopped speaking.

1. First, the algorithm determines when the user has started speaking.
2. Then it groups the audio into chunks.
3. On each chunk, we determine the length of human speech in the chunk.
4. If the length of human speech is below a threshold, a pause is detected.

The following parameters control this argument:

```python
from fastrtc import AlgoOptions, ReplyOnPause, Stream

options = AlgoOptions(audio_chunk_duration=0.6, # (1)
                      started_talking_threshold=0.2, # (2)
                      speech_threshold=0.1, # (3)
                      )

Stream(
    handler=ReplyOnPause(..., algo_options=algo_options),
    modality="audio",
    mode="send-receive"
)
```

1. This is the length (in seconds) of audio chunks.
2. If the chunk has more than 0.2 seconds of speech, the user started talking.
3. If, after the user started speaking, there is a chunk with less than 0.1 seconds of speech, the user stopped speaking.


## Stream Handler Input Audio

You can configure the sampling rate of the audio passed to the `ReplyOnPause` or `StreamHandler` instance with the `input_sampling_rate` parameter. The current default is `48000`

```python
from fastrtc import ReplyOnPause, Stream

stream = Stream(
    handler=ReplyOnPause(..., input_sampling_rate=24000),
    modality="audio",
    mode="send-receive"
)
```


## Stream Handler Output Audio

You can configure the output sampling rate of `ReplyOnPause` (and any `StreamHandler`) 
with the `output_sample_rate` and parameter. For example:

```python
from fastrtc import ReplyOnPause, Stream

stream = Stream(
    handler=ReplyOnPause(..., output_sample_rate=16000),
    modality="audio",
    mode="send-receive"
)
```

## Audio Icon

You can display an icon of your choice instead of the default wave animation for audio streaming.
Pass any local path or url to an image (svg, png, jpeg) to the components `icon` parameter. This will display the icon as a circular button. When audio is sent or recevied (depending on the `mode` parameter) a pulse animation will emanate from the button.

You can control the button color and pulse color with `icon_button_color` and `pulse_color` parameters. They can take any valid css color.

!!! warning

    The `icon` parameter is only supported in the `WebRTC` component.

=== "Code"
    ``` python
    audio = WebRTC(
        label="Stream",
        rtc_configuration=rtc_configuration,
        mode="receive",
        modality="audio",
        icon="phone-solid.svg",
    )
    ```
    <img src="https://github.com/user-attachments/assets/fd2e70a3-1698-4805-a8cb-9b7b3bcf2198">
=== "Code Custom colors"
    ``` python
    audio = WebRTC(
        label="Stream",
        rtc_configuration=rtc_configuration,
        mode="receive",
        modality="audio",
        icon="phone-solid.svg",
        icon_button_color="black",
        pulse_color="black",
    )
    ```
    <img src="https://github.com/user-attachments/assets/39e9bb0b-53fb-448e-be44-d37f6785b4b6">


## Changing the Button Text

You can supply a `button_labels` dictionary to change the text displayed in the `Start`, `Stop` and `Waiting` buttons that are displayed in the UI.
The keys must be `"start"`, `"stop"`, and `"waiting"`.

!!! warning

    The `button_labels` parameter is only supported in the `WebRTC` component.

``` python
webrtc = WebRTC(
    label="Video Chat",
    modality="audio-video",
    mode="send-receive",
    button_labels={"start": "Start Talking to Gemini"}
)
```

<img src="https://github.com/user-attachments/assets/04be0b95-189c-4b4b-b8cc-1eb598529dd3" />
