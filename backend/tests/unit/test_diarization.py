from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import PipelineError
from app.pipelines.alignment import Turn
from app.providers.diarization import (
    FakeDiarizationProvider,
    NullDiarizationProvider,
    PyannoteDiarizationProvider,
    build_diarization,
)


def test_null_diarization_provider(tmp_path: Path) -> None:
    provider = NullDiarizationProvider()
    res = provider.diarize(tmp_path / "dummy.wav")
    assert res.turns == []
    assert res.provider == "none"
    assert res.capability_notes["diarization"] == "disabled"


def test_fake_diarization_provider(tmp_path: Path) -> None:
    custom_turns = [
        Turn(start_ms=0, end_ms=1000, speaker="SPEAKER_A"),
        Turn(start_ms=1000, end_ms=2000, speaker="SPEAKER_B"),
    ]
    provider = FakeDiarizationProvider(turns=custom_turns)
    res = provider.diarize(tmp_path / "dummy.wav")
    assert len(res.turns) == 2
    assert res.turns[0].speaker == "SPEAKER_A"
    assert res.turns[1].speaker == "SPEAKER_B"
    assert res.capability_notes["diarization"] == "fake"


def test_pyannote_provider_raises_without_hf_token(tmp_path: Path, settings: Settings) -> None:
    settings.hf_token = None
    provider = PyannoteDiarizationProvider(settings)
    with pytest.raises(PipelineError) as exc:
        provider.diarize(tmp_path / "dummy.wav")
    assert exc.value.code == "diarization_not_configured"


def test_build_diarization_factory(settings: Settings) -> None:
    settings.diarization_provider = "none"
    assert isinstance(build_diarization(settings), NullDiarizationProvider)

    settings.diarization_provider = "fake"
    assert isinstance(build_diarization(settings), FakeDiarizationProvider)

    settings.diarization_provider = "pyannote"
    assert isinstance(build_diarization(settings), PyannoteDiarizationProvider)
