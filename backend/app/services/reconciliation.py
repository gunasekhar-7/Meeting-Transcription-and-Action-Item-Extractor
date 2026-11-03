"""Stranded job reconciliation sweep for the commit-to-dispatch gap and worker death."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import Meeting, ProcessingJob
from app.services.pipeline import dispatch_pipeline

logger = logging.getLogger(__name__)


def reconcile_stranded_jobs(
    factory: sessionmaker[Session],
    settings: Settings,
    *,
    max_queued_age_seconds: int = 300,
    max_running_age_seconds: int = 7200,
) -> dict[str, int]:
    """Inspect and recover stranded processing jobs.

    - Jobs stuck in 'queued' past max_queued_age_seconds (commit-to-dispatch gap)
      are re-dispatched.
    - Jobs stuck in 'running' past max_running_age_seconds (worker death/OOM)
      are marked failed or re-queued up to max_attempts.
    """
    now = utcnow()
    queued_cutoff = now - timedelta(seconds=max_queued_age_seconds)
    running_cutoff = now - timedelta(seconds=max_running_age_seconds)

    requeued = 0
    failed = 0
    checked = 0

    session = factory()
    try:
        # 1. Stalled queued jobs (commit succeeded, dispatch dropped or failed)
        stalled_queued = session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "queued",
                ProcessingJob.created_at <= queued_cutoff,
            )
            .order_by(ProcessingJob.created_at.asc())
        ).all()

        checked += len(stalled_queued)
        for job in stalled_queued:
            if job.attempt >= job.max_attempts:
                job.status = "failed"
                job.error_code = "reconciliation_timeout"
                job.error_detail = "Job exceeded maximum attempts without worker pickup"
                job.finished_at = now
                meeting = session.get(Meeting, job.meeting_id)
                if meeting:
                    meeting.status = "failed"
                    meeting.intelligence_status = "failed"
                    meeting.updated_at = now
                failed += 1
            else:
                logger.warning(
                    "reconciling_stranded_queued_job",
                    extra={"extra_fields": {"job_id": job.id, "meeting_id": job.meeting_id}},
                )
                dispatch_pipeline(settings, job.meeting_id, job.id, None)
                requeued += 1

        # 2. Abandoned running jobs (worker crashed or killed)
        abandoned_running = session.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.status == "running",
                ProcessingJob.started_at.is_not(None),
                ProcessingJob.started_at <= running_cutoff,
            )
            .order_by(ProcessingJob.started_at.asc())
        ).all()

        checked += len(abandoned_running)
        for job in abandoned_running:
            if job.attempt >= job.max_attempts:
                job.status = "failed"
                job.error_code = "worker_timeout"
                job.error_detail = "Worker timed out or crashed without completing"
                job.finished_at = now
                meeting = session.get(Meeting, job.meeting_id)
                if meeting:
                    meeting.status = "failed"
                    meeting.intelligence_status = "failed"
                    meeting.updated_at = now
                failed += 1
            else:
                logger.warning(
                    "requeuing_abandoned_running_job",
                    extra={"extra_fields": {"job_id": job.id, "meeting_id": job.meeting_id}},
                )
                job.status = "queued"
                dispatch_pipeline(settings, job.meeting_id, job.id, None)
                requeued += 1

        session.commit()
    except Exception:
        session.rollback()
        logger.exception("reconciliation_sweep_failed")
        raise
    finally:
        session.close()

    result = {"checked": checked, "requeued": requeued, "failed": failed}
    logger.info("reconciliation_sweep_completed", extra={"extra_fields": result})
    return result
