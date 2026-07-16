import pytest

from nexus_api import crypto
from nexus_api.config import get_settings


def test_round_trip() -> None:
    blob = crypto.encrypt("sk-ant-secret-123")
    assert crypto.decrypt(blob) == "sk-ant-secret-123"


def test_plaintext_not_in_blob() -> None:
    secret = "sk-ant-secret-123"
    assert secret.encode() not in crypto.encrypt(secret)


def test_encrypt_is_randomized() -> None:
    assert crypto.encrypt("same") != crypto.encrypt("same")


def test_tampered_blob_fails() -> None:
    blob = bytearray(crypto.encrypt("secret"))
    blob[-1] ^= 0xFF
    with pytest.raises(crypto.CryptoError, match="decryption failed"):
        crypto.decrypt(bytes(blob))


def test_unknown_format_fails() -> None:
    with pytest.raises(crypto.CryptoError, match="unrecognized"):
        crypto.decrypt(b"garbage-blob")


def test_wrong_master_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = crypto.encrypt("secret")
    monkeypatch.setenv("NEXUS_MASTER_KEY", "ab" * 32)
    get_settings.cache_clear()
    try:
        with pytest.raises(crypto.CryptoError, match="decryption failed"):
            crypto.decrypt(blob)
    finally:
        get_settings.cache_clear()


def test_missing_master_key_has_helpful_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_MASTER_KEY")
    get_settings.cache_clear()
    try:
        with pytest.raises(crypto.CryptoError, match="NEXUS_MASTER_KEY is not set"):
            crypto.encrypt("secret")
    finally:
        get_settings.cache_clear()


def test_malformed_master_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_MASTER_KEY", "not-hex")
    get_settings.cache_clear()
    try:
        with pytest.raises(crypto.CryptoError, match="hex-encoded"):
            crypto.encrypt("secret")
    finally:
        get_settings.cache_clear()
