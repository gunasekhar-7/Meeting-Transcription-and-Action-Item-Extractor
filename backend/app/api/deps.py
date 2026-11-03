"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFound, Unauthenticated
from app.core.security import decode_access_token
from app.db.models import Meeting, User

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


Db = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(app_settings)]


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Db,
    settings: AppSettings,
) -> User:
    if credentials is None:
        raise Unauthenticated("Missing access token")
    try:
        claims = decode_access_token(
            credentials.credentials, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )
    except jwt.PyJWTError as exc:
        raise Unauthenticated("Invalid or expired access token") from exc
    if claims.get("typ") != "access":
        raise Unauthenticated("Invalid token type")
    user = db.get(User, claims.get("sub"))
    if user is None or not user.is_active:
        raise Unauthenticated("Account is not active")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def owned_meeting(db: Session, user: User, meeting_id: str) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.owner_id != user.id:
        raise NotFound("Meeting not found")
    return meeting
