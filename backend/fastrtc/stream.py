import inspect
import logging
from pathlib import Path
from typing import (
    Any,
    AsyncContextManager,
    Callable,
    Literal,
    TypedDict,
    cast,
)

import anyio
import gradio as gr
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from gradio import Blocks
from gradio.components.base import Component
from pydantic import BaseModel
from typing_extensions import NotRequired

from .tracks import HandlerType, StreamHandlerImpl
from .webrtc import WebRTC
from .webrtc_connection_mixin import WebRTCConnectionMixin
from .websocket import WebSocketHandler

logger = logging.getLogger(__name__)

curr_dir = Path(__file__).parent


class Body(BaseModel):
    sdp: str
    type: str
    webrtc_id: str


class UIArgs(TypedDict):
    title: NotRequired[str]
    """Title of the demo"""
    subtitle: NotRequired[str]
    """Subtitle of the demo. Text will be centered and displayed below the title."""
    icon: NotRequired[str]
    """Icon to display on the button instead of the wave animation. The icon should be a path/url to a .svg/.png/.jpeg file."""
    icon_button_color: NotRequired[str]
    """Color of the icon button. Default is var(--color-accent) of the demo theme."""
    pulse_color: NotRequired[str]
    """Color of the pulse animation. Default is var(--color-accent) of the demo theme."""
    icon_radius: NotRequired[int]
    """Border radius of the icon button expressed as a percentage of the button size. Default is 50%."""


