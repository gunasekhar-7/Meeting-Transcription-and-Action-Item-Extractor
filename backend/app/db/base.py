"""Declarative base and portable timestamp helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    """Naive UTC: SQLite has no timezone type, so one representation is used everywhere."""
    return datetime.now(UTC).replace(tzinfo=None)
