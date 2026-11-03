"""Audio retention enforcement and orphan object sweep."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import AudioAsset
from app.services.storage import Storage

logger = logging.getLogger(__name__)


def enforce_audio_retention(
    session: Session,
    storage: Storage,
    settings: Settings,
) -> dict[str, Any]:
    """Delete audio assets older than settings.audio_retention_days and mark purged_at.

    Enforces the retention policy defined in AUDIO_RETENTION_DAYS. Audio is removed
    from storage to minimize data exposure and storage costs; transcripts and
    intelligence records remain preserved.
    """
    if settings.audio_retention_days <= 0:
        return {"purged_count": 0, "status": "disabled"}

    cutoff = utcnow() - timedelta(days=settings.audio_retention_days)
    expired_assets = session.scalars(
        select(AudioAsset).where(
            AudioAsset.purged_at.is_(None),
            AudioAsset.created_at <= cutoff,
        )
    ).all()

    purged_count = 0
    for asset in expired_assets:
        try:
            storage.delete(asset.object_key)
            asset.purged_at = utcnow()
            purged_count += 1
            logger.info(
                "audio_purged_for_retention",
                extra={
                    "extra_fields": {
                        "asset_id": asset.id,
                        "meeting_id": asset.meeting_id,
                        "object_key": asset.object_key,
                    }
                },
            )
        except Exception:
            logger.exception(
                "audio_purge_failed",
                extra={"extra_fields": {"asset_id": asset.id, "object_key": asset.object_key}},
            )

    session.commit()
    return {"purged_count": purged_count, "cutoff": cutoff.isoformat()}


def sweep_orphan_audio(
    session: Session,
    storage: Storage,
) -> dict[str, int]:
    """Find and remove audio objects in storage that have no active AudioAsset record.

    Prevents storage leaks from interrupted multipart uploads, crashed deletes, or
    abandoned temporary files.
    """
    storage_keys = set(storage.list_keys(prefix="audio/"))
    if not storage_keys:
        return {"scanned_keys": 0, "deleted_orphans": 0}

    active_keys = set(
        session.scalars(
            select(AudioAsset.object_key).where(AudioAsset.purged_at.is_(None))
        ).all()
    )

    orphan_keys = storage_keys - active_keys
    deleted_count = 0
    for key in orphan_keys:
        try:
            storage.delete(key)
            deleted_count += 1
            logger.info("orphan_audio_deleted", extra={"extra_fields": {"object_key": key}})
        except Exception:
            logger.exception("orphan_audio_delete_failed", extra={"extra_fields": {"object_key": key}})

    return {"scanned_keys": len(storage_keys), "deleted_orphans": deleted_count}
