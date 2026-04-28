"""
Service helpers for Kalshi authentication (REST/WebSocket).

Currently provides:
- build_websocket_auth_headers: construct Kalshi WS auth headers from env + key file.
"""
import os
from typing import Dict
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric import rsa

from app.websockets.socket_auth import (
    load_private_key_from_file,
    get_websocket_auth_headers,
)


def build_websocket_auth_headers() -> Dict[str, str] | None:
    """
    Build Kalshi WebSocket auth headers using env vars and a local private key file.

    Expects:
    - KALSHI_API_KEY
    - KALSHI_PRIVATE_KEY_PATH (optional, defaults to keys/kalshi-socket.pem)

    Returns a dict with the three required WS headers, or None if config is missing.
    """


    api_key = os.getenv("KALSHI_API_KEY")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "keys/kalshi-socket.pem")
    if not api_key or not os.path.isfile(key_path):
        return None

    private_key: rsa.RSAPrivateKey = load_private_key_from_file(key_path)
    return get_websocket_auth_headers(api_key, private_key)

