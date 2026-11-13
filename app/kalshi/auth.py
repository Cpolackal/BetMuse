import base64
import os
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def get_websocket_auth_headers(api_key: str, private_key: rsa.RSAPrivateKey) -> dict:
    """
    Build Kalshi WebSocket auth headers.
    Message to sign: timestamp + "GET" + "/trade-api/ws/v2"
    """
    timestamp_ms = str(int(time.time() * 1000))
    message = timestamp_ms + "GET" + "/trade-api/ws/v2"
    signature = sign_pss_text(private_key, message)
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
    }


def load_private_key_from_file(file_path: str) -> rsa.RSAPrivateKey:
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,  # or provide a password if your key is encrypted
            backend=default_backend()
        )
    return private_key

def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    message = text.encode('utf-8')
    try:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except InvalidSignature as e:
        raise ValueError("RSA sign PSS failed") from e


def build_websocket_auth_headers() -> dict[str, str] | None:
    """Build Kalshi WebSocket auth headers from the environment.

    Expects KALSHI_API_KEY and, optionally, KALSHI_PRIVATE_KEY_PATH (defaults
    to keys/kalshi-socket.pem). Returns the three required headers, or None if
    the key or key file is missing.
    """
    api_key = os.getenv("KALSHI_API_KEY")
    key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "keys/kalshi-socket.pem")
    if not api_key or not os.path.isfile(key_path):
        return None
    return get_websocket_auth_headers(api_key, load_private_key_from_file(key_path))
