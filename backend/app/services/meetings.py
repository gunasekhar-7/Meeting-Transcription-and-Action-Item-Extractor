"""Meeting lifecycle helpers."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    ActionItem,
    AudioAsset,
    Decision,
    EvidenceLink,
    KeyPoint,
    Meeting,
    MeetingIntelligence,
    ProcessingJob,
    Speaker,
    Transcript,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


def delete_meeting_cascade(session: Session, meeting: Meeting) -> list[str]:
    """Delete all meeting rows in dependency order and return audio object keys.

    Relying on database cascade order here is unsafe: ``action_items`` reference
    ``speakers`` with ON DELETE RESTRICT, and SQLite checks that immediately. The
    order below is explicit and portable.
    """
    asset = session.scalar(select(AudioAsset).where(AudioAsset.meeting_id == meeting.id))
    object_keys = [asset.object_key] if asset else []

    intelligence_ids = select(MeetingIntelligence.id).where(
        MeetingIntelligence.meeting_id == meeting.id
    )
    transcript_ids = select(Transcript.id).where(Transcript.meeting_id == meeting.id)

    session.execute(delete(EvidenceLink).where(EvidenceLink.meeting_id == meeting.id))
    session.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting.id))
    session.execute(delete(Decision).where(Decision.meeting_id == meeting.id))
    session.execute(delete(KeyPoint).where(KeyPoint.intelligence_id.in_(intelligence_ids)))
    session.execute(
        delete(MeetingIntelligence).where(MeetingIntelligence.meeting_id == meeting.id)
    )
    session.execute(
        delete(TranscriptSegment).where(TranscriptSegment.transcript_id.in_(transcript_ids))
    )
    session.execute(delete(Speaker).where(Speaker.transcript_id.in_(transcript_ids)))
    session.execute(delete(Transcript).where(Transcript.meeting_id == meeting.id))
    session.execute(delete(AudioAsset).where(AudioAsset.meeting_id == meeting.id))
    session.execute(delete(ProcessingJob).where(ProcessingJob.meeting_id == meeting.id))
    session.delete(meeting)
    return object_keys
