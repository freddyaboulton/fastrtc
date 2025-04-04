import asyncio
from typing import (
    Literal,
    cast,
)

import pytest
from aiortc import (
    AudioStreamTrack,
    RTCPeerConnection,
    RTCSessionDescription,
    VideoStreamTrack,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastrtc.stream import Body
from fastrtc.tracks import HandlerType
from fastrtc.webrtc_connection_mixin import WebRTCConnectionMixin


class MinimalTestStream(WebRTCConnectionMixin):
    def __init__(
        self,
        handler: HandlerType = lambda x: x,
        *,
        mode: Literal["send-receive", "receive", "send"] = "send-receive",
        modality: Literal["video", "audio", "audio-video"] = "video",
        concurrency_limit: int | None | Literal["default"] = "default",
        time_limit: float | None = None,
        allow_extra_tracks: bool = False,
    ):
        WebRTCConnectionMixin.__init__(self)
        self.mode = mode
        self.modality = modality
        self.event_handler = handler
        self.concurrency_limit = cast(
            (int),
            1 if concurrency_limit in ["default", None] else concurrency_limit,
        )
        self.time_limit = time_limit
        self.allow_extra_tracks = allow_extra_tracks

    def mount(self, app: FastAPI, path: str = ""):
        from fastapi import APIRouter

        router = APIRouter(prefix=path)
        router.post("/webrtc/offer")(self.offer)
        app.include_router(router)

    async def offer(self, body: Body):
        return await self.handle_offer(
            body.model_dump(), set_outputs=self.set_additional_outputs(body.webrtc_id)
        )


@pytest.fixture()
def test_client_and_stream(request):
    app = FastAPI()
    params = request.param if hasattr(request, "param") else {}
    stream = MinimalTestStream(**params)
    stream.mount(app)
    test_client = TestClient(app)
    yield test_client, stream


class TestWebRTCConnectionMixin:
    @staticmethod
    async def setup_peer_connection(audio=False, video=False):
        pc = RTCPeerConnection()
        channel = pc.createDataChannel("test-data-channel")
        if audio:
            audio_track = AudioStreamTrack()
            pc.addTrack(audio_track)
        if video:
            video_track = VideoStreamTrack()
            pc.addTrack(video_track)

        await pc.setLocalDescription(await pc.createOffer())
        return pc, channel

    @staticmethod
    async def send_offer(
        pc,
        client,
        audio=False,
        video=False,
        webrtc_id="test_id",
        response_code=200,
        return_status_and_metadata=False,
    ):
        body = {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
        }
        if webrtc_id is not None:
            body["webrtc_id"] = webrtc_id
        response = client.post(
            "/webrtc/offer",
            headers={"Content-Type": "application/json"},
            json=body,
        )
        assert response.status_code == response_code
        if not response_code == 200:
            return
        out = response.json()
        if return_status_and_metadata:
            assert "status" in out and "meta" in out
            return out["status"], out["meta"]
        assert "type" in out and out["type"] == "answer"
        assert "webrtc-datachannel" in out["sdp"]
        if audio:
            assert "m=audio" in out["sdp"]
        if video:
            assert "m=video" in out["sdp"]

        await pc.setRemoteDescription(RTCSessionDescription(out["sdp"], out["type"]))

        # Allow data to stream
        await asyncio.sleep(0.5)

    @staticmethod
    async def close_peer_connection(pc):
        await pc.close()
        assert pc.connectionState == "closed"
        assert pc.iceConnectionState == "closed"
        assert pc.signalingState == "closed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"modality": "audio"}], indirect=True
    )
    @pytest.mark.parametrize("audio", [True, False])
    async def test_successful_connection_audio(self, test_client_and_stream, audio):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection(audio)
        await self.send_offer(pc, test_client, audio)
        # TODO: Test stream? E.g., when no audio is not part of the offer...
        await self.close_peer_connection(pc)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"modality": "video"}], indirect=True
    )
    @pytest.mark.parametrize("video", [True, False])
    async def test_successful_connection_video(self, test_client_and_stream, video):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection(video=video)
        await self.send_offer(pc, test_client, video=video)
        # TODO: Test stream? E.g., when no video is not part of the offer...
        await self.close_peer_connection(pc)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"modality": "audio"}], indirect=True
    )
    @pytest.mark.parametrize("audio", [True, False])
    async def test_unsuccessful_connection_audio(self, test_client_and_stream, audio):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection(audio=audio, video=True)
        with pytest.raises(ValueError, match=r"Unsupported track kind .*"):
            await self.send_offer(pc, test_client, audio=audio, video=True)
        await self.close_peer_connection(pc)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"modality": "video"}], indirect=True
    )
    @pytest.mark.parametrize("video", [True, False])
    async def test_unsuccessful_connection_video(self, test_client_and_stream, video):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection(audio=True, video=video)
        with pytest.raises(ValueError, match=r"Unsupported track kind .*"):
            await self.send_offer(pc, test_client, audio=True, video=video)
        await self.close_peer_connection(pc)

    @pytest.mark.asyncio
    async def test_unsuccessful_webrtc_offer_no_webrtc_id(self, test_client_and_stream):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection()
        await self.send_offer(
            pc,
            test_client,
            webrtc_id=None,
            response_code=422,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"modality": "dummy"}], indirect=True
    )
    @pytest.mark.parametrize(
        "audio, video",
        [
            (True, False),
            (False, True),
            (True, True),
        ],
    )
    async def test_incorrect_modality(self, test_client_and_stream, audio, video):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection(audio=audio, video=video)
        with pytest.raises(ValueError, match=r"Modality must be .*"):
            await self.send_offer(pc, test_client, audio=audio, video=video)
        await self.close_peer_connection(pc)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"concurrency_limit": 1}], indirect=True
    )
    async def test_concurrency_limit_reached_two_peers(self, test_client_and_stream):
        test_client, stream = test_client_and_stream
        pc1, channel = await self.setup_peer_connection(video=True)
        pc2, channel = await self.setup_peer_connection(video=True)
        await self.send_offer(pc1, test_client)
        status, metadata = await self.send_offer(
            pc2, test_client, return_status_and_metadata=True
        )

        assert status == "failed"
        assert metadata == {"error": "concurrency_limit_reached", "limit": 1}

        await self.close_peer_connection(pc1)
        await self.close_peer_connection(pc2)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"concurrency_limit": 2}], indirect=True
    )
    @pytest.mark.xfail(
        reason="It is the same webrtc_id so pc1 and pc2 are seen as ONE connection"
    )
    async def test_concurrency_limit_reached_three_peers_same_id(
        self, test_client_and_stream
    ):
        test_client, stream = test_client_and_stream
        pc1, channel = await self.setup_peer_connection(video=True)
        pc2, channel = await self.setup_peer_connection(video=True)
        pc3, channel = await self.setup_peer_connection(video=True)
        await self.send_offer(pc1, test_client)
        await self.send_offer(pc2, test_client)
        status, metadata = await self.send_offer(
            pc3, test_client, return_status_and_metadata=True
        )

        assert status == "failed"
        assert metadata == {"error": "concurrency_limit_reached", "limit": 1}

        await self.close_peer_connection(pc1)
        await self.close_peer_connection(pc2)
        await self.close_peer_connection(pc3)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"concurrency_limit": 2}], indirect=True
    )
    async def test_concurrency_limit_reached_three_peers(self, test_client_and_stream):
        test_client, stream = test_client_and_stream
        pc1, channel = await self.setup_peer_connection(video=True)
        pc2, channel = await self.setup_peer_connection(video=True)
        pc3, channel = await self.setup_peer_connection(video=True)
        await self.send_offer(pc1, test_client, webrtc_id="foo")
        await self.send_offer(pc2, test_client, webrtc_id="bar")
        status, metadata = await self.send_offer(
            pc3, test_client, webrtc_id="baz", return_status_and_metadata=True
        )

        assert status == "failed"
        assert metadata == {"error": "concurrency_limit_reached", "limit": 2}

        await self.close_peer_connection(pc1)
        await self.close_peer_connection(pc2)
        await self.close_peer_connection(pc3)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream", [{"concurrency_limit": 1}], indirect=True
    )
    @pytest.mark.xfail(
        reason="No audio or video tracks in peer connections added only datachannels"
    )
    async def test_concurrency_limit_reached_peers_with_no_mediastreams(
        self, test_client_and_stream
    ):
        test_client, stream = test_client_and_stream
        pc1, channel = await self.setup_peer_connection()
        pc2, channel = await self.setup_peer_connection()
        await self.send_offer(pc1, test_client, webrtc_id="foo")
        status, metadata = await self.send_offer(
            pc2, test_client, webrtc_id="bar", return_status_and_metadata=True
        )

        assert status == "failed"
        assert metadata == {"error": "concurrency_limit_reached", "limit": 1}

        await self.close_peer_connection(pc1)
        await self.close_peer_connection(pc2)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_client_and_stream",
        [
            {"allow_extra_tracks": True, "modality": "audio"},
            {"allow_extra_tracks": True, "modality": "video"},
        ],
        indirect=True,
    )
    async def test_successful_connection_allow_extra_tracks(
        self, test_client_and_stream
    ):
        test_client, stream = test_client_and_stream
        pc, channel = await self.setup_peer_connection(audio=True, video=True)
        await self.send_offer(pc, test_client, audio=True, video=True)
        await self.close_peer_connection(pc)
