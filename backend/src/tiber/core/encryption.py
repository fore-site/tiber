"""Symmetric encryption for secrets Tiber must replay, not merely verify.

Passwords and API keys are one-way hashed. A webhook signing secret cannot be:
the dispatcher has to reproduce the HMAC the client will verify, so it has to
recover the key. It is encrypted at rest with a Fernet key derived from
``SECRET_KEY``.

Limitation worth knowing: deriving the key from a single application secret
means rotating ``SECRET_KEY`` makes existing webhook secrets undecryptable.
Rotation therefore needs a re-encryption step, which does not exist yet.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


def _fernet() -> Fernet:
    """Build the Fernet instance from the configured application secret.

    Raises ``RuntimeError`` when ``SECRET_KEY`` is unset: encrypting under an
    empty key would look like encryption while providing none.
    """
    secret_key = get_settings().secret_key
    if not secret_key:
        raise RuntimeError("SECRET_KEY must be set to store webhook signing secrets.")
    digest = hashlib.sha256(secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage; returns a URL-safe token."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a stored secret, raising ``RuntimeError`` on a bad token/key."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored webhook secret cannot be decrypted with the current SECRET_KEY."
        ) from exc
