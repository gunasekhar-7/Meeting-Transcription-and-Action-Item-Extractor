"""Meeting routes."""

from __future__ import annotations

import logging
from math import ceil
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, File, Query, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import AppSettings, CurrentUser, Db
from app.api.presenters import (
    action_item_out,
    decision_out,
    intelligence_out,
    meeting_out,
    speaker_out,
    transcript_out,
)
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.db.base import utcnow
from app.db.models import (
    ActionItem,
    Meeting,
    ProcessingJob,
    Speaker,
    Transcript,
    TranscriptSegment,
)
from app.schemas.api import (
    ActionItemOut,
    DecisionOut,
    JobErrorOut,
    MeetingCreate,
    MeetingOut,
    MeetingUpdate,
    SpeakerOut,
    SpeakerUpdate,
    StageStatus,
    StatusResponse,
    TranscriptOut,
    TranscriptSearchHit,
    TranscriptSearchResponse,
    UploadResponse,
)
from app.schemas.common import Page
from app.services.analysis_job import dispatch_analysis
from app.services.exports import (
    export_payload,
    render_markdown,
    render_subtitles,
    render_text,
)
from app.services.ingest import store_upload
from app.services.intelligence import load_active_intelligence, load_active_transcript
from app.services.meetings import delete_meeting_cascade
from app.services.pipeline import dispatch_pipeline, newest_job, retryable_codes
from app.services.storage import build_storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/meetings", tags=["meetings"])


def _meeting_query():
    return select(Meeting).options(
        selectinload(Meeting.audio_asset),
        selectinload(Meeting.transcripts).selectinload(Transcript.speakers),
        selectinload(Meeting.action_items),
    )


def _load_meeting(db, user, meeting_id: str) -> Meeting:
    meeting = db.scalar(_meeting_query().where(Meeting.id == meeting_id, Meeting.owner_id == user.id))
    if meeting is None:
        raise NotFound("Meeting not found")
    return meeting


@router.post("", response_model=MeetingOut, status_code=status.HTTP_201_CREATED)
def create_meeting(payload: MeetingCreate, db: Db, user: CurrentUser) -> MeetingOut:
    meeting = Meeting(
        owner_id=user.id,
        title=payload.title.strip(),
        description=(payload.description or "").strip() or None,
        meeting_date=payload.meeting_date,
        status="created",
        intelligence_status="pending",
    )
    db.add(meeting)
    db.commit()
    return meeting_out(meeting)


