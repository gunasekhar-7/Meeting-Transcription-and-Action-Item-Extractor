"""SQLAlchemy models for the meeting intelligence domain."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_uuid, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    meetings: Mapped[list[Meeting]] = relationship(back_populates="owner", cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("role IN ('user','admin')", name="ck_users_role"),)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meeting_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    intelligence_status: Mapped[str] = mapped_column(String(20), default="pending")
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="meetings")
    audio_asset: Mapped[AudioAsset | None] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )
    transcripts: Mapped[list[Transcript]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True
    )
    intelligence_runs: Mapped[list[MeetingIntelligence]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True
    )
    action_items: Mapped[list[ActionItem]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('created','processing','ready','failed')", name="ck_meetings_status"
        ),
        CheckConstraint(
            "intelligence_status IN ('pending','processing','ready','failed','skipped')",
            name="ck_meetings_intel_status",
        ),
        Index("ix_meetings_owner_created", "owner_id", "created_at"),
    )


class AudioAsset(Base):
    __tablename__ = "audio_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), unique=True
    )
    storage_backend: Mapped[str] = mapped_column(String(20), default="local")
    object_key: Mapped[str] = mapped_column(String(1024), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    codec: Mapped[str | None] = mapped_column(String(40), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="audio_asset")

    __table_args__ = (
        UniqueConstraint("owner_id", "sha256", name="uq_audio_owner_sha"),
        CheckConstraint("size_bytes > 0", name="ck_audio_size_positive"),
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    asr_provider: Mapped[str] = mapped_column(String(40))
    asr_model: Mapped[str] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    language_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    real_time_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    capability_notes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="transcripts")
    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan", passive_deletes=True
    )
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TranscriptSegment.sequence",
    )

    __table_args__ = (
        UniqueConstraint("meeting_id", "version", name="uq_transcript_version"),
        CheckConstraint("status IN ('processing','ready','failed')", name="ck_transcripts_status"),
    )


class Speaker(Base):
    __tablename__ = "speakers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(50))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_named: Mapped[bool] = mapped_column(Boolean, default=False)
    total_speaking_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)

    transcript: Mapped[Transcript] = relationship(back_populates="speakers")
    segments: Mapped[list[TranscriptSegment]] = relationship(back_populates="speaker")

    __table_args__ = (UniqueConstraint("transcript_id", "label", name="uq_speaker_label"),)


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    speaker_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    is_low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")
    speaker: Mapped[Speaker | None] = relationship(back_populates="segments")

    __table_args__ = (
        UniqueConstraint("transcript_id", "sequence", name="uq_segment_sequence"),
        CheckConstraint("start_ms >= 0", name="ck_segment_start"),
        CheckConstraint("end_ms > start_ms", name="ck_segment_end"),
        Index("ix_segments_transcript_start", "transcript_id", "start_ms"),
    )


class MeetingIntelligence(Base):
    __tablename__ = "meeting_intelligence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    transcript_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcripts.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="running")
    llm_provider: Mapped[str] = mapped_column(String(40))
    llm_model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(20))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_detailed: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="intelligence_runs")
    transcript: Mapped[Transcript] = relationship()
    key_points: Mapped[list[KeyPoint]] = relationship(
        back_populates="intelligence", cascade="all, delete-orphan", passive_deletes=True
    )
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="intelligence", cascade="all, delete-orphan", passive_deletes=True
    )
    action_items: Mapped[list[ActionItem]] = relationship(back_populates="intelligence")

    __table_args__ = (
        UniqueConstraint("meeting_id", "version", name="uq_intel_version"),
        CheckConstraint(
            "status IN ('pending','running','ready','failed','skipped')", name="ck_intel_status"
        ),
    )


class KeyPoint(Base):
    __tablename__ = "key_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    intelligence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_intelligence.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    intelligence: Mapped[MeetingIntelligence] = relationship(back_populates="key_points")
    evidence: Mapped[list[EvidenceLink]] = relationship(
        back_populates="key_point", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("intelligence_id", "sequence", name="uq_keypoint_seq"),)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    intelligence_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_intelligence.id", ondelete="CASCADE"), index=True
    )
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    made_by_speaker_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    intelligence: Mapped[MeetingIntelligence] = relationship(back_populates="decisions")
    evidence: Mapped[list[EvidenceLink]] = relationship(
        back_populates="decision", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("intelligence_id", "sequence", name="uq_decision_seq"),)


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    intelligence_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("meeting_intelligence.id", ondelete="SET NULL"), nullable=True
    )
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_speaker_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("speakers.id", ondelete="RESTRICT"), nullable=True
    )
    owner_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_resolution: Mapped[str] = mapped_column(String(30), default="unassigned")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date_precision: Mapped[str] = mapped_column(String(20), default="unknown")
    priority: Mapped[str] = mapped_column(String(20), default="unknown")
    status: Mapped[str] = mapped_column(String(20), default="open")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    meeting: Mapped[Meeting] = relationship(back_populates="action_items")
    intelligence: Mapped[MeetingIntelligence | None] = relationship(back_populates="action_items")
    owner: Mapped[Speaker | None] = relationship()
    evidence: Mapped[list[EvidenceLink]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "owner_resolution IN ('matched_speaker','unresolved_mention','unassigned')",
            name="ck_action_owner_resolution",
        ),
        CheckConstraint(
            "owner_resolution <> 'matched_speaker' OR owner_speaker_id IS NOT NULL",
            name="ck_action_owner_present",
        ),
        CheckConstraint(
            "owner_resolution = 'unassigned' OR owner_text IS NOT NULL",
            name="ck_action_owner_text",
        ),
        CheckConstraint(
            "due_date_precision IN ('day','week','month','quarter','unknown')",
            name="ck_action_due_precision",
        ),
        CheckConstraint(
            "due_date_precision <> 'unknown' OR due_date IS NULL",
            name="ck_action_due_unknown",
        ),
        CheckConstraint(
            "due_date IS NULL OR due_date_text IS NOT NULL", name="ck_action_due_text"
        ),
        CheckConstraint(
            "priority IN ('low','medium','high','critical','unknown')", name="ck_action_priority"
        ),
        CheckConstraint(
            "status IN ('open','in_progress','blocked','done','cancelled')",
            name="ck_action_status",
        ),
        Index("ix_actions_meeting_status", "meeting_id", "status"),
        Index("ix_actions_due_date", "due_date"),
    )


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    transcript_segment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transcript_segments.id", ondelete="CASCADE"), index=True
    )
    decision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("decisions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("action_items.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key_point_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("key_points.id", ondelete="CASCADE"), nullable=True, index=True
    )
    quote: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    verified_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    decision: Mapped[Decision | None] = relationship(back_populates="evidence")
    action_item: Mapped[ActionItem | None] = relationship(back_populates="evidence")
    key_point: Mapped[KeyPoint | None] = relationship(back_populates="evidence")

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN decision_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN action_item_id IS NULL THEN 0 ELSE 1 END) + "
            "(CASE WHEN key_point_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_evidence_one_target",
        ),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(30), default="pipeline")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    meeting: Mapped[Meeting] = relationship(back_populates="jobs")

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="ck_job_status",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_job_progress"),
        Index("ix_jobs_meeting_created", "meeting_id", "created_at"),
    )
