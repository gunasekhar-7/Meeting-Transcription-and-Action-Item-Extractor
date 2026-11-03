from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from app.core.config import Settings
from app.db.base import Base, utcnow
from app.db.models import Meeting, ProcessingJob, User
from app.db.session import make_engine, make_session_factory
from app.services.reconciliation import reconcile_stranded_jobs


def test_reconcile_redispatches_stalled_queued_job(settings: Settings) -> None:
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    session = factory()
    user = User(email="test@example.com", password_hash="hash", display_name="Test")
    session.add(user)
    session.flush()

    meeting = Meeting(owner_id=user.id, title="Sync", status="created")
    session.add(meeting)
    session.flush()

    old_time = utcnow() - timedelta(seconds=600)
    job = ProcessingJob(
        meeting_id=meeting.id,
        status="queued",
        created_at=old_time,
        attempt=0,
        max_attempts=2,
    )
    session.add(job)
    session.commit()
    session.close()

    with patch("app.services.reconciliation.dispatch_pipeline") as mock_dispatch:
        result = reconcile_stranded_jobs(factory, settings, max_queued_age_seconds=300)
        assert result["requeued"] == 1
        assert result["failed"] == 0
        assert mock_dispatch.called


def test_reconcile_fails_exhausted_job(settings: Settings) -> None:
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)

    session = factory()
    user = User(email="exhaust@example.com", password_hash="hash", display_name="Test")
    session.add(user)
    session.flush()

    meeting = Meeting(owner_id=user.id, title="Sync", status="created")
    session.add(meeting)
    session.flush()

    old_time = utcnow() - timedelta(seconds=600)
    job = ProcessingJob(
        meeting_id=meeting.id,
        status="queued",
        created_at=old_time,
        attempt=2,
        max_attempts=2,
    )
    session.add(job)
    session.commit()
    session.close()

    result = reconcile_stranded_jobs(factory, settings, max_queued_age_seconds=300)
    assert result["failed"] == 1
    assert result["requeued"] == 0

    session = factory()
    updated_job = session.get(ProcessingJob, job.id)
    assert updated_job is not None
    assert updated_job.status == "failed"
    assert updated_job.error_code == "reconciliation_timeout"
    session.close()
