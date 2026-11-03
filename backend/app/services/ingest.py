"""Audio ingestion: validation before anything is persisted."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import mutagen
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    AudioTooLong,
    AudioUnreadable,
    DuplicateAudio,
    UnsupportedMedia,
)
from app.db.base import utcnow
from app.db.models import AudioAsset, Meeting
from app.services.storage import Storage

logger = logging.getLogger(__name__)

ALLOWED = {
    ".wav": ("audio/wav", b"RIFF"),
    ".mp3": ("audio/mpeg", b"ID3"),
    ".m4a": ("audio/mp4", b"ftyp"),
    ".flac": ("audio/flac", b"fLaC"),
    ".ogg": ("audio/ogg", b"OggS"),
    ".webm": ("audio/webm", b"\x1aE\xdf\xa3"),
}


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float
    sample_rate: int | None
    channels: int | None
    codec: str | None


def safe_filename(filename: str | None) -> str:
    name = Path(filename or "recording").name
    cleaned = "".join(ch for ch in name if ch.isprintable() and ch not in {'"', "'", "\\", "/"}).strip()
    return cleaned[:255] or "recording"


def container_matches(head: bytes, extension: str) -> bool:
    if extension == ".mp3":
        return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
    if extension == ".m4a":
        return len(head) >= 12 and head[4:8] == b"ftyp"
    return head.startswith(ALLOWED[extension][1])


def probe_audio(path: Path) -> AudioProbe:
    try:
        media = mutagen.File(str(path))
    except Exception as exc:
        logger.warning("audio_probe_failed", extra={"extra_fields": {"reason": type(exc).__name__}})
        raise AudioUnreadable("The file could not be decoded as audio") from exc
    if media is None or media.info is None:
        raise AudioUnreadable("The file could not be decoded as audio")

    info = media.info
    duration = float(getattr(info, "length", 0) or 0)
    if duration <= 0:
        raise AudioUnreadable("The audio file contains no readable audio")
    return AudioProbe(
        duration_seconds=round(duration, 3),
        sample_rate=getattr(info, "sample_rate", None),
        channels=getattr(info, "channels", None),
        codec=type(media).__name__.lower(),
    )


def validate_upload_shape(filename: str | None, head: bytes) -> tuple[str, str]:
    name = safe_filename(filename)
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED:
        raise UnsupportedMedia(
            "Supported formats: " + ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED))
        )
    if not container_matches(head, extension):
        raise UnsupportedMedia("File contents do not match the file extension")
    return name, ALLOWED[extension][0]


def store_upload(
    session: Session,
    meeting: Meeting,
    upload: UploadFile,
    storage: Storage,
    settings: Settings,
) -> AudioAsset:
    stream = upload.file
    head = stream.read(32)
    if not head:
        raise AudioUnreadable("Uploaded file is empty")
    stream.seek(0)

    filename, content_type = validate_upload_shape(upload.filename, head)
    extension = Path(filename).suffix.lower()
    key = f"audio/{meeting.owner_id}/{meeting.id}/original{extension}"

    size, sha256 = storage.save(stream, key, settings.max_upload_bytes)

    existing = session.scalar(
        select(AudioAsset).where(
            AudioAsset.owner_id == meeting.owner_id,
            AudioAsset.sha256 == sha256,
            AudioAsset.meeting_id != meeting.id,
        )
    )
    if existing is not None:
        storage.delete(key)
        raise DuplicateAudio(existing.meeting_id)

    try:
        probe = probe_audio(storage.download_to_temp(key))
    except Exception:
        storage.delete(key)
        raise

    if probe.duration_seconds > settings.max_audio_minutes * 60:
        storage.delete(key)
        raise AudioTooLong(f"Audio is limited to {settings.max_audio_minutes} minutes")

    asset = AudioAsset(
        owner_id=meeting.owner_id,
        meeting_id=meeting.id,
        storage_backend=settings.storage_backend,
        object_key=key,
        original_filename=filename,
        content_type=content_type,
        codec=probe.codec,
        size_bytes=size,
        sha256=sha256,
        duration_seconds=probe.duration_seconds,
        sample_rate=probe.sample_rate,
        channels=probe.channels,
        created_at=utcnow(),
    )
    session.add(asset)
    meeting.duration_seconds = probe.duration_seconds
    meeting.status = "processing"
    meeting.updated_at = utcnow()
    return asset
