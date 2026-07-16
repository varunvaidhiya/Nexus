"""Envelope encryption for provider API keys.

Layout of an encrypted blob (all concatenated bytes):

    b"NX1" | wrap_nonce (12) | wrapped_data_key (48) | data_nonce (12) | ciphertext

Each secret gets a fresh random 256-bit data key, encrypted ("wrapped") with
the master key from NEXUS_MASTER_KEY. The master key never touches the
database; rotating it only requires re-wrapping the 48-byte wrapped keys, not
re-encrypting payloads.
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexus_api.config import get_settings

_MAGIC = b"NX1"
_NONCE_LEN = 12
_WRAPPED_KEY_LEN = 48  # 32-byte key + 16-byte GCM tag


class CryptoError(Exception):
    """Encryption/decryption failed. Message is always safe to log."""


def _master_key() -> bytes:
    raw = get_settings().master_key
    if raw is None:
        raise CryptoError(
            "NEXUS_MASTER_KEY is not set. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    try:
        key = bytes.fromhex(raw.get_secret_value())
    except ValueError as exc:
        raise CryptoError("NEXUS_MASTER_KEY must be hex-encoded") from exc
    if len(key) != 32:
        raise CryptoError("NEXUS_MASTER_KEY must be 32 bytes (64 hex chars)")
    return key


def encrypt(plaintext: str) -> bytes:
    master = AESGCM(_master_key())
    data_key = os.urandom(32)

    wrap_nonce = os.urandom(_NONCE_LEN)
    wrapped_key = master.encrypt(wrap_nonce, data_key, _MAGIC)

    data_nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(data_key).encrypt(data_nonce, plaintext.encode(), _MAGIC)

    return _MAGIC + wrap_nonce + wrapped_key + data_nonce + ciphertext


def decrypt(blob: bytes) -> str:
    if not blob.startswith(_MAGIC):
        raise CryptoError("unrecognized ciphertext format")
    offset = len(_MAGIC)
    wrap_nonce = blob[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    wrapped_key = blob[offset : offset + _WRAPPED_KEY_LEN]
    offset += _WRAPPED_KEY_LEN
    data_nonce = blob[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    ciphertext = blob[offset:]

    try:
        data_key = AESGCM(_master_key()).decrypt(wrap_nonce, wrapped_key, _MAGIC)
        plaintext = AESGCM(data_key).decrypt(data_nonce, ciphertext, _MAGIC)
    except InvalidTag as exc:
        raise CryptoError("decryption failed (wrong master key or corrupted data)") from exc
    return plaintext.decode()
