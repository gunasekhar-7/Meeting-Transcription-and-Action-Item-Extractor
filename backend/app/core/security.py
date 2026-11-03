"""Password hashing and JWT/refresh-token primitives."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


def create_access_token(
    *, user_id: str, role: str, secret: str, algorithm: str, ttl_minutes: int
) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes)
    claims: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "typ": "access",
        "jti": secrets.token_hex(8),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=algorithm), ttl_minutes * 60


def decode_access_token(token: str, *, secret: str, algorithm: str) -> dict[str, Any]:
    return jwt.decode(token, secret, algorithms=[algorithm], options={"require": ["exp", "sub"]})


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
