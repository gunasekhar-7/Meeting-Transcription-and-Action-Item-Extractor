from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

from app.core.config import Settings
from app.db.base import Base, utcnow
from app.db.models import AudioAsset, Meeting, User
from app.db.session import make_engine, make_session_factory
from app.services.retention import enforce_audio_retention, sweep_orphan_audio
from app.services.storage import LocalStorage


def test_enforce_audio_retention_purges_old_audio(tmp_path: Path, settings: Settings) -> None:
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    storage = LocalStorage(tmp_path / "audio_retention")

    session = factory()
    user = User(email="ret@example.com", password_hash="hash", display_name="Ret")
    session.add(user)
    session.flush()

    meeting = Meeting(owner_id=user.id, title="Old Meeting", status="ready")
    session.add(meeting)
    session.flush()

    key = f"audio/{user.id}/{meeting.id}/original.wav"
    storage.save(io.BytesIO(b"fake audio data content"), key, 10_000_000)

    old_date = utcnow() - timedelta(days=45)
    asset = AudioAsset(
        owner_id=user.id,
        meeting_id=meeting.id,
        storage_backend="local",
        object_key=key,
        original_filename="sync.wav",
        content_type="audio/wav",
        size_bytes=100,
        sha256="abc123",
        created_at=old_date,
    )
    session.add(asset)
    session.commit()

    # Audio exists before retention
    assert (storage.root / key).exists()

    report = enforce_audio_retention(session, storage, settings)
    assert report["purged_count"] == 1

    # Audio file is deleted from disk
    assert not (storage.root / key).exists()

    # Asset row is marked purged_at
    refreshed = session.get(AudioAsset, asset.id)
    assert refreshed is not None
    assert refreshed.purged_at is not None
    session.close()


def test_sweep_orphan_audio(tmp_path: Path, settings: Settings) -> None:
    engine = make_engine(settings)
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    storage = LocalStorage(tmp_path / "audio_orphan")

    session = factory()
    # Create orphan file in storage
    orphan_key = "audio/user1/meeting1/orphan.wav"
    storage.save(io.BytesIO(b"abandoned upload"), orphan_key, 10_000_000)

    assert (storage.root / orphan_key).exists()

    result = sweep_orphan_audio(session, storage)
    assert result["deleted_orphans"] == 1
    assert not (storage.root / orphan_key).exists()
    session.close()
