"""Authentication routes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import AppSettings, CurrentUser, Db
from app.core.errors import Unauthenticated
from app.core.security import create_access_token
from app.db.models import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services.auth import (
    authenticate,
    issue_tokens,
    register_user,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        created_at=user.created_at,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Db) -> UserOut:
    user = register_user(
        db, email=payload.email, password=payload.password, display_name=payload.display_name
    )
    db.commit()
    return _user_out(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Db, settings: AppSettings) -> TokenResponse:
    user = authenticate(db, email=payload.email, password=payload.password)
    access, refresh, expires_in = issue_tokens(db, user, settings)
    db.commit()
    return TokenResponse(access_token=access, refresh_token=refresh, expires_in=expires_in)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Db, settings: AppSettings) -> TokenResponse:
    raw_refresh, record = rotate_refresh_token(db, payload.refresh_token, settings)
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("Account is not active")
    access, expires_in = create_access_token(
        user_id=user.id,
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        ttl_minutes=settings.access_token_minutes,
    )
    db.commit()
    return TokenResponse(
        access_token=access, refresh_token=raw_refresh, expires_in=expires_in
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Db) -> Response:
    revoke_refresh_token(db, payload.refresh_token)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
