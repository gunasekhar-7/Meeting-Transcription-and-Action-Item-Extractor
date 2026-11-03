"""Automatic speech recognition providers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Protocol

from app.core.config import Settings
from app.core.errors import PipelineError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ASRSegment:
    start_ms: int
    end_ms: int
    text: str
    speaker_label: str | None = None


@dataclass
class ASRResult:
    segments: list[ASRSegment]
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    provider: str
    model: str
    processing_seconds: float
    capability_notes: dict[str, str] = field(default_factory=dict)


class ASRProvider(Protocol):
    name: str
    model: str

    def transcribe(self, path: Path) -> ASRResult: ...


FAKE_SEGMENTS = [
    ASRSegment(
        start_ms=0,
        end_ms=5200,
        text=(
            "Good morning. We reviewed the launch plan and agreed to move the release "
            "to the fourteenth of November."
        ),
        speaker_label="SPEAKER_00",
    ),
    ASRSegment(
        start_ms=5200,
        end_ms=9600,
        text="Ada, can you take the billing migration before then?",
        speaker_label="SPEAKER_01",
    ),
    ASRSegment(
        start_ms=9600,
        end_ms=13200,
        text="Yes, I will update the pricing deck by Friday.",
        speaker_label="SPEAKER_00",
    ),
]


class FakeASRProvider:
    """Deterministic provider for tests and offline demos.

    It ignores the audio and returns a fixed transcript. The UI surfaces the
    `fake` capability note so nobody mistakes this for real transcription.
    """

    name = "fake"
    model = "canned-transcript-v1"

    def __init__(self, segments: list[ASRSegment] | None = None) -> None:
        self.segments = segments or FAKE_SEGMENTS

    def transcribe(self, path: Path) -> ASRResult:
        return ASRResult(
            segments=list(self.segments),
            language="en",
            language_probability=1.0,
            duration_seconds=max(segment.end_ms for segment in self.segments) / 1000,
            provider=self.name,
            model=self.model,
            processing_seconds=0.001,
            capability_notes={"asr": "fake", "note": "Deterministic canned transcript"},
        )


_MODEL_CACHE: dict[tuple[str, str], object] = {}


class FasterWhisperASR:
    name = "faster_whisper"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.asr_model

    def _load(self) -> object:
        key = (self.settings.asr_model, self.settings.asr_compute_type)
        if key not in _MODEL_CACHE:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise PipelineError(
                    "asr_not_installed",
                    "faster-whisper is not installed. Install the 'asr' extra or set ASR_PROVIDER=fake.",
                ) from exc
            logger.info(
                "loading_asr_model",
                extra={"extra_fields": {"model": self.settings.asr_model}},
            )
            _MODEL_CACHE[key] = WhisperModel(
                self.settings.asr_model,
                device="cpu",
                compute_type=self.settings.asr_compute_type,
            )
        return _MODEL_CACHE[key]

    def transcribe(self, path: Path) -> ASRResult:
        model = self._load()
        started = perf_counter()
        try:
            raw_segments, info = model.transcribe(  # type: ignore[attr-defined]
                str(path),
                beam_size=self.settings.asr_beam_size,
                vad_filter=True,
                word_timestamps=False,
            )
            segments = []
            for item in raw_segments:
                text = (item.text or "").strip()
                if not text:
                    continue
                start_ms = max(0, int(item.start * 1000))
                end_ms = max(start_ms + 1, int(item.end * 1000))
                segments.append(ASRSegment(start_ms=start_ms, end_ms=end_ms, text=text))
        except Exception as exc:
            logger.exception("asr_failed")
            raise PipelineError("asr_failed", "Transcription failed for this recording") from exc

        elapsed = perf_counter() - started
        if not segments:
            raise PipelineError(
                "empty_transcript", "No speech was detected in this recording"
            )

        return ASRResult(
            segments=segments,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", None),
            provider=self.name,
            model=self.settings.asr_model,
            processing_seconds=round(elapsed, 3),
            capability_notes={
                "diarization": "disabled",
                "note": "Speaker attribution requires a diarization provider",
            },
        )


def build_asr(settings: Settings) -> ASRProvider:
    if settings.asr_provider == "faster_whisper":
        return FasterWhisperASR(settings)
    return FakeASRProvider()
