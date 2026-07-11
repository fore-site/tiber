import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext

from tiber.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(
    schemes=["argon2"], 
    deprecated="auto",
    argon2__memory_cost=65536,  # 64 MB,
    argon2__rounds=3,  # Number of iterations
    argon2__parallelism=4,  # Number of parallel threads
)


def hash_password(password: str) -> str:
    """
    Hashes a password using the configured password hashing algorithm.

    Args:
        password (str): The plain text password to hash.

    Returns:
        str: The hashed password.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a password against a hashed password.

    Args:
        plain_password (str): The plain text password to verify.
        hashed_password (str): The hashed password to compare against.

    Returns:
        bool: True if the password matches the hash, False otherwise.
    """
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> tuple[str, str]:
    """
    Creates a JWT access token with the given subject and optional extra claims.

    Args:
        subject (str): The subject (usually user ID) for the token.
        extra (dict[str, Any] | None): Optional additional claims to include in the token.

    Returns:
        (access_token, jti): A tuple containing the access token and its unique identifier (jti).

    jti is written to redis blocklist on revocation.
    Signature verification always happens before any Redis blocklist check.
    """
    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload = {
        "sub": subject,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "access",
        **(extra or {})
    }

    access_token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return access_token, jti


def create_refresh_token(subject: str) -> tuple[str, str]:
    """
    Creates a JWT refresh token with the given subject.

    Args:
        subject (str): The subject (usually user ID) for the token.

    Returns:
        (refresh_token, jti): A tuple containing the refresh token and its unique identifier (jti).

    jti is written to redis blocklist on revocation.
    Signature verification always happens before any Redis blocklist check.
    """
    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.refresh_token_expire_days)

    payload = {
        "sub": subject,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "refresh"
    }

    refresh_token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return refresh_token, jti


def decode_token(token: str) -> dict[str, Any]:
    """
    Decodes a JWT token and returns its payload.

    Args:
        token (str): The JWT token to decode.

    Returns:
        dict[str, Any]: The decoded token payload.

    Raises:
        jose.exceptions.JWTError: If the token is invalid or expired.

    This must be called before any Redis blocklist check to ensure the token's signature is valid.
    """
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


def generate_api_key() -> str:
    """
    Generates a secure random API key.

    Returns:
        str: A securely generated random API key.
    """
    api_key = secrets.token_urlsafe(32)  # Generates a 32-byte URL-safe token
    return f"tb_{api_key}"  # Prefix with 'tb_' to indicate it's a Tiber API key


def hash_api_key(api_key: str) -> str:
    """
    Hashes an API key using SHA-256. The raw key is never persisted.

    Args:
        api_key (str): The API key to hash.

    Returns:
        str: The hashed API key.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()