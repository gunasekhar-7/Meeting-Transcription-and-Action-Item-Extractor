"""Shared response envelopes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int


class Problem(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str | None = None
    request_id: str | None = None
    errors: list[dict[str, str]] = []


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