@router.get("", response_model=Page[MeetingOut])
def list_meetings(
    db: Db,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
) -> Page[MeetingOut]:
    filters = [Meeting.owner_id == user.id]
    if status_filter:
        filters.append(Meeting.status == status_filter)
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(or_(Meeting.title.ilike(pattern), Meeting.description.ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(Meeting).where(*filters)) or 0
    rows = db.scalars(
        _meeting_query()
        .where(*filters)
        .order_by(Meeting.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return Page[MeetingOut](
        items=[meeting_out(item) for item in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=ceil(total / page_size) if total else 0,
    )


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: str, db: Db, user: CurrentUser) -> MeetingOut:
    return meeting_out(_load_meeting(db, user, meeting_id))


@router.patch("/{meeting_id}", response_model=MeetingOut)
def update_meeting(
    meeting_id: str, payload: MeetingUpdate, db: Db, user: CurrentUser
) -> MeetingOut:
    meeting = _load_meeting(db, user, meeting_id)
    fields = payload.model_fields_set

    if "title" in fields:
        if not payload.title or not payload.title.strip():
            raise ValidationFailed("Title cannot be empty")
        meeting.title = payload.title.strip()
    if "description" in fields:
        meeting.description = (payload.description or "").strip() or None
    if "meeting_date" in fields:
        meeting.meeting_date = payload.meeting_date

    meeting.updated_at = utcnow()
    db.commit()
    return meeting_out(meeting)


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(
    meeting_id: str, db: Db, user: CurrentUser, settings: AppSettings
) -> Response:
    meeting = _load_meeting(db, user, meeting_id)
    object_keys = delete_meeting_cascade(db, meeting)
    db.commit()

    storage = build_storage(settings)
    for key in object_keys:
        try:
            storage.delete(key)
        except Exception:
            logger.warning(
                "audio_delete_failed",
                extra={"extra_fields": {"meeting_id": meeting_id, "object_key": key}},
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{meeting_id}/audio", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_audio(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db: Db,
    user: CurrentUser,
    settings: AppSettings,
    file: UploadFile = File(...),
) -> UploadResponse:
    meeting = _load_meeting(db, user, meeting_id)
    if meeting.audio_asset is not None:
        raise Conflict("Audio is already uploaded for this meeting")

    storage = build_storage(settings)
    asset = store_upload(db, meeting, file, storage, settings)

    job = ProcessingJob(
        meeting_id=meeting.id,
        job_type="pipeline",
        status="queued",
        stage="queued",
        progress=0,
    )
    db.add(job)
    meeting.intelligence_status = "pending"
    db.commit()

    # Dispatch strictly after commit: a worker must never observe an uncommitted job.
    dispatch_pipeline(settings, meeting.id, job.id, background_tasks)

    return UploadResponse(
        meeting_id=meeting.id,
        audio_asset_id=asset.id,
        job_id=job.id,
        status="queued",
        status_url=f"{settings.api_prefix}/meetings/{meeting.id}/status",
    )


@router.get("/{meeting_id}/status", response_model=StatusResponse)
def get_status(meeting_id: str, db: Db, user: CurrentUser) -> StatusResponse:
    meeting = _load_meeting(db, user, meeting_id)
    job = newest_job(db, meeting.id)

    stages: list[StageStatus] = []
    order = ["transcribing", "analyzing"]
    if job is None:
        stages = [StageStatus(name=name, status="queued", progress=0, duration_ms=None) for name in order]
    else:
        current = job.stage
        current_index = order.index(current) if current in order else len(order)
        for index, name in enumerate(order):
            if job.status == "succeeded" or index < current_index:
                stage_status, progress = "succeeded", 100
            elif index == current_index:
                stage_status, progress = job.status, job.progress
            else:
                stage_status, progress = "queued", 0
            stages.append(
                StageStatus(name=name, status=stage_status, progress=progress, duration_ms=None)
            )

    error = None
    if job is not None and job.status == "failed" and job.error_code:
        error = JobErrorOut(
            code=job.error_code,
            message=job.error_detail or "Processing failed",
            retryable=job.error_code in retryable_codes(),
        )

    return StatusResponse(
        meeting_id=meeting.id,
        status=meeting.status,
        intelligence_status=meeting.intelligence_status,
        stages=stages,
        error=error,
        updated_at=meeting.updated_at,
    )


@router.get("/{meeting_id}/transcript", response_model=TranscriptOut)
def get_transcript(
    meeting_id: str,
    db: Db,
    user: CurrentUser,
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
) -> TranscriptOut:
    meeting = _load_meeting(db, user, meeting_id)
    transcript = load_active_transcript(db, meeting.id)
    if transcript is None:
        raise NotFound("Transcript is not ready")
    return transcript_out(transcript, offset=offset, limit=limit)


@router.get("/{meeting_id}/transcript/search", response_model=TranscriptSearchResponse)
def search_transcript(
    meeting_id: str,
    db: Db,
    user: CurrentUser,
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(20, ge=1, le=100),
) -> TranscriptSearchResponse:
    meeting = _load_meeting(db, user, meeting_id)
    transcript = load_active_transcript(db, meeting.id)
    if transcript is None:
        raise NotFound("Transcript is not ready")

    pattern = f"%{q.strip()}%"
    segments = db.scalars(
        select(TranscriptSegment)
        .where(
            TranscriptSegment.transcript_id == transcript.id,
            TranscriptSegment.text.ilike(pattern),
        )
        .order_by(TranscriptSegment.start_ms)
        .limit(limit)
    ).all()
    speakers = {speaker.id: speaker for speaker in transcript.speakers}

    hits = []
    needle = q.strip().lower()
    for segment in segments:
        index = segment.text.lower().find(needle)
        start = max(0, index - 60)
        end = min(len(segment.text), index + len(q) + 60)
        snippet = ("…" if start > 0 else "") + segment.text[start:end] + ("…" if end < len(segment.text) else "")
        speaker = speakers.get(segment.speaker_id) if segment.speaker_id else None
        hits.append(
            TranscriptSearchHit(
                segment_id=segment.id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                speaker_label=speaker.label if speaker else None,
                snippet=snippet,
            )
        )
    return TranscriptSearchResponse(query=q, total=len(hits), hits=hits)


@router.patch("/{meeting_id}/speakers/{speaker_id}", response_model=SpeakerOut)
def rename_speaker(
    meeting_id: str, speaker_id: str, payload: SpeakerUpdate, db: Db, user: CurrentUser
) -> SpeakerOut:
    meeting = _load_meeting(db, user, meeting_id)
    transcript = load_active_transcript(db, meeting.id)
    if transcript is None:
        raise NotFound("Transcript is not ready")
    speaker = db.get(Speaker, speaker_id)
    if speaker is None or speaker.transcript_id != transcript.id:
        raise NotFound("Speaker not found")

    name = (payload.display_name or "").strip() or None
    speaker.display_name = name
    speaker.is_named = name is not None
    db.commit()
    return speaker_out(speaker)


@router.get("/{meeting_id}/intelligence")
def get_intelligence(meeting_id: str, db: Db, user: CurrentUser) -> dict:
    meeting = _load_meeting(db, user, meeting_id)
    intelligence = load_active_intelligence(db, meeting.id)
    if intelligence is None:
        raise NotFound("Meeting intelligence is not ready")
    transcript = db.get(Transcript, intelligence.transcript_id)
    if transcript is None:
        raise NotFound("Transcript is not ready")
    return jsonable_encoder(intelligence_out(intelligence, transcript))


@router.get("/{meeting_id}/decisions", response_model=list[DecisionOut])
def get_decisions(meeting_id: str, db: Db, user: CurrentUser) -> list[DecisionOut]:
    meeting = _load_meeting(db, user, meeting_id)
    intelligence = load_active_intelligence(db, meeting.id)
    if intelligence is None:
        raise NotFound("Meeting intelligence is not ready")
    transcript = db.get(Transcript, intelligence.transcript_id)
    if transcript is None:
        raise NotFound("Transcript is not ready")
    segments = {segment.id: segment for segment in transcript.segments}
    speakers = {speaker.id: speaker for speaker in transcript.speakers}
    return [decision_out(item, segments, speakers) for item in intelligence.decisions]


@router.get("/{meeting_id}/action-items", response_model=list[ActionItemOut])
def get_meeting_action_items(meeting_id: str, db: Db, user: CurrentUser) -> list[ActionItemOut]:
    meeting = _load_meeting(db, user, meeting_id)
    transcript = load_active_transcript(db, meeting.id)
    if transcript is None:
        raise NotFound("Transcript is not ready")
    segments = {segment.id: segment for segment in transcript.segments}
    items = db.scalars(
        select(ActionItem)
        .options(selectinload(ActionItem.owner), selectinload(ActionItem.evidence))
        .where(ActionItem.meeting_id == meeting.id)
        .order_by(ActionItem.sequence)
    ).all()
    return [action_item_out(item, segments) for item in items]


@router.post("/{meeting_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze_meeting(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    db: Db,
    user: CurrentUser,
    settings: AppSettings,
) -> dict:
    meeting = _load_meeting(db, user, meeting_id)
    transcript = load_active_transcript(db, meeting.id)
    if transcript is None:
        raise Conflict("Transcription must complete before analysis")

    job = ProcessingJob(
        meeting_id=meeting.id,
        job_type="analyze",
        status="queued",
        stage="queued",
        progress=0,
    )
    db.add(job)
    meeting.intelligence_status = "processing"
    db.commit()
    dispatch_analysis(settings, meeting.id, job.id, background_tasks)
    return {"meeting_id": meeting.id, "job_id": job.id, "status": "queued"}


@router.get("/{meeting_id}/export")
def export_meeting(
    meeting_id: str,
    db: Db,
    user: CurrentUser,
    export_format: Literal["json", "md", "txt", "srt", "vtt"] = Query("json", alias="format"),
) -> Response:
    meeting = _load_meeting(db, user, meeting_id)
    transcript = load_active_transcript(db, meeting.id)
    intelligence = load_active_intelligence(db, meeting.id)
    if transcript is None or intelligence is None:
        raise Conflict("Meeting intelligence is not ready for export")

    stem = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in meeting.title)[:50] or "meeting"
    headers = {"Content-Disposition": f'attachment; filename="{stem}.{export_format}"'}

    if export_format == "json":
        return JSONResponse(
            content=jsonable_encoder(export_payload(meeting, transcript, intelligence)),
            headers=headers,
        )
    if export_format == "md":
        return Response(
            content=render_markdown(meeting, transcript, intelligence),
            media_type="text/markdown",
            headers=headers,
        )
    if export_format == "txt":
        return Response(content=render_text(transcript), media_type="text/plain", headers=headers)
    if export_format == "srt":
        return Response(
            content=render_subtitles(transcript, vtt=False),
            media_type="application/x-subrip",
            headers=headers,
        )
    return Response(
        content=render_subtitles(transcript, vtt=True), media_type="text/vtt", headers=headers
    )
