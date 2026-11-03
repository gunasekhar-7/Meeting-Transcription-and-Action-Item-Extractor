"""Structured output contracts for the intelligence layer.

All fields are required (nullable where unknown) so the generated JSON Schema is
compatible with strict structured-output modes. Validation is always repeated
locally; the provider is never trusted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: int = Field(ge=1)
    quote: str = Field(min_length=3, max_length=1000)


class KeyPointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=3, max_length=400)
    evidence: list[EvidenceRef]


class SummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_short: str = Field(min_length=10, max_length=800)
    summary_detailed: str = Field(min_length=10, max_length=4000)
    key_points: list[KeyPointOut] = Field(max_length=12)
    topics: list[str] = Field(max_length=10)


class DecisionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=3, max_length=800)
    rationale: str | None
    made_by_label: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef]


class DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DecisionOut]


class ActionItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=300)
    description: str | None
    owner_label: str | None
    owner_mention: str | None
    due_date: str | None
    due_date_text: str | None
    due_date_precision: Literal["day", "week", "month", "quarter", "unknown"]
    priority: Literal["low", "medium", "high", "critical", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceRef]


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActionItemOut]


SCHEMAS: dict[str, type[BaseModel]] = {
    "summary": SummaryPayload,
    "decisions": DecisionPayload,
    "actions": ActionPayload,
}
