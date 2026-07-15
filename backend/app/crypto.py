"""Encrypt / decrypt subscriber secrets at rest (Fernet = AES-128-CBC + HMAC)."""
from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from . import config


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a url-safe 32-byte Fernet key from an app secret."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    # Prefer dedicated ENCRYPTION_KEY; fall back to JWT_SECRET.
    raw = (
        os.getenv("ENCRYPTION_KEY", "").strip()
        or getattr(config, "ENCRYPTION_KEY", "")
        or config.JWT_SECRET
    )
    if not raw or len(raw) < 16:
        raise RuntimeError(
            "ENCRYPTION_KEY or JWT_SECRET must be set (≥16 chars) to store subscriber API keys"
        )
    # Accept a pre-generated Fernet key (url-safe base64, 44 chars ending with =)
    if len(raw) == 44:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            pass
    return Fernet(_derive_fernet_key(raw))


def encrypt_secret(plaintext: str) -> str:
    if plaintext is None:
        return ""
    text = str(plaintext).strip()
    if not text:
        return ""
    return _fernet().encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "Unable to decrypt secret — ENCRYPTION_KEY may have changed"
        ) from e


def mask_secret(plaintext: str, keep: int = 4) -> str:
    if not plaintext:
        return ""
    p = plaintext.strip()
    if len(p) <= keep:
        return "•" * len(p)
    return "•" * max(8, len(p) - keep) + p[-keep:]
