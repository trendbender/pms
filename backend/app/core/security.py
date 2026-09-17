"""Password hashing (Argon2) and JWT access/refresh token helpers."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import settings

_ph = PasswordHasher()

ACCESS_TOKEN = "access"
REFRESH_TOKEN = "refresh"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _create_token(
    subject: str, token_type: str, expires: timedelta, workspace_id: str | None
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": str(uuid4()),
    }
    if workspace_id:
        payload["ws"] = workspace_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, workspace_id: str | None = None) -> str:
    return _create_token(
        subject,
        ACCESS_TOKEN,
        timedelta(minutes=settings.jwt_access_ttl_minutes),
        workspace_id,
    )


def create_refresh_token(subject: str, workspace_id: str | None = None) -> str:
    return _create_token(
        subject,
        REFRESH_TOKEN,
        timedelta(days=settings.jwt_refresh_ttl_days),
        workspace_id,
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
