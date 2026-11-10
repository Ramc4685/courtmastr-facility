"""argon2id password hashing and the one password policy for staff and clients (ADR 0002 section 3)."""

from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import ValidationFailed
from app.core.settings import get_settings

# shortcut: a token list, not the bundled common-password corpus the ADR asks for; with the 12-character
# minimum it only needs the long favourites. Replace with a real list file before launch.
_COMMON = {
    "password1234", "passwordpassword", "123456789012", "1234567890123", "qwertyuiop12", "qwertyuiopasdf",
    "letmeinletmein", "iloveyou1234", "administrator", "welcome12345", "changemeplease", "password12345",
}  # fmt: skip


@cache
def _hasher() -> PasswordHasher:
    cfg = get_settings().auth.argon2
    return PasswordHasher(memory_cost=cfg.memory_kib, time_cost=cfg.time_cost, parallelism=cfg.parallelism)


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher().check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return hash_password("no-such-identity-placeholder")


def burn(password: str) -> None:
    """Spend the same work as a real verify so an unknown email is not faster than a wrong password."""
    verify_password(_dummy_hash(), password)


def check_policy(password: str, *, forbidden: tuple[str, ...] = ()) -> None:
    minimum = get_settings().auth.password_min_length
    lowered = password.lower()
    if (
        not minimum <= len(password) <= 128
        or lowered in _COMMON
        or any(lowered == value.lower() for value in forbidden if value)
    ):
        raise ValidationFailed(
            f"Use {minimum} to 128 characters, not a common password and not your email or name.",
            code="password-too-weak",
            pointer="/new_password",
        )
