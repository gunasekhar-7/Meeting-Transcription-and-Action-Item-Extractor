"""ORM-to-schema mapping. Kept out of routers so routes stay thin."""

from __future__ import annotations

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
from app.schemas.api import (
    ActionItemListItem,
    ActionItemOut,
    AudioOut,
    DecisionOut,
    EvidenceOut,
    IntelligenceOut,
    KeyPointOut,
    MeetingOut,
    SegmentOut,
    SpeakerOut,
    TranscriptOut,
)


def _evidence(links: list[EvidenceLink], segments: dict[int, TranscriptSegment]) -> list[EvidenceOut]:
    output: list[EvidenceOut] = []
    for link in links:
        segment = segments.get(link.transcript_segment_id)
        if segment is None:
            continue
        output.append(
            EvidenceOut(
                segment_id=segment.id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                quote=link.quote,
                char_start=link.char_start,
                char_end=link.char_end,
            )
        )
    return output


def meeting_out(meeting: Meeting) -> MeetingOut:
    asset = meeting.audio_asset
    active = next((item for item in meeting.transcripts if item.is_active), None)
    return MeetingOut(
        id=meeting.id,
        title=meeting.title,
        description=meeting.description,
        meeting_date=meeting.meeting_date,
        status=meeting.status,
        intelligence_status=meeting.intelligence_status,
        language=meeting.language,
        duration_seconds=meeting.duration_seconds,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
        audio=(
            AudioOut(
                original_filename=asset.original_filename,
                size_bytes=asset.size_bytes,
                codec=asset.codec,
                duration_seconds=asset.duration_seconds,
                sample_rate=asset.sample_rate,
                channels=asset.channels,
                sha256=asset.sha256,
                purged=asset.purged_at is not None,
            )
            if asset
            else None
        ),
        action_item_count=len(meeting.action_items),
        open_action_item_count=sum(
            1 for item in meeting.action_items if item.status not in {"done", "cancelled"}
        ),
        speaker_count=len(active.speakers) if active else 0,
    )


def speaker_out(speaker: Speaker) -> SpeakerOut:
    return SpeakerOut(
        id=speaker.id,
        label=speaker.label,
        display_name=speaker.display_name,
        total_speaking_seconds=speaker.total_speaking_seconds,
        segment_count=speaker.segment_count,
    )


def segment_out(segment: TranscriptSegment, speakers: dict[str, Speaker]) -> SegmentOut:
    speaker = speakers.get(segment.speaker_id) if segment.speaker_id else None
    return SegmentOut(
        id=segment.id,
        sequence=segment.sequence,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        speaker_id=segment.speaker_id,
        speaker_label=speaker.label if speaker else None,
        text=segment.text,
        is_low_confidence=segment.is_low_confidence,
    )


def transcript_out(
    transcript: Transcript, *, offset: int, limit: int
) -> TranscriptOut:
    speakers = {speaker.id: speaker for speaker in transcript.speakers}
    segments = transcript.segments[offset : offset + limit]
    return TranscriptOut(
        transcript_id=transcript.id,
        version=transcript.version,
        meeting_id=transcript.meeting_id,
        language=transcript.language,
        language_probability=transcript.language_probability,
        duration_seconds=transcript.audio_duration_seconds,
        real_time_factor=transcript.real_time_factor,
        asr={
            "provider": transcript.asr_provider,
            "model": transcript.asr_model,
        },
        capability_notes=transcript.capability_notes or {},
        speakers=[speaker_out(item) for item in transcript.speakers],
        segments=[segment_out(item, speakers) for item in segments],
        offset=offset,
        limit=limit,
        total=len(transcript.segments),
    )


