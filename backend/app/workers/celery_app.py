"""Celery configuration.

Non-default settings are deliberate:

* ``task_acks_late``: a worker killed mid-job must not lose the message.
* ``worker_prefetch_multiplier=1``: one job in flight per process, so a long
  transcription cannot hoard queued work.
* time limits: a stuck model call must not pin a worker forever.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "meeting_intelligence",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_soft_time_limit=3480,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_default_queue="nlp",
    task_routes={
        "pipeline.process_meeting": {"queue": "asr"},
        "pipeline.analyze_meeting": {"queue": "nlp"},
        "pipeline.reconcile_jobs": {"queue": "nlp"},
        "pipeline.purge_expired_audio": {"queue": "nlp"},
        "pipeline.sweep_orphan_audio": {"queue": "nlp"},
    },
    beat_schedule={
        "reconcile-stranded-jobs-every-minute": {
            "task": "pipeline.reconcile_jobs",
            "schedule": 60.0,
        },
        "purge-expired-audio-daily": {
            "task": "pipeline.purge_expired_audio",
            "schedule": 86400.0,
        },
        "sweep-orphan-audio-daily": {
            "task": "pipeline.sweep_orphan_audio",
            "schedule": 86400.0,
        },
    },
)
