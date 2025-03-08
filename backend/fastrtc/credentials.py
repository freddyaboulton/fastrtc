import os
from typing import Literal

import requests


def get_hf_turn_credentials(token=None):
    if token is None:
        token = os.getenv("HF_TOKEN")
    credentials = requests.get(
        "https://fastrtc-turn-server-login.hf.space/credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not credentials.status_code == 200:
        raise ValueError("Failed to get credentials from HF turn server")
    return {
        "iceServers": [
            {
                "urls": "turn:gradio-turn.com:80",
                **credentials.json(),
            },
        ]
    }


def get_cloudflare_turn_credentials_sync(
    turn_key_id=None, turn_key_api_token=None, hf_token=None, ttl=600
):
    if hf_token is None:
        hf_token = os.getenv("HF_TOKEN")
    if hf_token is not None:
        return requests.get(
            "https://turn.fastrtc.org/credentials",
            headers={"Authorization": f"Bearer {hf_token}"},
        ).json()
    else:
        if turn_key_id is None or turn_key_api_token is None:
            turn_key_id = os.getenv("CLOUDFLARE_TURN_KEY_ID")
            turn_key_api_token = os.getenv("CLOUDFLARE_TURN_KEY_API_TOKEN")
        if turn_key_id is None or turn_key_api_token is None:
            raise ValueError(
                "HF_TOKEN or CLOUDFLARE_TURN_KEY_ID and CLOUDFLARE_TURN_KEY_API_TOKEN must be set to use get_cloudflare_turn_credentials_sync"
            )
        response = requests.post(
            f"https://rtc.live.cloudflare.com/v1/turn/keys/{turn_key_id}/credentials/generate-ice-servers",
            headers={
                "Authorization": f"Bearer {turn_key_api_token}",
                "Content-Type": "application/json",
            },
            json={"ttl": ttl},
        )
        if response.ok:
            return response.json()
        else:
            raise Exception(
                f"Failed to get TURN credentials: {response.status_code} {response.text}"
            )


async def get_cloudflare_turn_credentials(
    turn_key_id=None, turn_key_api_token=None, hf_token=None, ttl=600
):
    import httpx

    if hf_token is None:
        hf_token = os.getenv("HF_TOKEN", "").strip()
    if hf_token is not None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://turn.fastrtc.org/credentials",
                headers={"Authorization": f"Bearer {hf_token}"},
            )
            return {**response.json(), "iceTransportPolicy": "relay"}
    else:
        if turn_key_id is None or turn_key_api_token is None:
            turn_key_id = os.getenv("CLOUDFLARE_TURN_KEY_ID")
            turn_key_api_token = os.getenv("CLOUDFLARE_TURN_KEY_API_TOKEN")
        if turn_key_id is None or turn_key_api_token is None:
            raise ValueError(
                "HF_TOKEN or CLOUDFLARE_TURN_KEY_ID and CLOUDFLARE_TURN_KEY_API_TOKEN must be set to use get_cloudflare_turn_credentials"
            )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://rtc.live.cloudflare.com/v1/turn/keys/{turn_key_id}/credentials/generate-ice-servers",
                headers={
                    "Authorization": f"Bearer {turn_key_api_token}",
                    "Content-Type": "application/json",
                },
                json={"ttl": ttl},
            )
            if response.status_code == 200:
                return {**response.json(), "iceTransportPolicy": "relay"}
            else:
                raise Exception(
                    f"Failed to get TURN credentials: {response.status_code} {response.text}"
                )


def get_twilio_turn_credentials(twilio_sid=None, twilio_token=None):
    try:
        from twilio.rest import Client
    except ImportError:
        raise ImportError("Please install twilio with `pip install twilio`")

    if not twilio_sid and not twilio_token:
        twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        twilio_token = os.environ.get("TWILIO_AUTH_TOKEN")

    client = Client(twilio_sid, twilio_token)

    token = client.tokens.create()

    return {
        "iceServers": token.ice_servers,
        "iceTransportPolicy": "relay",
    }


def get_turn_credentials(method: Literal["hf", "twilio"] = "hf", **kwargs):
    if method == "hf":
        return get_hf_turn_credentials(**kwargs)
    elif method == "twilio":
        return get_twilio_turn_credentials(**kwargs)
    else:
        raise ValueError("Invalid method. Must be 'hf' or 'twilio'")
