"""Celery tasks."""

from __future__ import annotations

from app.core.config import get_settings
from app.db.session import session_factory_for
from app.services.analysis_job import run_analysis
from app.services.pipeline import run_pipeline
from app.workers.celery_app import celery_app


@celery_app.task(name="pipeline.process_meeting", bind=True)
def process_meeting_task(self, meeting_id: str, job_id: str) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    run_pipeline(session_factory_for(settings), settings, meeting_id, job_id)


@celery_app.task(name="pipeline.analyze_meeting", bind=True)
def analyze_meeting_task(self, meeting_id: str, job_id: str) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    run_analysis(session_factory_for(settings), settings, meeting_id, job_id)


@celery_app.task(name="pipeline.reconcile_jobs")
def reconcile_jobs_task() -> dict[str, int]:
    from app.services.reconciliation import reconcile_stranded_jobs

    settings = get_settings()
    return reconcile_stranded_jobs(session_factory_for(settings), settings)


@celery_app.task(name="pipeline.purge_expired_audio")
def purge_expired_audio_task() -> dict[str, object]:
    from app.services.retention import enforce_audio_retention
    from app.services.storage import build_storage

    settings = get_settings()
    factory = session_factory_for(settings)
    session = factory()
    try:
        return enforce_audio_retention(session, build_storage(settings), settings)
    finally:
        session.close()


@celery_app.task(name="pipeline.sweep_orphan_audio")
def sweep_orphan_audio_task() -> dict[str, int]:
    from app.services.retention import sweep_orphan_audio
    from app.services.storage import build_storage

    settings = get_settings()
    factory = session_factory_for(settings)
    session = factory()
    try:
        return sweep_orphan_audio(session, build_storage(settings))
    finally:
        session.close()
