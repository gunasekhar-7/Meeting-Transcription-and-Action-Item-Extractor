"""Re-run analysis without repeating transcription."""

from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import PipelineError
from app.db.base import utcnow
from app.db.models import Meeting, ProcessingJob
from app.providers.llm import build_llm
from app.services.intelligence import analyze_transcript, load_active_transcript

logger = logging.getLogger(__name__)


def run_analysis(
    factory: sessionmaker[Session], settings: Settings, meeting_id: str, job_id: str
) -> None:
    session = factory()
    started = perf_counter()
    try:
        job = session.get(ProcessingJob, job_id)
        meeting = session.get(Meeting, meeting_id)
        if job is None or meeting is None or job.status not in {"queued", "running"}:
            return

        job.status = "running"
        job.started_at = utcnow()
        job.attempt += 1
        job.stage = "analyzing"
        job.progress = 30
        session.commit()

        transcript = load_active_transcript(session, meeting_id)
        if transcript is None:
            raise PipelineError("transcript_not_ready", "Transcription must complete first")

        meeting.intelligence_status = "processing"
        session.commit()

        provider = build_llm(settings)
        analyze_transcript(session, meeting, transcript, provider, settings)
        session.commit()

        job = session.get(ProcessingJob, job_id)
        assert job is not None
        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.finished_at = utcnow()
        job.duration_ms = int((perf_counter() - started) * 1000)
        session.commit()

    except PipelineError as exc:
        session.rollback()
        job = session.get(ProcessingJob, job_id)
        meeting = session.get(Meeting, meeting_id)
        if job is not None:
            job.status = "failed"
            job.error_code = exc.code
            job.error_detail = exc.message[:500]
            job.finished_at = utcnow()
        if meeting is not None:
            meeting.intelligence_status = "failed"
            if meeting.status != "ready":
                meeting.status = "ready"
        session.commit()
    except Exception:
        logger.exception("analysis_crashed", extra={"extra_fields": {"meeting_id": meeting_id}})
        session.rollback()
        job = session.get(ProcessingJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_code = "internal_error"
            job.error_detail = "Analysis failed unexpectedly"
            job.finished_at = utcnow()
        session.commit()
    finally:
        session.close()


def run_analysis_task(settings: Settings, meeting_id: str, job_id: str) -> None:
    from app.db.session import session_factory_for

    run_analysis(session_factory_for(settings), settings, meeting_id, job_id)


def dispatch_analysis(settings: Settings, meeting_id: str, job_id: str, background_tasks) -> None:  # type: ignore[no-untyped-def]
    if settings.jobs_mode == "celery":
        from app.workers.tasks import analyze_meeting_task

        analyze_meeting_task.delay(meeting_id, job_id)
    else:
        background_tasks.add_task(run_analysis_task, settings, meeting_id, job_id)
