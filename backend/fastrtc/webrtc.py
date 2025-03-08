"""gr.WebRTC() component."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    Iterable,
    Literal,
    ParamSpec,
    Sequence,
    TypeVar,
    cast,
)

import anyio
import anyio.to_thread
from gradio import wasm_utils
from gradio.components.base import Component, server
from gradio_client import handle_file

from .tracks import (
    AudioVideoStreamHandlerImpl,
    StreamHandler,
    StreamHandlerBase,
    StreamHandlerImpl,
    VideoEventHandler,
)
from .webrtc_connection_mixin import WebRTCConnectionMixin

if TYPE_CHECKING:
    from gradio.blocks import Block
    from gradio.components import Timer

if wasm_utils.IS_WASM:
    raise ValueError("Not supported in gradio-lite!")


logger = logging.getLogger(__name__)


# For the return type
R = TypeVar("R")
# For the parameter specification
P = ParamSpec("P")


class WebRTC(Component, WebRTCConnectionMixin):
    """
    Creates a video component that can be used to upload/record videos (as an input) or display videos (as an output).
    For the video to be playable in the browser it must have a compatible container and codec combination. Allowed
    combinations are .mp4 with h264 codec, .ogg with theora codec, and .webm with vp9 codec. If the component detects
    that the output video would not be playable in the browser it will attempt to convert it to a playable mp4 video.
    If the conversion fails, the original video is returned.

    Demos: video_identity_2
    """

    EVENTS = ["tick", "state_change"]

    def __init__(
        self,
        value: None = None,
        height: int | str | None = None,
        width: int | str | None = None,
        label: str | None = None,
        every: Timer | float | None = None,
        inputs: Component | Sequence[Component] | set[Component] | None = None,
        show_label: bool | None = None,
        container: bool = True,
        scale: int | None = None,
        min_width: int = 160,
        interactive: bool | None = None,
        visible: bool = True,
        elem_id: str | None = None,
        elem_classes: list[str] | str | None = None,
        render: bool = True,
        key: int | str | None = None,
        mirror_webcam: bool = True,
        rtc_configuration: dict[str, Any] | None | Callable[[], dict[str, Any]] = None,
        track_constraints: dict[str, Any] | None = None,
        time_limit: float | None = None,
        mode: Literal["send-receive", "receive", "send"] = "send-receive",
        modality: Literal["video", "audio", "audio-video"] = "video",
        rtp_params: dict[str, Any] | None = None,
        icon: str | None = None,
        icon_button_color: str | None = None,
        pulse_color: str | None = None,
        icon_radius: int | None = None,
        button_labels: dict | None = None,
    ):
        """
        Parameters:
            value: path or URL for the default value that WebRTC component is going to take. Can also be a tuple consisting of (video filepath, subtitle filepath). If a subtitle file is provided, it should be of type .srt or .vtt. Or can be callable, in which case the function will be called whenever the app loads to set the initial value of the component.
            format: the file extension with which to save video, such as 'avi' or 'mp4'. This parameter applies both when this component is used as an input to determine which file format to convert user-provided video to, and when this component is used as an output to determine the format of video returned to the user. If None, no file format conversion is done and the video is kept as is. Use 'mp4' to ensure browser playability.
            height: The height of the component, specified in pixels if a number is passed, or in CSS units if a string is passed. This has no effect on the preprocessed video file, but will affect the displayed video.
            width: The width of the component, specified in pixels if a number is passed, or in CSS units if a string is passed. This has no effect on the preprocessed video file, but will affect the displayed video.
            label: the label for this component. Appears above the component and is also used as the header if there are a table of examples for this component. If None and used in a `gr.Interface`, the label will be the name of the parameter this component is assigned to.
            every: continously calls `value` to recalculate it if `value` is a function (has no effect otherwise). Can provide a Timer whose tick resets `value`, or a float that provides the regular interval for the reset Timer.
            inputs: components that are used as inputs to calculate `value` if `value` is a function (has no effect otherwise). `value` is recalculated any time the inputs change.
            show_label: if True, will display label.
            container: if True, will place the component in a container - providing some extra padding around the border.
            scale: relative size compared to adjacent Components. For example if Components A and B are in a Row, and A has scale=2, and B has scale=1, A will be twice as wide as B. Should be an integer. scale applies in Rows, and to top-level Components in Blocks where fill_height=True.
            min_width: minimum pixel width, will wrap if not sufficient screen space to satisfy this value. If a certain scale value results in this Component being narrower than min_width, the min_width parameter will be respected first.
            interactive: if True, will allow users to upload a video; if False, can only be used to display videos. If not provided, this is inferred based on whether the component is used as an input or output.
            visible: if False, component will be hidden.
            elem_id: an optional string that is assigned as the id of this component in the HTML DOM. Can be used for targeting CSS styles.
            elem_classes: an optional list of strings that are assigned as the classes of this component in the HTML DOM. Can be used for targeting CSS styles.
            render: if False, component will not render be rendered in the Blocks context. Should be used if the intention is to assign event listeners now but render the component later.
            key: if assigned, will be used to assume identity across a re-render. Components that have the same key across a re-render will have their value preserved.
            mirror_webcam: if True webcam will be mirrored. Default is True.
            rtc_configuration: WebRTC configuration options. See https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/RTCPeerConnection . If running the demo on a remote server, you will need to specify a rtc_configuration. See https://freddyaboulton.github.io/gradio-webrtc/deployment/
            track_constraints: Media track constraints for WebRTC. For example, to set video height, width use {"width": {"exact": 800}, "height": {"exact": 600}, "aspectRatio": {"exact": 1.33333}}
            time_limit: Maximum duration in seconds for recording.
            mode: WebRTC mode - "send-receive", "receive", or "send".
            modality: Type of media - "video" or "audio".
            rtp_params: See https://developer.mozilla.org/en-US/docs/Web/API/RTCRtpSender/setParameters. If you are changing the video resolution, you can set this to {"degradationPreference": "maintain-framerate"} to keep the frame rate consistent.
            icon: Icon to display on the button instead of the wave animation. The icon should be a path/url to a .svg/.png/.jpeg file.
            icon_button_color: Color of the icon button. Default is var(--color-accent) of the demo theme.
            pulse_color: Color of the pulse animation. Default is var(--color-accent) of the demo theme.
            button_labels: Text to display on the audio or video start, stop, waiting buttons. Dict with keys "start", "stop", "waiting" mapping to the text to display on the buttons.
            icon_radius: Border radius of the icon button expressed as a percentage of the button size. Default is 50%
        """
        WebRTCConnectionMixin.__init__(self)
        self.time_limit = time_limit
        self.height = height
        self.width = width
        self.mirror_webcam = mirror_webcam
        self.concurrency_limit = 1
        self.rtc_configuration = rtc_configuration
        self.mode = mode
        self.modality = modality
        self.icon_button_color = icon_button_color
        self.icon_radius = icon_radius
        self.pulse_color = pulse_color
        self.rtp_params = rtp_params or {}
        self.button_labels = {
            "start": "",
            "stop": "",
            "waiting": "",
            **(button_labels or {}),
        }
        if track_constraints is None and modality == "audio":
            track_constraints = {
                "echoCancellation": True,
                "noiseSuppression": {"exact": True},
                "autoGainControl": {"exact": True},
                "sampleRate": {"ideal": 24000},
                "sampleSize": {"ideal": 16},
                "channelCount": {"exact": 1},
            }
        if track_constraints is None and modality == "video":
            track_constraints = {
                "facingMode": "user",
                "width": {"ideal": 500},
                "height": {"ideal": 500},
                "frameRate": {"ideal": 30},
            }
        if track_constraints is None and modality == "audio-video":
            track_constraints = {
                "video": {
                    "facingMode": "user",
                    "width": {"ideal": 500},
                    "height": {"ideal": 500},
                    "frameRate": {"ideal": 30},
                },
                "audio": {
                    "echoCancellation": True,
                    "noiseSuppression": {"exact": True},
                    "autoGainControl": {"exact": True},
                    "sampleRate": {"ideal": 24000},
                    "sampleSize": {"ideal": 16},
                    "channelCount": {"exact": 1},
                },
            }
        self.track_constraints = track_constraints
        self.event_handler: Callable | StreamHandler | None = None
        super().__init__(
            label=label,
            every=every,
            inputs=inputs,
            show_label=show_label,
            container=container,
            scale=scale,
            min_width=min_width,
            interactive=interactive,
            visible=visible,
            elem_id=elem_id,
            elem_classes=elem_classes,
            render=render,
            key=key,
            value=value,
        )
        # need to do this here otherwise the proxy_url is not set
        self.icon = (
            icon if not icon else cast(dict, self.serve_static_file(icon)).get("url")
        )

    def preprocess(self, payload: str) -> str:
        """
        Parameters:
            payload: An instance of VideoData containing the video and subtitle files.
        Returns:
            Passes the uploaded video as a `str` filepath or URL whose extension can be modified by `format`.
        """
        return payload

    def postprocess(self, value: Any) -> str:
        """
        Parameters:
            value: Expects a {str} or {pathlib.Path} filepath to a video which is displayed, or a {Tuple[str | pathlib.Path, str | pathlib.Path | None]} where the first element is a filepath to a video and the second element is an optional filepath to a subtitle file.
        Returns:
            VideoData object containing the video and subtitle files.
        """
        return value

    def on_additional_outputs(
        self,
        fn: Callable[Concatenate[P], R],
        inputs: Block | Sequence[Block] | set[Block] | None = None,
        outputs: Block | Sequence[Block] | set[Block] | None = None,
        js: str | None = None,
        concurrency_limit: int | None | Literal["default"] = "default",
        concurrency_id: str | None = None,
        show_progress: Literal["full", "minimal", "hidden"] = "full",
        queue: bool = True,
    ):
        inputs = inputs or []
        if inputs and not isinstance(inputs, Iterable):
            inputs = [inputs]
            inputs = list(inputs)

        async def handler(webrtc_id: str, *args):
            async for next_outputs in self.output_stream(webrtc_id):
                yield fn(*args, *next_outputs.args)  # type: ignore

        return self.state_change(  # type: ignore
            fn=handler,
            inputs=[self] + cast(list, inputs),
            outputs=outputs,
            js=js,
            concurrency_limit=concurrency_limit,
            concurrency_id=concurrency_id,
            show_progress="minimal",
            queue=queue,
            trigger_mode="once",
        )

    def stream(
        self,
        fn: (
            Callable[..., Any]
            | StreamHandlerImpl
            | AudioVideoStreamHandlerImpl
            | VideoEventHandler
            | None
        ) = None,
        inputs: Block | Sequence[Block] | set[Block] | None = None,
        outputs: Block | Sequence[Block] | set[Block] | None = None,
        js: str | None = None,
        concurrency_limit: int | None | Literal["default"] = "default",
        concurrency_id: str | None = None,
        time_limit: float | None = None,
        trigger: Callable | None = None,
    ):
        from gradio.blocks import Block

        if inputs is None:
            inputs = []
        if outputs is None:
            outputs = []
        if isinstance(inputs, Block):
            inputs = [inputs]
        if isinstance(outputs, Block):
            outputs = [outputs]

        self.concurrency_limit = cast(
            int, (1 if concurrency_limit in ["default", None] else concurrency_limit)
        )
        self.event_handler = fn  # type: ignore
        self.time_limit = time_limit

        if (
            self.mode == "send-receive"
            and self.modality in ["audio", "audio-video"]
            and not isinstance(self.event_handler, StreamHandlerBase)
        ):
            raise ValueError(
                "In the send-receive mode for audio, the event handler must be an instance of StreamHandlerBase."
            )

        if self.mode == "send-receive" or self.mode == "send":
            if cast(list[Block], inputs)[0] != self:
                raise ValueError(
                    "In the webrtc stream event, the first input component must be the WebRTC component."
                )

            if (
                len(cast(list[Block], outputs)) != 1
                and cast(list[Block], outputs)[0] != self
            ):
                raise ValueError(
                    "In the webrtc stream event, the only output component must be the WebRTC component."
                )
            for input_component in inputs[1:]:  # type: ignore
                if hasattr(input_component, "change"):
                    input_component.change(  # type: ignore
                        self.set_input,
                        inputs=inputs,
                        outputs=None,
                        concurrency_id=concurrency_id,
                        concurrency_limit=None,
                        time_limit=None,
                        js=js,
                    )
            return self.tick(  # type: ignore
                self.set_input,
                inputs=inputs,
                outputs=None,
                concurrency_id=concurrency_id,
                concurrency_limit=None,
                time_limit=None,
                js=js,
            )
        elif self.mode == "receive":
            if isinstance(inputs, list) and self in cast(list[Block], inputs):
                raise ValueError(
                    "In the receive mode stream event, the WebRTC component cannot be an input."
                )
            if (
                len(cast(list[Block], outputs)) != 1
                and cast(list[Block], outputs)[0] != self
            ):
                raise ValueError(
                    "In the receive mode stream, the only output component must be the WebRTC component."
                )
            if trigger is None:
                raise ValueError(
                    "In the receive mode stream event, the trigger parameter must be provided"
                )
            trigger(lambda: "start_webrtc_stream", inputs=None, outputs=self)
            self.tick(  # type: ignore
                self.set_input,
                inputs=[self] + list(inputs),
                outputs=None,
                concurrency_id=concurrency_id,
            )

    @server
    async def turn(self, _):
        try:
            if inspect.isfunction(self.rtc_configuration):
                if inspect.iscoroutinefunction(self.rtc_configuration):
                    print("coroutine")
                    print("config", await self.rtc_configuration())
                    return await self.rtc_configuration()
                else:
                    print("sync")
                    print("config", anyio.to_thread.run_sync(self.rtc_configuration))
                    return anyio.to_thread.run_sync(self.rtc_configuration)
            else:
                return self.rtc_configuration
        except Exception as e:
            return {"error": str(e)}

    @server
    async def offer(self, body):
        return await self.handle_offer(
            body, self.set_additional_outputs(body["webrtc_id"])
        )

    def example_payload(self) -> Any:
        return {
            "video": handle_file(
                "https://github.com/gradio-app/gradio/raw/main/demo/video_component/files/world.mp4"
            ),
        }

    def example_value(self) -> Any:
        return "https://github.com/gradio-app/gradio/raw/main/demo/video_component/files/world.mp4"

    def api_info(self) -> Any:
        return {"type": "number"}