def action_item_out(
    item: ActionItem, segments: dict[int, TranscriptSegment]
) -> ActionItemOut:
    owner = item.owner
    return ActionItemOut(
        id=item.id,
        meeting_id=item.meeting_id,
        sequence=item.sequence,
        title=item.title,
        description=item.description,
        owner_speaker_id=item.owner_speaker_id,
        owner_label=owner.label if owner else None,
        owner_display_name=owner.display_name if owner else None,
        owner_resolution=item.owner_resolution,
        owner_text=item.owner_text,
        due_date=item.due_date,
        due_date_text=item.due_date_text,
        due_date_precision=item.due_date_precision,
        priority=item.priority,
        status=item.status,
        confidence=item.confidence,
        is_user_edited=item.is_user_edited,
        evidence=_evidence(item.evidence, segments),
    )


def action_list_item(item: ActionItem) -> ActionItemListItem:
    owner = item.owner
    return ActionItemListItem(
        id=item.id,
        meeting_id=item.meeting_id,
        meeting_title=item.meeting.title,
        title=item.title,
        owner_speaker_id=item.owner_speaker_id,
        owner_display_name=(owner.display_name or owner.label) if owner else None,
        owner_resolution=item.owner_resolution,
        due_date=item.due_date,
        due_date_precision=item.due_date_precision,
        priority=item.priority,
        status=item.status,
        is_user_edited=item.is_user_edited,
        evidence_count=len(item.evidence),
    )


def decision_out(
    item: Decision,
    segments: dict[int, TranscriptSegment],
    speakers: dict[str, Speaker] | None = None,
) -> DecisionOut:
    speaker = (
        speakers.get(item.made_by_speaker_id)
        if speakers and item.made_by_speaker_id
        else None
    )
    return DecisionOut(
        id=item.id,
        sequence=item.sequence,
        text=item.text,
        rationale=item.rationale,
        made_by_speaker_id=item.made_by_speaker_id,
        made_by_speaker_label=speaker.label if speaker else None,
        confidence=item.confidence,
        evidence=_evidence(item.evidence, segments),
    )


def intelligence_out(
    intelligence: MeetingIntelligence, transcript: Transcript
) -> IntelligenceOut:
    segments = {segment.id: segment for segment in transcript.segments}
    speakers = {speaker.id: speaker for speaker in transcript.speakers}

    decisions = []
    for item in intelligence.decisions:
        speaker = speakers.get(item.made_by_speaker_id) if item.made_by_speaker_id else None
        decisions.append(
            DecisionOut(
                id=item.id,
                sequence=item.sequence,
                text=item.text,
                rationale=item.rationale,
                made_by_speaker_id=item.made_by_speaker_id,
                made_by_speaker_label=speaker.label if speaker else None,
                confidence=item.confidence,
                evidence=_evidence(item.evidence, segments),
            )
        )

    return IntelligenceOut(
        intelligence_id=intelligence.id,
        meeting_id=intelligence.meeting_id,
        transcript_id=intelligence.transcript_id,
        version=intelligence.version,
        status=intelligence.status,
        llm={
            "provider": intelligence.llm_provider,
            "model": intelligence.llm_model,
            "prompt_version": intelligence.prompt_version,
            "schema_version": intelligence.schema_version,
        },
        usage={
            "input_tokens": intelligence.input_tokens,
            "output_tokens": intelligence.output_tokens,
            "cost_usd": intelligence.cost_usd,
            "latency_ms": intelligence.latency_ms,
        },
        quality=intelligence.quality_metrics or {},
        summary_short=intelligence.summary_short,
        summary_detailed=intelligence.summary_detailed,
        topics=list(intelligence.topics or []),
        key_points=[
            KeyPointOut(
                id=point.id,
                sequence=point.sequence,
                text=point.text,
                evidence=_evidence(point.evidence, segments),
            )
            for point in intelligence.key_points
        ],
        decisions=decisions,
        action_items=[action_item_out(item, segments) for item in intelligence.action_items],
    )


def key_point_out(point: KeyPoint, segments: dict[int, TranscriptSegment]) -> KeyPointOut:
    return KeyPointOut(
        id=point.id,
        sequence=point.sequence,
        text=point.text,
        evidence=_evidence(point.evidence, segments),
    )
