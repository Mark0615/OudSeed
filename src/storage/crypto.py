"""Symmetric encryption for secrets stored at rest (e.g. OAuth tokens).

Uses Fernet (AES-128-CBC + HMAC). The key is a urlsafe-base64 string supplied via
``TOKEN_ENCRYPTION_KEY`` (sourced from Secret Manager in production) and must
never be committed. Generate one with :func:`generate_key`.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

ENCRYPTION_KEY_ENV = "TOKEN_ENCRYPTION_KEY"


def generate_key() -> str:
    """Return a new urlsafe-base64 Fernet key as a string."""
    return Fernet.generate_key().decode()


def get_encryption_key() -> str:
    """Return the configured encryption key, or raise if it is missing."""
    key = os.getenv(ENCRYPTION_KEY_ENV)
    if not key:
        raise RuntimeError(
            f"{ENCRYPTION_KEY_ENV} is not set; cannot encrypt or decrypt secrets."
        )
    return key


def _fernet(key: str | None) -> Fernet:
    return Fernet((key or get_encryption_key()).encode())


def encrypt_secret(plaintext: str, *, key: str | None = None) -> str:
    """Encrypt a plaintext secret and return a urlsafe token string."""
    return _fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, *, key: str | None = None) -> str:
    """Decrypt a token string produced by :func:`encrypt_secret`."""
    return _fernet(key).decrypt(token.encode()).decode()
