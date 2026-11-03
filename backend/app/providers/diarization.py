"""Speaker diarization providers.

Diarization is an optional capability (see ADR-0003). It returns speaker turns,
which the alignment pipeline merges with word/segment timestamps to label who spoke.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Protocol

from app.core.config import Settings
from app.core.errors import PipelineError
from app.pipelines.alignment import Turn

logger = logging.getLogger(__name__)


@dataclass
class DiarizationResult:
    turns: list[Turn]
    provider: str
    model: str
    processing_seconds: float
    capability_notes: dict[str, str] = field(default_factory=dict)


class DiarizationProvider(Protocol):
    name: str
    model: str

    def diarize(self, path: Path) -> DiarizationResult: ...


class NullDiarizationProvider:
    """Default provider when diarization is disabled."""

    name = "none"
    model = "none"

    def diarize(self, path: Path) -> DiarizationResult:
        return DiarizationResult(
            turns=[],
            provider=self.name,
            model=self.model,
            processing_seconds=0.0,
            capability_notes={"diarization": "disabled"},
        )


FAKE_TURNS = [
    Turn(start_ms=0, end_ms=5200, speaker="SPEAKER_00"),
    Turn(start_ms=5200, end_ms=9600, speaker="SPEAKER_01"),
    Turn(start_ms=9600, end_ms=14000, speaker="SPEAKER_00"),
]


class FakeDiarizationProvider:
    """Deterministic provider for tests, local development, and offline demos."""

    name = "fake"
    model = "canned-turns-v1"

    def __init__(self, turns: list[Turn] | None = None) -> None:
        self.turns = turns or FAKE_TURNS

    def diarize(self, path: Path) -> DiarizationResult:
        return DiarizationResult(
            turns=list(self.turns),
            provider=self.name,
            model=self.model,
            processing_seconds=0.001,
            capability_notes={"diarization": "fake", "note": "Deterministic speaker turns"},
        )


_PIPELINE_CACHE: dict[str, object] = {}


class PyannoteDiarizationProvider:
    """Self-hosted diarization via pyannote.audio."""

    name = "pyannote"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model = settings.diarization_model

    def _load_pipeline(self) -> object:
        if not self.settings.hf_token:
            raise PipelineError(
                "diarization_not_configured",
                "HF_TOKEN is required to load pyannote diarization models",
            )
        cache_key = self.settings.diarization_model
        if cache_key not in _PIPELINE_CACHE:
            try:
                from pyannote.audio import Pipeline
            except ImportError as exc:
                raise PipelineError(
                    "diarization_not_installed",
                    "pyannote.audio is not installed. Install the 'diarization' extra or set DIARIZATION_PROVIDER=none.",
                ) from exc

            logger.info("loading_diarization_pipeline", extra={"extra_fields": {"model": self.model}})
            _PIPELINE_CACHE[cache_key] = Pipeline.from_pretrained(
                self.model,
                use_auth_token=self.settings.hf_token,
            )
        return _PIPELINE_CACHE[cache_key]

    def diarize(self, path: Path) -> DiarizationResult:
        pipeline = self._load_pipeline()
        started = perf_counter()
        turns: list[Turn] = []
        try:
            # pyannote pipeline accepts file path
            annotation = pipeline(str(path))  # type: ignore[operator]
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                turns.append(
                    Turn(
                        start_ms=max(0, int(turn.start * 1000)),
                        end_ms=max(1, int(turn.end * 1000)),
                        speaker=str(speaker),
                    )
                )
        except Exception as exc:
            logger.exception("diarization_failed")
            raise PipelineError(
                "diarization_failed", "Diarization processing failed for this audio"
            ) from exc

        elapsed = perf_counter() - started
        return DiarizationResult(
            turns=turns,
            provider=self.name,
            model=self.model,
            processing_seconds=round(elapsed, 3),
            capability_notes={
                "diarization": "pyannote",
                "turns_count": str(len(turns)),
                "model": self.model,
            },
        )


def build_diarization(settings: Settings) -> DiarizationProvider:
    if settings.diarization_provider == "fake":
        return FakeDiarizationProvider()
    if settings.diarization_provider == "pyannote":
        return PyannoteDiarizationProvider(settings)
    return NullDiarizationProvider()