class Stream(WebRTCConnectionMixin):
    def __init__(
        self,
        handler: HandlerType,
        *,
        additional_outputs_handler: Callable | None = None,
        mode: Literal["send-receive", "receive", "send"] = "send-receive",
        modality: Literal["video", "audio", "audio-video"] = "video",
        concurrency_limit: int | None | Literal["default"] = "default",
        time_limit: float | None = None,
        rtp_params: dict[str, Any] | None = None,
        rtc_configuration: dict[str, Any] | None | Callable[[], dict[str, Any]] = None,
        additional_inputs: list[Component] | None = None,
        additional_outputs: list[Component] | None = None,
        ui_args: UIArgs | None = None,
    ):
        WebRTCConnectionMixin.__init__(self)
        self.mode = mode
        self.modality = modality
        self.rtp_params = rtp_params
        self.event_handler = handler
        self.concurrency_limit = cast(
            (int | float),
            1 if concurrency_limit in ["default", None] else concurrency_limit,
        )
        self.time_limit = time_limit
        self.additional_output_components = additional_outputs
        self.additional_input_components = additional_inputs
        self.additional_outputs_handler = additional_outputs_handler
        self.rtc_configuration = rtc_configuration
        self._ui = self._generate_default_ui(ui_args)
        self._ui.launch = self._wrap_gradio_launch(self._ui.launch)

    def mount(self, app: FastAPI):
        app.router.post("/webrtc/offer")(self.offer)
        app.router.websocket("/telephone/handler")(self.telephone_handler)
        app.router.post("/telephone/incoming")(self.handle_incoming_call)
        app.router.websocket("/websocket/offer")(self.websocket_offer)
        app.router.get("/webrtc/turn")(self.get_rtc_configuration)
        lifespan = self._inject_startup_message(app.router.lifespan_context)
        app.router.lifespan_context = lifespan

    @staticmethod
    def print_error(env: Literal["colab", "spaces"]):
        import click

        print(
            click.style("ERROR", fg="red")
            + f":\t  Running in {env} is not possible without providing a valid rtc_configuration. "
            + "See "
            + click.style("https://fastrtc.org/deployment/", fg="cyan")
            + " for more information."
        )
        raise RuntimeError(
            f"Running in {env} is not possible without providing a valid rtc_configuration. "
            + "See https://fastrtc.org/deployment/ for more information."
        )

    def _check_colab_or_spaces(self):
        from gradio.utils import colab_check, get_space

        if colab_check() and not self.rtc_configuration:
            self.print_error("colab")
        if get_space() and not self.rtc_configuration:
            self.print_error("spaces")

    def _wrap_gradio_launch(self, callable):
        import contextlib

        def wrapper(*args, **kwargs):
            lifespan = kwargs.get("app_kwargs", {}).get("lifespan", None)

            @contextlib.asynccontextmanager
            async def new_lifespan(app: FastAPI):
                if lifespan is None:
                    self._check_colab_or_spaces()
                    yield
                else:
                    async with lifespan(app):
                        self._check_colab_or_spaces()
                        yield

            if "app_kwargs" not in kwargs:
                kwargs["app_kwargs"] = {}
            kwargs["app_kwargs"]["lifespan"] = new_lifespan
            return callable(*args, **kwargs)

        return wrapper

    def _inject_startup_message(
        self, lifespan: Callable[[FastAPI], AsyncContextManager] | None = None
    ):
        import contextlib

        import click

        def print_startup_message():
            self._check_colab_or_spaces()
            print(
                click.style("INFO", fg="green")
                + ":\t  Visit "
                + click.style("https://fastrtc.org/userguide/api/", fg="cyan")
                + " for WebRTC or Websocket API docs."
            )

        @contextlib.asynccontextmanager
        async def new_lifespan(app: FastAPI):
            if lifespan is None:
                print_startup_message()
                yield
            else:
                async with lifespan(app):
                    print_startup_message()
                    yield

        return new_lifespan

    def _generate_default_ui(
        self,
        ui_args: UIArgs | None = None,
    ):
        ui_args = ui_args or {}
        same_components = []
        additional_input_components = self.additional_input_components or []
        additional_output_components = self.additional_output_components or []
        if additional_output_components and not self.additional_outputs_handler:
            raise ValueError(
                "additional_outputs_handler must be provided if there are additional output components."
            )
        if additional_input_components and additional_output_components:
            same_components = [
                component
                for component in additional_input_components
                if component in additional_output_components
            ]
            for component in additional_output_components:
                if component in same_components:
                    same_components.append(component)
        if self.modality == "video" and self.mode == "receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Video Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Row():
                    with gr.Column():
                        if additional_input_components:
                            for component in additional_input_components:
                                component.render()
                        button = gr.Button("Start Stream", variant="primary")
                    with gr.Column():
                        output_video = WebRTC(
                            label="Video Stream",
                            rtc_configuration=self.rtc_configuration,
                            mode="receive",
                            modality="video",
                        )
                        for component in additional_output_components:
                            if component not in same_components:
                                component.render()
                output_video.stream(
                    fn=self.event_handler,
                    inputs=self.additional_input_components,
                    outputs=[output_video],
                    trigger=button.click,
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    output_video.on_additional_outputs(
                        self.additional_outputs_handler,
                        inputs=additional_output_components,
                        outputs=additional_output_components,
                    )
        elif self.modality == "video" and self.mode == "send":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Video Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Row():
                    if additional_input_components:
                        with gr.Column():
                            for component in additional_input_components:
                                component.render()
                    with gr.Column():
                        output_video = WebRTC(
                            label="Video Stream",
                            rtc_configuration=self.rtc_configuration,
                            mode="send",
                            modality="video",
                        )
                        for component in additional_output_components:
                            if component not in same_components:
                                component.render()
                output_video.stream(
                    fn=self.event_handler,
                    inputs=[output_video] + additional_input_components,
                    outputs=[output_video],
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    output_video.on_additional_outputs(
                        self.additional_outputs_handler,
                        inputs=additional_output_components,
                        outputs=additional_output_components,
                    )
        elif self.modality == "video" and self.mode == "send-receive":
            css = """.my-group {max-width: 600px !important; max-height: 600 !important;}
                      .my-column {display: flex !important; justify-content: center !important; align-items: center !important};"""

            with gr.Blocks(css=css) as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Video Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Column(elem_classes=["my-column"]):
                    with gr.Group(elem_classes=["my-group"]):
                        image = WebRTC(
                            label="Stream",
                            rtc_configuration=self.rtc_configuration,
                            mode="send-receive",
                            modality="video",
                        )
                        for component in additional_input_components:
                            component.render()
                if additional_output_components:
                    with gr.Column():
                        for component in additional_output_components:
                            if component not in same_components:
                                component.render()

                image.stream(
                    fn=self.event_handler,
                    inputs=[image] + additional_input_components,
                    outputs=[image],
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    image.on_additional_outputs(
                        self.additional_outputs_handler,
                        inputs=additional_output_components,
                        outputs=additional_output_components,
                    )
        elif self.modality == "audio" and self.mode == "receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Audio Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Row():
                    with gr.Column():
                        for component in additional_input_components:
                            component.render()
                        button = gr.Button("Start Stream", variant="primary")
                    if additional_output_components:
                        with gr.Column():
                            output_video = WebRTC(
                                label="Audio Stream",
                                rtc_configuration=self.rtc_configuration,
                                mode="receive",
                                modality="audio",
                                icon=ui_args.get("icon"),
                                icon_button_color=ui_args.get("icon_button_color"),
                                pulse_color=ui_args.get("pulse_color"),
                                icon_radius=ui_args.get("icon_radius"),
                            )
                            for component in additional_output_components:
                                if component not in same_components:
                                    component.render()
                output_video.stream(
                    fn=self.event_handler,
                    inputs=self.additional_input_components,
                    outputs=[output_video],
                    trigger=button.click,
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    output_video.on_additional_outputs(
                        self.additional_outputs_handler,
                        inputs=additional_output_components,
                        outputs=additional_output_components,
                    )
        elif self.modality == "audio" and self.mode == "send":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Audio Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Row():
                    with gr.Column():
                        with gr.Group():
                            image = WebRTC(
                                label="Stream",
                                rtc_configuration=self.rtc_configuration,
                                mode="send",
                                modality="audio",
                                icon=ui_args.get("icon"),
                                icon_button_color=ui_args.get("icon_button_color"),
                                pulse_color=ui_args.get("pulse_color"),
                                icon_radius=ui_args.get("icon_radius"),
                            )
                            for component in additional_input_components:
                                if component not in same_components:
                                    component.render()
                    if additional_output_components:
                        with gr.Column():
                            for component in additional_output_components:
                                component.render()
                image.stream(
                    fn=self.event_handler,
                    inputs=[image] + additional_input_components,
                    outputs=[image],
                    time_limit=self.time_limit,
                    concurrency_limit=self.concurrency_limit,  # type: ignore
                )
                if additional_output_components:
                    assert self.additional_outputs_handler
                    image.on_additional_outputs(
                        self.additional_outputs_handler,
                        inputs=additional_output_components,
                        outputs=additional_output_components,
                    )
        elif self.modality == "audio" and self.mode == "send-receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Audio Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                    {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Row():
                    with gr.Column():
                        with gr.Group():
                            image = WebRTC(
                                label="Stream",
                                rtc_configuration=self.rtc_configuration,
                                mode="send-receive",
                                modality="audio",
                                icon=ui_args.get("icon"),
                                icon_button_color=ui_args.get("icon_button_color"),
                                pulse_color=ui_args.get("pulse_color"),
                                icon_radius=ui_args.get("icon_radius"),
                            )
                            for component in additional_input_components:
                                if component not in same_components:
                                    component.render()
                    if additional_output_components:
                        with gr.Column():
                            for component in additional_output_components:
                                component.render()

                    image.stream(
                        fn=self.event_handler,
                        inputs=[image] + additional_input_components,
                        outputs=[image],
                        time_limit=self.time_limit,
                        concurrency_limit=self.concurrency_limit,  # type: ignore
                    )
                    if additional_output_components:
                        assert self.additional_outputs_handler
                        image.on_additional_outputs(
                            self.additional_outputs_handler,
                            inputs=additional_output_components,
                            outputs=additional_output_components,
                        )
        elif self.modality == "audio-video" and self.mode == "send-receive":
            with gr.Blocks() as demo:
                gr.HTML(
                    f"""
                <h1 style='text-align: center'>
                {ui_args.get("title", "Audio Video Streaming (Powered by FastRTC ⚡️)")}
                </h1>
                """
                )
                if ui_args.get("subtitle"):
                    gr.Markdown(
                        f"""
                <div style='text-align: center'>
                {ui_args.get("subtitle")}
                </div>
                """
                    )
                with gr.Row():
                    with gr.Column():
                        with gr.Group():
                            image = WebRTC(
                                label="Stream",
                                rtc_configuration=self.rtc_configuration,
                                mode="send-receive",
                                modality="audio-video",
                                icon=ui_args.get("icon"),
                                icon_button_color=ui_args.get("icon_button_color"),
                                pulse_color=ui_args.get("pulse_color"),
                                icon_radius=ui_args.get("icon_radius"),
                            )
                            for component in additional_input_components:
                                if component not in same_components:
                                    component.render()
                    if additional_output_components:
                        with gr.Column():
                            for component in additional_output_components:
                                component.render()

                    image.stream(
                        fn=self.event_handler,
                        inputs=[image] + additional_input_components,
                        outputs=[image],
                        time_limit=self.time_limit,
                        concurrency_limit=self.concurrency_limit,  # type: ignore
                    )
                    if additional_output_components:
                        assert self.additional_outputs_handler
                        image.on_additional_outputs(
                            self.additional_outputs_handler,
                            inputs=additional_output_components,
                            outputs=additional_output_components,
                        )
        else:
            raise ValueError(f"Invalid modality: {self.modality} and mode: {self.mode}")
        return demo

    @property
    def ui(self) -> Blocks:
        return self._ui

    @ui.setter
    def ui(self, blocks: Blocks):
        self._ui = blocks

    async def offer(self, body: Body):
        return await self.handle_offer(
            body.model_dump(), set_outputs=self.set_additional_outputs(body.webrtc_id)
        )

    async def get_rtc_configuration(self):
        if inspect.isfunction(self.rtc_configuration):
            if inspect.iscoroutinefunction(self.rtc_configuration):
                return await self.rtc_configuration()
            else:
                return anyio.to_thread.run_sync(self.rtc_configuration)  # type: ignore
        else:
            return self.rtc_configuration

    async def handle_incoming_call(self, request: Request):
        from twilio.twiml.voice_response import Connect, VoiceResponse

        response = VoiceResponse()
        response.say("Connecting to the AI assistant.")
        connect = Connect()
        connect.stream(url=f"wss://{request.url.hostname}/telephone/handler")
        response.append(connect)
        response.say("The call has been disconnected.")
        return HTMLResponse(content=str(response), media_type="application/xml")

    async def telephone_handler(self, websocket: WebSocket):
        handler = cast(StreamHandlerImpl, self.event_handler.copy())  # type: ignore
        handler.phone_mode = True

        async def set_handler(s: str, a: WebSocketHandler):
            if len(self.connections) >= self.concurrency_limit:  # type: ignore
                await cast(WebSocket, a.websocket).send_json(
                    {
                        "status": "failed",
                        "meta": {
                            "error": "concurrency_limit_reached",
                            "limit": self.concurrency_limit,
                        },
                    }
                )
                await websocket.close()
                return

        ws = WebSocketHandler(
            handler, set_handler, lambda s: None, lambda s: lambda a: None
        )
        await ws.handle_websocket(websocket)

    async def websocket_offer(self, websocket: WebSocket):
        handler = cast(StreamHandlerImpl, self.event_handler.copy())  # type: ignore
        handler.phone_mode = False

        async def set_handler(s: str, a: WebSocketHandler):
            if len(self.connections) >= self.concurrency_limit:  # type: ignore
                await cast(WebSocket, a.websocket).send_json(
                    {
                        "status": "failed",
                        "meta": {
                            "error": "concurrency_limit_reached",
                            "limit": self.concurrency_limit,
                        },
                    }
                )
                await websocket.close()
                return

            self.connections[s] = [a]  # type: ignore

        def clean_up(s):
            self.clean_up(s)

        ws = WebSocketHandler(
            handler, set_handler, clean_up, lambda s: self.set_additional_outputs(s)
        )
        await ws.handle_websocket(websocket)

    def fastphone(
        self,
        token: str | None = None,
        host: str = "127.0.0.1",
        port: int = 8000,
        **kwargs,
    ):
        import atexit
        import secrets
        import threading
        import time
        import urllib.parse

        import click
        import httpx
        import uvicorn
        from gradio.networking import setup_tunnel
        from gradio.tunneling import CURRENT_TUNNELS
        from huggingface_hub import get_token

        app = FastAPI()

        self.mount(app)

        t = threading.Thread(
            target=uvicorn.run,
            args=(app,),
            kwargs={"host": host, "port": port, **kwargs},
        )
        t.start()

        url = setup_tunnel(
            host, port, share_token=secrets.token_urlsafe(32), share_server_address=None
        )
        host = urllib.parse.urlparse(url).netloc

        URL = "https://api.fastrtc.org"
        try:
            r = httpx.post(
                URL + "/register",
                json={"url": host},
                headers={"Authorization": token or get_token() or ""},
            )
        except Exception:
            URL = "https://fastrtc-fastphone.hf.space"
            r = httpx.post(
                URL + "/register",
                json={"url": host},
                headers={"Authorization": token or get_token() or ""},
            )
        r.raise_for_status()
        data = r.json()
        code = f"{data['code']}"
        phone_number = data["phone"]
        reset_date = data["reset_date"]
        print(
            click.style("INFO", fg="green")
            + ":\t  Your FastPhone is now live! Call "
            + click.style(phone_number, fg="cyan")
            + " and use code "
            + click.style(code, fg="cyan")
            + " to connect to your stream."
        )
        minutes = str(int(data["time_remaining"] // 60)).zfill(2)
        seconds = str(int(data["time_remaining"] % 60)).zfill(2)
        print(
            click.style("INFO", fg="green")
            + ":\t  You have "
            + click.style(f"{minutes}:{seconds}", fg="cyan")
            + " minutes remaining in your quota (Resetting on "
            + click.style(f"{reset_date}", fg="cyan")
            + ")"
        )
        print(
            click.style("INFO", fg="green")
            + ":\t  Visit "
            + click.style(
                "https://fastrtc.org/userguide/audio/#telephone-integration",
                fg="cyan",
            )
            + " for information on making your handler compatible with phone usage."
        )

        def unregister():
            httpx.post(
                URL + "/unregister",
                json={"url": host, "code": code},
                headers={"Authorization": token or get_token() or ""},
            )

        atexit.register(unregister)

        try:
            while True:
                time.sleep(0.1)
        except (KeyboardInterrupt, OSError):
            print(
                click.style("INFO", fg="green")
                + ":\t  Keyboard interruption in main thread... closing server."
            )
            unregister()
            t.join(timeout=5)
            for tunnel in CURRENT_TUNNELS:
                tunnel.kill()
