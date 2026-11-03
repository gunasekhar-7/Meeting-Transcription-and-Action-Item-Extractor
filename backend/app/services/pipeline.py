"""Transcription and analysis pipeline.

Design rules enforced here:

* No database transaction is held across an inference call.
* The transcript is committed before analysis starts, so an LLM failure leaves a
  usable transcript rather than losing work.
* Dispatch happens only after the job row is committed (see ``dispatch``).
"""

from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import PipelineError
from app.db.base import utcnow
from app.db.models import (
    AudioAsset,
    Meeting,
    ProcessingJob,
    Speaker,
    Transcript,
    TranscriptSegment,
)
from app.providers.asr import ASRResult, ASRSegment, build_asr
from app.providers.llm import build_llm
from app.services.intelligence import analyze_transcript
from app.services.storage import build_storage

logger = logging.getLogger(__name__)


def _fail(
    session: Session,
    job_id: str,
    meeting_id: str,
    stage: str,
    code: str,
    message: str,
) -> None:
    session.rollback()
    job = session.get(ProcessingJob, job_id)
    meeting = session.get(Meeting, meeting_id)
    if job is not None:
        job.status = "failed"
        job.error_code = code
        job.error_detail = message[:500]
        job.finished_at = utcnow()
    if meeting is not None:
        if stage == "analyzing":
            meeting.intelligence_status = "failed"
            if meeting.status != "ready":
                meeting.status = "ready"
        else:
            meeting.status = "failed"
        meeting.updated_at = utcnow()
    session.commit()


def _persist_transcript(
    session: Session, meeting: Meeting, result: ASRResult
) -> Transcript:
    version = (
        session.scalar(
            select(func.max(Transcript.version)).where(Transcript.meeting_id == meeting.id)
        )
        or 0
    ) + 1
    session.execute(
        update(Transcript)
        .where(Transcript.meeting_id == meeting.id, Transcript.is_active.is_(True))
        .values(is_active=False)
    )

    duration = result.duration_seconds or meeting.duration_seconds
    rtf = None
    if duration and duration > 0:
        rtf = round(result.processing_seconds / duration, 4)

    transcript = Transcript(
        meeting_id=meeting.id,
        version=version,
        is_active=True,
        status="ready",
        asr_provider=result.provider,
        asr_model=result.model,
        language=result.language,
        language_probability=result.language_probability,
        audio_duration_seconds=duration,
        processing_seconds=result.processing_seconds,
        real_time_factor=rtf,
        segment_count=len(result.segments),
        capability_notes=result.capability_notes,
    )
    session.add(transcript)
    session.flush()

    labels: list[str] = []
    for segment in result.segments:
        if segment.speaker_label and segment.speaker_label not in labels:
            labels.append(segment.speaker_label)

    speakers: dict[str, Speaker] = {}
    for label in labels:
        new_speaker = Speaker(transcript_id=transcript.id, label=label)
        session.add(new_speaker)
        speakers[label] = new_speaker
    session.flush()

    totals: dict[str, tuple[int, int]] = {}
    for index, segment in enumerate(result.segments):
        assigned_speaker = (
            speakers.get(segment.speaker_label) if segment.speaker_label else None
        )
        start_ms = max(0, segment.start_ms)
        end_ms = max(start_ms + 1, segment.end_ms)
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                speaker_id=assigned_speaker.id if assigned_speaker else None,
                sequence=index,
                start_ms=start_ms,
                end_ms=end_ms,
                text=segment.text.strip(),
            )
        )
        if assigned_speaker is not None:
            count, total_ms = totals.get(assigned_speaker.id, (0, 0))
            totals[assigned_speaker.id] = (count + 1, total_ms + (end_ms - start_ms))

    for speaker_id, (count, total_ms) in totals.items():
        stored_speaker = session.get(Speaker, speaker_id)
        if stored_speaker is not None:
            stored_speaker.segment_count = count
            stored_speaker.total_speaking_seconds = round(total_ms / 1000, 2)

    meeting.language = result.language
    meeting.status = "ready"
    meeting.updated_at = utcnow()
    return transcript


