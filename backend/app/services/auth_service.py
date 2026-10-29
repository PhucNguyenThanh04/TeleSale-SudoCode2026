"""Password hashing helpers for future operator accounts."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


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
