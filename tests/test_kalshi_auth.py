import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.kalshi import auth


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def test_headers_carry_a_valid_pss_signature(key):
    h = auth.get_websocket_auth_headers("my-key", key)
    assert h["KALSHI-ACCESS-KEY"] == "my-key"
    signed = h["KALSHI-ACCESS-TIMESTAMP"] + "GET" + "/trade-api/ws/v2"
    key.public_key().verify(  # raises InvalidSignature on mismatch
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]), signed.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256(),
    )


def test_build_headers_none_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("KALSHI_API_KEY", raising=False)
    assert auth.build_websocket_auth_headers() is None
    monkeypatch.setenv("KALSHI_API_KEY", "k")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(tmp_path / "missing.pem"))
    assert auth.build_websocket_auth_headers() is None


def test_build_headers_reads_env_and_key_file(monkeypatch, tmp_path, key):
    from cryptography.hazmat.primitives import serialization
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    (tmp_path / "k.pem").write_bytes(pem)
    monkeypatch.setenv("KALSHI_API_KEY", "env-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", str(tmp_path / "k.pem"))
    assert auth.build_websocket_auth_headers()["KALSHI-ACCESS-KEY"] == "env-key"
