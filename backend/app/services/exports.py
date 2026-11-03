"""Meeting export renderers."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from app.db.models import ActionItem, Meeting, MeetingIntelligence, Transcript


def _evidence(link) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "quote": link.quote,
        "char_start": link.char_start,
        "char_end": link.char_end,
    }


def _segment_index(transcript: Transcript) -> dict[int, Any]:
    return {segment.id: segment for segment in transcript.segments}


def export_payload(
    meeting: Meeting,
    transcript: Transcript,
    intelligence: MeetingIntelligence,
) -> dict[str, Any]:
    segments = _segment_index(transcript)
    speakers = {speaker.id: speaker for speaker in transcript.speakers}
    asset = meeting.audio_asset

    def evidence(links) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        output = []
        for link in links:
            segment = segments.get(link.transcript_segment_id)
            if segment is None:
                continue
            output.append(
                {
                    "segment_id": segment.id,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    **_evidence(link),
                }
            )
        return output

    return {
        "schema_version": intelligence.schema_version,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "meeting": {
            "id": meeting.id,
            "title": meeting.title,
            "description": meeting.description,
            "meeting_date": meeting.meeting_date.isoformat() if meeting.meeting_date else None,
            "duration_seconds": meeting.duration_seconds,
            "language": meeting.language,
        },
        "audio": (
            {
                "original_filename": asset.original_filename,
                "size_bytes": asset.size_bytes,
                "codec": asset.codec,
                "sample_rate": asset.sample_rate,
                "channels": asset.channels,
                "sha256": asset.sha256,
                "purged": asset.purged_at is not None,
            }
            if asset
            else None
        ),
        "transcript": {
            "asr": {"provider": transcript.asr_provider, "model": transcript.asr_model},
            "real_time_factor": transcript.real_time_factor,
            "capability_notes": transcript.capability_notes,
            "speakers": [
                {
                    "id": speaker.id,
                    "label": speaker.label,
                    "display_name": speaker.display_name,
                }
                for speaker in transcript.speakers
            ],
            "segments": [
                {
                    "id": segment.id,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "speaker_label": speakers[segment.speaker_id].label
                    if segment.speaker_id and segment.speaker_id in speakers
                    else None,
                    "text": segment.text,
                }
                for segment in transcript.segments
            ],
        },
        "intelligence": {
            "llm_model": intelligence.llm_model,
            "prompt_version": intelligence.prompt_version,
            "summary_short": intelligence.summary_short,
            "summary_detailed": intelligence.summary_detailed,
            "topics": list(intelligence.topics or []),
            "key_points": [
                {"text": point.text, "evidence": evidence(point.evidence)}
                for point in intelligence.key_points
            ],
            "decisions": [
                {
                    "text": item.text,
                    "rationale": item.rationale,
                    "made_by_speaker_label": (
                        speakers[item.made_by_speaker_id].label
                        if item.made_by_speaker_id and item.made_by_speaker_id in speakers
                        else None
                    ),
                    "confidence": item.confidence,
                    "evidence": evidence(item.evidence),
                }
                for item in intelligence.decisions
            ],
            "action_items": [
                {
                    "title": item.title,
                    "description": item.description,
                    "owner_label": (
                        speakers[item.owner_speaker_id].label
                        if item.owner_speaker_id and item.owner_speaker_id in speakers
                        else None
                    ),
                    "owner_resolution": item.owner_resolution,
                    "owner_text": item.owner_text,
                    "due_date": item.due_date.isoformat() if item.due_date else None,
                    "due_date_text": item.due_date_text,
                    "due_date_precision": item.due_date_precision,
                    "priority": item.priority,
                    "status": item.status,
                    "confidence": item.confidence,
                    "evidence": evidence(item.evidence),
                }
                for item in intelligence.action_items
            ],
        },
        "quality": intelligence.quality_metrics or {},
    }


def _timestamp_ms(value: int, *, srt: bool) -> str:
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    separator = "," if srt else "."
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def render_subtitles(transcript: Transcript, *, vtt: bool) -> str:
    lines: list[str] = ["WEBVTT", ""] if vtt else []
    speakers = {speaker.id: speaker for speaker in transcript.speakers}
    for index, segment in enumerate(transcript.segments, start=1):
        speaker = speakers.get(segment.speaker_id) if segment.speaker_id else None
        prefix = f"{speaker.display_name or speaker.label}: " if speaker else ""
        if not vtt:
            lines.append(str(index))
        lines.append(
            f"{_timestamp_ms(segment.start_ms, srt=not vtt)} --> "
            f"{_timestamp_ms(segment.end_ms, srt=not vtt)}"
        )
        lines.append(prefix + segment.text)
        lines.append("")
    return "\n".join(lines)


def render_text(transcript: Transcript) -> str:
    speakers = {speaker.id: speaker for speaker in transcript.speakers}
    lines = []
    for segment in transcript.segments:
        speaker = speakers.get(segment.speaker_id) if segment.speaker_id else None
        prefix = f"{speaker.display_name or speaker.label}: " if speaker else ""
        seconds = segment.start_ms // 1000
        lines.append(f"[{seconds // 60:02d}:{seconds % 60:02d}] {prefix}{segment.text}")
    return "\n".join(lines)


def render_markdown(
    meeting: Meeting,
    transcript: Transcript,
    intelligence: MeetingIntelligence,
) -> str:
    payload = export_payload(meeting, transcript, intelligence)
    speakers = {speaker.id: speaker for speaker in transcript.speakers}
    lines = [
        f"# {meeting.title}",
        "",
        f"- Date: {payload['meeting']['meeting_date'] or 'not supplied'}",
        f"- Duration: {payload['meeting']['duration_seconds'] or 'unknown'} seconds",
        f"- Language: {meeting.language or 'unknown'}",
        f"- Model: {intelligence.llm_model} (prompt {intelligence.prompt_version})",
        "",
        "## Summary",
        "",
        intelligence.summary_short or "_No summary._",
        "",
        intelligence.summary_detailed or "",
        "",
        "## Topics",
        "",
        ", ".join(intelligence.topics or []) or "_None._",
        "",
        "## Decisions",
        "",
    ]
    if not intelligence.decisions:
        lines.append("_No decisions were extracted._")
    for decision in intelligence.decisions:
        lines.append(f"- **{decision.text}**")
        if decision.rationale:
            lines.append(f"  - Rationale: {decision.rationale}")
        for link in decision.evidence:
            lines.append(f'  - Evidence: "{link.quote}"')

    lines.extend(["", "## Action items", ""])
    if not intelligence.action_items:
        lines.append("_No action items were extracted._")
    for action in intelligence.action_items:
        owner = (
            speakers[action.owner_speaker_id].display_name
            or speakers[action.owner_speaker_id].label
            if action.owner_speaker_id and action.owner_speaker_id in speakers
            else "unassigned"
        )
        due = action.due_date.isoformat() if action.due_date else (action.due_date_text or "no date")
        lines.append(
            f"- [ ] **{action.title}** — owner: {owner}; due: {due}; priority: {action.priority}"
        )
        for link in action.evidence:
            lines.append(f'  - Evidence: "{link.quote}"')

    lines.extend(["", "## Transcript", ""])
    for segment in transcript.segments:
        speaker = speakers.get(segment.speaker_id) if segment.speaker_id else None
        prefix = f"**{speaker.display_name or speaker.label}:** " if speaker else ""
        seconds = segment.start_ms // 1000
        lines.append(f"`{seconds // 60:02d}:{seconds % 60:02d}` {prefix}{segment.text}")
        lines.append("")
    return "\n".join(lines)


def action_items_csv(items: list[ActionItem]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "meeting",
            "title",
            "owner",
            "owner_resolution",
            "due_date",
            "due_date_text",
            "due_date_precision",
            "priority",
            "status",
            "evidence_quote",
        ]
    )
    for item in items:
        owner = ""
        if item.owner:
            owner = item.owner.display_name or item.owner.label
        writer.writerow(
            [
                item.meeting.title,
                item.title,
                owner,
                item.owner_resolution,
                item.due_date.isoformat() if item.due_date else "",
                item.due_date_text or "",
                item.due_date_precision,
                item.priority,
                item.status,
                item.evidence[0].quote if item.evidence else "",
            ]
        )
    return buffer.getvalue()
