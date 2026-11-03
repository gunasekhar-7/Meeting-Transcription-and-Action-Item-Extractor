"""Authentication use cases."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import Conflict, Unauthenticated
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.db.base import new_uuid, utcnow
from app.db.models import RefreshToken, User


def register_user(session: Session, *, email: str, password: str, display_name: str) -> User:
    if session.scalar(select(User).where(User.email == email.lower())) is not None:
        raise Conflict("An account with this email already exists")
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
        created_at=utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, *, email: str, password: str) -> User:
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise Unauthenticated("Incorrect email or password")
    user.last_login_at = utcnow()
    return user


def issue_tokens(session: Session, user: User, settings: Settings) -> tuple[str, str, int]:
    access, expires_in = create_access_token(
        user_id=user.id,
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        ttl_minutes=settings.access_token_minutes,
    )
    raw_refresh = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            family_id=new_uuid(),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
            created_at=utcnow(),
        )
    )
    return access, raw_refresh, expires_in


def rotate_refresh_token(
    session: Session, raw_token: str, settings: Settings
) -> tuple[str, RefreshToken]:
    """Rotate a refresh token and return the new raw token plus its record.

    Presenting a revoked token is treated as theft: the whole rotation family is
    revoked, which logs the attacker and the victim out of that session.
    """
    token_hash = hash_refresh_token(raw_token)
    record = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if record is None:
        raise Unauthenticated("Invalid refresh token")

    if record.revoked_at is not None:
        session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == record.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        session.flush()
        # Security state must survive the raised error: the request session is
        # rolled back on close, so commit the family revocation explicitly.
        session.commit()
        raise Unauthenticated("Refresh token reuse detected; the session has been revoked")

    if record.expires_at <= utcnow():
        record.revoked_at = utcnow()
        session.flush()
        raise Unauthenticated("Refresh token expired")

    raw_new = new_refresh_token()
    replacement = RefreshToken(
        user_id=record.user_id,
        token_hash=hash_refresh_token(raw_new),
        family_id=record.family_id,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
        created_at=utcnow(),
    )
    session.add(replacement)
    session.flush()
    record.revoked_at = utcnow()
    record.replaced_by_id = replacement.id
    return raw_new, replacement


def revoke_refresh_token(session: Session, raw_token: str) -> None:
    record = session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
