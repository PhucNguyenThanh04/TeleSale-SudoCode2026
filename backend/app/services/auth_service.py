"""Password hashing and access-token helpers for backend authentication."""

from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.configs import get_settings


_password_hash = PasswordHash.recommended()


def hash_password(plain: str) -> str:
    """Hash a new password with pwdlib's recommended Argon2 settings."""
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return False for an incorrect password or an unrecognized hash."""
    try:
        return _password_hash.verify(plain, hashed)
    except UnknownHashError:
        return False


def create_access_token(user_id: str) -> str:
    """Issue a signed access token for a backend user ID."""
    if not user_id:
        raise ValueError("user_id must not be empty")

    settings = get_settings()
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> str:
    """Return the user ID or raise jwt.exceptions.InvalidTokenError."""
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "iat", "exp"]},
    )
    user_id = payload["sub"]
    if not isinstance(user_id, str) or not user_id:
        raise InvalidTokenError("Invalid subject in token")
    return user_id
