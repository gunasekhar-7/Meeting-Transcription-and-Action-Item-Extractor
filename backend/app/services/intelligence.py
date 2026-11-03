"""Turn a transcript into validated, evidence-grounded meeting intelligence."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import PipelineError
from app.db.base import utcnow
from app.db.models import (
    ActionItem,
    Decision,
    EvidenceLink,
    KeyPoint,
    Meeting,
    MeetingIntelligence,
    Speaker,
    Transcript,
    TranscriptSegment,
)
from app.providers.llm import LLMProvider, SegmentView
from app.schemas.llm import (
    ActionItemOut,
    ActionPayload,
    DecisionPayload,
    EvidenceRef,
    SummaryPayload,
)
from app.services.grounding import quote_supported, verify_quote

logger = logging.getLogger(__name__)

MAX_SHORT_SUMMARY_WORDS = 80


@dataclass(frozen=True)
class VerifiedEvidence:
    segment: TranscriptSegment
    quote: str
    start: int
    end: int


@dataclass
class RunStats:
    dropped_actions: int = 0
    dropped_decisions: int = 0
    grounding_failures: int = 0
    stored_actions: int = 0
    stored_decisions: int = 0
    stored_key_points: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, int | list[str]]:
        return {
            "items_dropped": self.dropped_actions + self.dropped_decisions,
            "dropped_actions": self.dropped_actions,
            "dropped_decisions": self.dropped_decisions,
            "grounding_failures": self.grounding_failures,
            "stored_actions": self.stored_actions,
            "stored_decisions": self.stored_decisions,
            "stored_key_points": self.stored_key_points,
            "notes": self.notes,
        }


def _verify_refs(
    refs: list[EvidenceRef], segments: dict[int, TranscriptSegment]
) -> tuple[list[VerifiedEvidence], int]:
    verified: list[VerifiedEvidence] = []
    failures = 0
    for ref in refs:
        segment_id = ref.segment_id
        quote = ref.quote
        segment = segments.get(segment_id)
        if segment is None:
            failures += 1
            continue
        match = verify_quote(segment.text, quote)
        if match is None:
            failures += 1
            continue
        verified.append(
            VerifiedEvidence(segment=segment, quote=match.text, start=match.start, end=match.end)
        )
    return verified, failures


def _speaker_maps(transcript: Transcript) -> tuple[dict[str, Speaker], dict[str, Speaker]]:
    by_label: dict[str, Speaker] = {}
    by_name: dict[str, Speaker] = {}
    for speaker in transcript.speakers:
        by_label[speaker.label.lower()] = speaker
        if speaker.display_name:
            by_name[speaker.display_name.lower()] = speaker
    return by_label, by_name


def _resolve_owner(
    item: ActionItemOut,
    evidence: list[VerifiedEvidence],
    transcript: Transcript,
) -> tuple[str, str | None, str | None]:
    """Return (resolution, speaker_id, owner_text).

    A name is only accepted when it appears in the evidence quote. This is the
    rule that prevents a plausible-sounding but unsupported owner from being
    stored as fact.
    """
    by_label, by_name = _speaker_maps(transcript)
    haystack = " ".join(entry.quote for entry in evidence).lower()

    speaker: Speaker | None = None
    if item.owner_label:
        speaker = by_label.get(item.owner_label.lower()) or by_name.get(item.owner_label.lower())

    if speaker is not None:
        needle = (item.owner_mention or speaker.display_name or speaker.label).lower()
        if needle in haystack:
            return "matched_speaker", speaker.id, (item.owner_mention or speaker.display_name or speaker.label)

    mention = (item.owner_mention or "").strip()
    if mention and mention.lower() in haystack:
        return "unresolved_mention", None, mention

    return "unassigned", None, None


def _resolve_due(item: ActionItemOut, evidence: list[VerifiedEvidence]) -> tuple[date | None, str | None, str]:
    due_text = (item.due_date_text or "").strip() or None
    if due_text and not any(quote_supported(entry.segment.text, due_text) for entry in evidence):
        due_text = None

    precision = item.due_date_precision
    parsed: date | None = None
    if item.due_date and due_text:
        try:
            parsed = date.fromisoformat(item.due_date)
        except ValueError:
            parsed = None

    if parsed is None:
        precision = "unknown"
    elif precision == "unknown":
        precision = "day"
    return parsed, due_text, precision


def _add_evidence(
    session: Session,
    *,
    meeting_id: str,
    verified: list[VerifiedEvidence],
    decision_id: str | None = None,
    action_item_id: str | None = None,
    key_point_id: str | None = None,
) -> None:
    for entry in verified:
        session.add(
            EvidenceLink(
                meeting_id=meeting_id,
                transcript_segment_id=entry.segment.id,
                decision_id=decision_id,
                action_item_id=action_item_id,
                key_point_id=key_point_id,
                quote=entry.quote,
                char_start=entry.start,
                char_end=entry.end,
                verified_at=utcnow(),
            )
        )


def analyze_transcript(
    session: Session,
    meeting: Meeting,
    transcript: Transcript,
    provider: LLMProvider,
    settings: Settings,
) -> MeetingIntelligence:
    segments = list(transcript.segments)
    if not segments:
        raise PipelineError("empty_transcript", "The transcript has no segments to analyse")

    by_id = {segment.id: segment for segment in segments}
    views = [
        SegmentView(
            id=segment.id,
            start_ms=segment.start_ms,
            speaker_label=segment.speaker.label if segment.speaker else None,
            text=segment.text,
        )
        for segment in segments
    ]

    summary_raw = provider.generate("summary", views)
    decisions_raw = provider.generate("decisions", views)
    actions_raw = provider.generate("actions", views)

    try:
        summary = SummaryPayload.model_validate(summary_raw.payload)
        decisions = DecisionPayload.model_validate(decisions_raw.payload)
        actions = ActionPayload.model_validate(actions_raw.payload)
    except ValidationError as exc:
        logger.warning(
            "llm_schema_validation_failed",
            extra={"extra_fields": {"errors": exc.errors()[:3]}},
        )
        raise PipelineError(
            "llm_invalid_output", "The language model returned data that failed validation"
        ) from exc

    stats = RunStats()
    version = (
        session.scalar(
            select(func.max(MeetingIntelligence.version)).where(
                MeetingIntelligence.meeting_id == meeting.id
            )
        )
        or 0
    ) + 1
    session.execute(
        update(MeetingIntelligence)
        .where(MeetingIntelligence.meeting_id == meeting.id, MeetingIntelligence.is_active.is_(True))
        .values(is_active=False)
    )

    input_tokens = summary_raw.input_tokens + decisions_raw.input_tokens + actions_raw.input_tokens
    output_tokens = (
        summary_raw.output_tokens + decisions_raw.output_tokens + actions_raw.output_tokens
    )
    latency_ms = summary_raw.latency_ms + decisions_raw.latency_ms + actions_raw.latency_ms
    cost = (
        input_tokens / 1_000_000 * settings.llm_input_price_per_million
        + output_tokens / 1_000_000 * settings.llm_output_price_per_million
    )

    short = summary.summary_short.strip()
    words = short.split()
    if len(words) > MAX_SHORT_SUMMARY_WORDS:
        short = " ".join(words[:MAX_SHORT_SUMMARY_WORDS]).rstrip(",;:") + "…"
        stats.notes.append("short_summary_truncated")

    topics: list[str] = []
    for topic in summary.topics:
        cleaned = topic.strip()[:60]
        if cleaned and cleaned.lower() not in {existing.lower() for existing in topics}:
            topics.append(cleaned)

    intelligence = MeetingIntelligence(
        meeting_id=meeting.id,
        transcript_id=transcript.id,
        version=version,
        is_active=True,
        status="ready",
        llm_provider=provider.name,
        llm_model=provider.model,
        prompt_version=settings.prompt_version,
        schema_version=settings.schema_version,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        latency_ms=latency_ms,
        quality_metrics={},
        summary_short=short,
        summary_detailed=summary.summary_detailed.strip(),
        topics=topics[:10],
        created_at=utcnow(),
    )
    session.add(intelligence)
    session.flush()

    for index, point in enumerate(summary.key_points):
        verified, failures = _verify_refs(point.evidence, by_id)
        stats.grounding_failures += failures
        point_row = KeyPoint(
            intelligence_id=intelligence.id,
            sequence=index,
            text=point.text.strip()[:400],
        )
        session.add(point_row)
        session.flush()
        stats.stored_key_points += 1
        if not verified:
            stats.notes.append("key_point_without_evidence")
        _add_evidence(
            session, meeting_id=meeting.id, verified=verified, key_point_id=point_row.id
        )

    for index, decision_item in enumerate(decisions.items):
        verified, failures = _verify_refs(decision_item.evidence, by_id)
        stats.grounding_failures += failures
        if not verified:
            stats.dropped_decisions += 1
            continue
        by_label, by_name = _speaker_maps(transcript)
        decision_speaker = None
        if decision_item.made_by_label:
            decision_speaker = by_label.get(
                decision_item.made_by_label.lower()
            ) or by_name.get(decision_item.made_by_label.lower())
        decision_row = Decision(
            intelligence_id=intelligence.id,
            meeting_id=meeting.id,
            sequence=index,
            text=decision_item.text.strip()[:800],
            rationale=(decision_item.rationale or "").strip() or None,
            made_by_speaker_id=decision_speaker.id if decision_speaker else None,
            confidence=decision_item.confidence,
        )
        session.add(decision_row)
        session.flush()
        stats.stored_decisions += 1
        _add_evidence(
            session, meeting_id=meeting.id, verified=verified, decision_id=decision_row.id
        )

    for index, action_item in enumerate(actions.items):
        verified, failures = _verify_refs(action_item.evidence, by_id)
        stats.grounding_failures += failures
        if not verified:
            stats.dropped_actions += 1
            continue

        resolution, speaker_id, owner_text = _resolve_owner(action_item, verified, transcript)
        due_date, due_text, precision = _resolve_due(action_item, verified)

        action_row = ActionItem(
            meeting_id=meeting.id,
            intelligence_id=intelligence.id,
            sequence=index,
            title=action_item.title.strip()[:300],
            description=(action_item.description or "").strip() or None,
            owner_speaker_id=speaker_id,
            owner_text=owner_text,
            owner_resolution=resolution,
            due_date=due_date,
            due_date_text=due_text,
            due_date_precision=precision,
            priority=action_item.priority,
            status="open",
            confidence=action_item.confidence,
            is_user_edited=False,
        )
        session.add(action_row)
        session.flush()
        stats.stored_actions += 1
        _add_evidence(
            session, meeting_id=meeting.id, verified=verified, action_item_id=action_row.id
        )

    intelligence.quality_metrics = stats.as_dict()
    meeting.intelligence_status = "ready"
    meeting.status = "ready"
    meeting.updated_at = utcnow()
    session.flush()

    logger.info(
        "intelligence_completed",
        extra={
            "extra_fields": {
                "meeting_id": meeting.id,
                "actions": stats.stored_actions,
                "decisions": stats.stored_decisions,
                "dropped": stats.dropped_actions + stats.dropped_decisions,
            }
        },
    )
    return intelligence


def load_active_transcript(session: Session, meeting_id: str) -> Transcript | None:
    return session.scalar(
        select(Transcript)
        .options(
            selectinload(Transcript.segments).selectinload(TranscriptSegment.speaker),
            selectinload(Transcript.speakers),
        )
        .where(Transcript.meeting_id == meeting_id, Transcript.is_active.is_(True))
    )


def load_active_intelligence(session: Session, meeting_id: str) -> MeetingIntelligence | None:
    return session.scalar(
        select(MeetingIntelligence)
        .options(
            selectinload(MeetingIntelligence.key_points).selectinload(KeyPoint.evidence),
            selectinload(MeetingIntelligence.decisions).selectinload(Decision.evidence),
            selectinload(MeetingIntelligence.action_items).selectinload(ActionItem.evidence),
        )
        .where(MeetingIntelligence.meeting_id == meeting_id, MeetingIntelligence.is_active.is_(True))
    )
