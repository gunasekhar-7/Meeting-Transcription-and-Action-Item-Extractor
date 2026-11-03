"""Speaker alignment.

Diarization returns speaker turns; ASR returns words. Each word is assigned to
the turn with the largest temporal overlap (ties go to the earlier turn), and
consecutive words from the same speaker form a segment. This is deliberately
simple and fully testable; its errors are visible in ``is_low_confidence``
rather than silently smoothed over.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    start_ms: int
    end_ms: int
    speaker: str


@dataclass(frozen=True)
class Word:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class AlignedSegment:
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def assign_speaker(word: Word, turns: list[Turn]) -> str | None:
    best_speaker: str | None = None
    best_overlap = 0
    for turn in turns:
        overlap = _overlap(word.start_ms, word.end_ms, turn.start_ms, turn.end_ms)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker
    return best_speaker


def split_by_speaker(words: list[Word], turns: list[Turn]) -> list[AlignedSegment]:
    segments: list[AlignedSegment] = []
    current: str | None = None
    buffer: list[str] = []
    start_ms = 0
    end_ms = 0

    def flush() -> None:
        nonlocal buffer
        if buffer:
            segments.append(
                AlignedSegment(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speaker=current,
                    text=" ".join(buffer),
                )
            )
            buffer = []

    for word in words:
        speaker = assign_speaker(word, turns)
        if not buffer:
            current = speaker
            start_ms = word.start_ms
            end_ms = word.end_ms
            buffer.append(word.text)
            continue
        if speaker != current:
            flush()
            current = speaker
            start_ms = word.start_ms
        end_ms = word.end_ms
        buffer.append(word.text)

    flush()
    return segments