def run_pipeline(
    factory: sessionmaker[Session],
    settings: Settings,
    meeting_id: str,
    job_id: str,
) -> None:
    started_wall = perf_counter()
    session = factory()
    stage = "transcribing"
    try:
        job = session.get(ProcessingJob, job_id)
        meeting = session.get(Meeting, meeting_id)
        if job is None or meeting is None or job.status not in {"queued", "running"}:
            return

        job.status = "running"
        job.started_at = job.started_at or utcnow()
        job.attempt += 1
        job.stage = "transcribing"
        job.progress = 15
        session.commit()

        asset = session.scalar(select(AudioAsset).where(AudioAsset.meeting_id == meeting_id))
        if asset is None:
            raise PipelineError("audio_missing", "No audio is attached to this meeting")

        storage = build_storage(settings)
        asr = build_asr(settings)
        audio_path = storage.download_to_temp(asset.object_key)
        try:
            result = asr.transcribe(audio_path)
            if settings.diarization_provider != "none":
                try:
                    from app.pipelines.alignment import Word, assign_speaker
                    from app.providers.diarization import build_diarization

                    diar = build_diarization(settings)
                    diar_res = diar.diarize(audio_path)
                    result.capability_notes.update(diar_res.capability_notes)
                    if diar_res.turns:
                        aligned = []
                        for seg in result.segments:
                            word = Word(start_ms=seg.start_ms, end_ms=seg.end_ms, text=seg.text)
                            assigned = assign_speaker(word, diar_res.turns)
                            aligned.append(
                                ASRSegment(
                                    start_ms=seg.start_ms,
                                    end_ms=seg.end_ms,
                                    text=seg.text,
                                    speaker_label=assigned or seg.speaker_label or "SPEAKER_00",
                                )
                            )
                        result.segments = aligned
                except Exception as diar_exc:
                    logger.warning(
                        "diarization_degraded",
                        extra={"extra_fields": {"reason": str(diar_exc)}},
                    )
                    result.capability_notes["diarization_warning"] = str(diar_exc)
        finally:
            if settings.storage_backend == "s3":
                audio_path.unlink(missing_ok=True)

        transcript = _persist_transcript(session, meeting, result)
        session.commit()

        job = session.get(ProcessingJob, job_id)
        assert job is not None
        job.stage = "analyzing"
        job.progress = 60
        session.commit()

        meeting = session.get(Meeting, meeting_id)
        assert meeting is not None
        meeting.intelligence_status = "processing"
        session.commit()

        stage = "analyzing"
        llm = build_llm(settings)
        analyze_transcript(session, meeting, transcript, llm, settings)
        session.commit()

        job = session.get(ProcessingJob, job_id)
        assert job is not None
        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.finished_at = utcnow()
        job.duration_ms = int((perf_counter() - started_wall) * 1000)
        session.commit()

    except PipelineError as exc:
        logger.warning(
            "pipeline_failed",
            extra={"extra_fields": {"meeting_id": meeting_id, "code": exc.code, "stage": stage}},
        )
        _fail(session, job_id, meeting_id, stage, exc.code, exc.message)
    except Exception:
        logger.exception("pipeline_crashed", extra={"extra_fields": {"meeting_id": meeting_id}})
        _fail(
            session,
            job_id,
            meeting_id,
            stage,
            "internal_error",
            "Processing failed unexpectedly. The transcript, if completed, remains available.",
        )
    finally:
        try:
            job = session.get(ProcessingJob, job_id)
            if job is not None and job.finished_at is None:
                job.finished_at = utcnow()
                job.duration_ms = job.duration_ms or int((perf_counter() - started_wall) * 1000)
                session.commit()
        except Exception:
            session.rollback()
        session.close()


def run_pipeline_task(settings: Settings, meeting_id: str, job_id: str) -> None:
    """Entry point for an in-process background task."""
    from app.db.session import session_factory_for

    run_pipeline(session_factory_for(settings), settings, meeting_id, job_id)


def dispatch_pipeline(settings: Settings, meeting_id: str, job_id: str, background_tasks: object = None) -> None:
    """Dispatch only after the caller has committed the job row.

    Calling this before commit is the classic Celery race: the worker can read a
    job that does not exist yet. The routes here always commit first.
    """
    if settings.jobs_mode == "celery":
        from app.workers.tasks import process_meeting_task

        process_meeting_task.delay(meeting_id, job_id)
    else:
        if background_tasks is not None and hasattr(background_tasks, "add_task"):
            background_tasks.add_task(run_pipeline_task, settings, meeting_id, job_id)
        else:
            run_pipeline_task(settings, meeting_id, job_id)


def retryable_codes() -> set[str]:
    return {"asr_failed", "llm_unavailable", "llm_rate_limited", "llm_error", "internal_error"}


def newest_job(session: Session, meeting_id: str) -> ProcessingJob | None:
    return session.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.meeting_id == meeting_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
