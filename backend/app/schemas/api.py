"""API contracts for meetings, transcripts, intelligence, and tasks."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    meeting_date: datetime | None = None


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    meeting_date: datetime | None = None


class AudioOut(BaseModel):
    original_filename: str
    size_bytes: int
    codec: str | None
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    sha256: str
    purged: bool


class MeetingOut(BaseModel):
    id: str
    title: str
    description: str | None
    meeting_date: datetime | None
    status: str
    intelligence_status: str
    language: str | None
    duration_seconds: float | None
    created_at: datetime
    updated_at: datetime
    audio: AudioOut | None = None
    action_item_count: int = 0
    open_action_item_count: int = 0
    speaker_count: int = 0


class UploadResponse(BaseModel):
    meeting_id: str
    audio_asset_id: str
    job_id: str
    status: str
    status_url: str


class StageStatus(BaseModel):
    name: str
    status: str
    progress: int
    duration_ms: int | None


class JobErrorOut(BaseModel):
    code: str
    message: str
    retryable: bool


class StatusResponse(BaseModel):
    meeting_id: str
    status: str
    intelligence_status: str
    stages: list[StageStatus]
    error: JobErrorOut | None
    updated_at: datetime


class SpeakerOut(BaseModel):
    id: str
    label: str
    display_name: str | None
    total_speaking_seconds: float
    segment_count: int


class SegmentOut(BaseModel):
    id: int
    sequence: int
    start_ms: int
    end_ms: int
    speaker_id: str | None
    speaker_label: str | None
    text: str
    is_low_confidence: bool


class TranscriptOut(BaseModel):
    transcript_id: str
    version: int
    meeting_id: str
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    real_time_factor: float | None
    asr: dict[str, object]
    capability_notes: dict[str, object]
    speakers: list[SpeakerOut]
    segments: list[SegmentOut]
    offset: int
    limit: int
    total: int


class TranscriptSearchHit(BaseModel):
    segment_id: int
    start_ms: int
    end_ms: int
    speaker_label: str | None
    snippet: str


class TranscriptSearchResponse(BaseModel):
    query: str
    total: int
    hits: list[TranscriptSearchHit]


class SpeakerUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)


class EvidenceOut(BaseModel):
    segment_id: int
    start_ms: int
    end_ms: int
    quote: str
    char_start: int
    char_end: int


class KeyPointOut(BaseModel):
    id: str
    sequence: int
    text: str
    evidence: list[EvidenceOut]


class DecisionOut(BaseModel):
    id: str
    sequence: int
    text: str
    rationale: str | None
    made_by_speaker_id: str | None
    made_by_speaker_label: str | None
    confidence: float | None
    evidence: list[EvidenceOut]


class ActionItemOut(BaseModel):
    id: str
    meeting_id: str
    sequence: int | None
    title: str
    description: str | None
    owner_speaker_id: str | None
    owner_label: str | None
    owner_display_name: str | None
    owner_resolution: str
    owner_text: str | None
    due_date: date | None
    due_date_text: str | None
    due_date_precision: str
    priority: str
    status: str
    confidence: float | None
    is_user_edited: bool
    evidence: list[EvidenceOut]


class IntelligenceOut(BaseModel):
    intelligence_id: str
    meeting_id: str
    transcript_id: str
    version: int
    status: str
    llm: dict[str, object]
    usage: dict[str, object]
    quality: dict[str, object]
    summary_short: str | None
    summary_detailed: str | None
    topics: list[str]
    key_points: list[KeyPointOut]
    decisions: list[DecisionOut]
    action_items: list[ActionItemOut]


class ActionItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    owner_speaker_id: str | None = None
    due_date: date | None = None
    priority: Literal["low", "medium", "high", "critical", "unknown"] | None = None
    status: Literal["open", "in_progress", "blocked", "done", "cancelled"] | None = None


class ActionItemCreate(BaseModel):
    meeting_id: str
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    owner_speaker_id: str | None = None
    due_date: date | None = None
    priority: Literal["low", "medium", "high", "critical", "unknown"] = "unknown"


class ActionItemListItem(BaseModel):
    id: str
    meeting_id: str
    meeting_title: str
    title: str
    owner_speaker_id: str | None
    owner_display_name: str | None
    owner_resolution: str
    due_date: date | None
    due_date_precision: str
    priority: str
    status: str
    is_user_edited: bool
    evidence_count: int


class DashboardCounts(BaseModel):
    meetings: dict[str, int]
    action_items: dict[str, int]
    recent_meetings: list[dict[str, object]]
    upcoming_due: list[dict[str, object]]


class MetaOut(BaseModel):
    api_version: str
    environment: str
    schema_version: str
    prompt_version: str
    asr: dict[str, object]
    llm: dict[str, object]
