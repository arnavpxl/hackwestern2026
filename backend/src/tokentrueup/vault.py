"""Encryption for stored provider keys (AES-256-GCM).

The master key comes from TTU_ENCRYPTION_KEY (32 random bytes, base64url). Each stored key is
bound to its connection label as associated data, so a ciphertext copied onto another row fails
to decrypt. Nothing in this module logs or returns a key except decrypt(), which only the sync
worker will call.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

PREFIX = "v1:"
MIN_KEY_LENGTH = 20


def generate_master_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def _master() -> bytes:
    if not settings.ttu_encryption_key:
        raise RuntimeError("TTU_ENCRYPTION_KEY is not set, so provider keys cannot be stored")
    try:
        raw = base64.urlsafe_b64decode(settings.ttu_encryption_key)
    except ValueError:
        raise RuntimeError("TTU_ENCRYPTION_KEY is not valid base64") from None
    if len(raw) != 32:
        raise RuntimeError("TTU_ENCRYPTION_KEY must decode to 32 bytes")
    return raw


def encrypt(plaintext: str, context: str) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_master()).encrypt(nonce, plaintext.encode(), context.encode())
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt(token: str, context: str) -> str:
    if not token.startswith(PREFIX):
        raise ValueError("stored key has an unknown format")
    blob = base64.urlsafe_b64decode(token[len(PREFIX):])
    try:
        return AESGCM(_master()).decrypt(blob[:12], blob[12:], context.encode()).decode()
    except InvalidTag:
        raise ValueError("stored key failed authentication (wrong master key, or the row was altered)") from None


def last4(key: str) -> str:
    return key[-4:]


def check_format(provider: str, key: str) -> str | None:
    """A shape check only, so obvious mistakes are caught on paste. The real check is one read-only
    call to the provider, added with each provider adapter in phase 2. Returns an error or None."""
    k = key.strip()
    if len(k) < MIN_KEY_LENGTH or any(ch.isspace() for ch in k):
        return "That doesn't look like an API key."
    if provider == "anthropic" and not k.startswith("sk-ant-admin"):
        return "Anthropic usage and cost data needs an Admin API key (it starts with sk-ant-admin)."
    return None
