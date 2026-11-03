#!/usr/bin/env python3
"""Smoke measurement of the real faster-whisper adapter.

Uses a single synthetic text-to-speech clip. This measures adapter behaviour,
model load, latency and a rough WER on clean synthetic speech. It is explicitly
not a meeting-audio benchmark.
"""

from __future__ import annotations

import json
import re
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.core.config import Settings  # noqa: E402
from app.providers.asr import FasterWhisperASR  # noqa: E402

AUDIO = ROOT / "fixtures" / "audio" / "smoke.wav"
REPORT = ROOT / "reports" / "asr_smoke.json"
REFERENCE = (
    "Good morning. We agreed to move the launch to the twentieth of November. "
    "Ada, can you prepare the migration checklist before Friday?"
)


def normalize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    return cleaned.split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    expected = normalize(reference)
    actual = normalize(hypothesis)
    rows = len(expected) + 1
    cols = len(actual) + 1
    previous = list(range(cols))
    for i in range(1, rows):
        current = [i] + [0] * (cols - 1)
        for j in range(1, cols):
            cost = 0 if expected[i - 1] == actual[j - 1] else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
        previous = current
    return round(previous[-1] / max(1, len(expected)), 4)


def main() -> int:
    if not AUDIO.exists():
        print(f"Missing audio fixture: {AUDIO}", file=sys.stderr)
        return 1

    with wave.open(str(AUDIO), "rb") as handle:
        duration = handle.getnframes() / float(handle.getframerate())

    settings = Settings(
        env="local",
        asr_provider="faster_whisper",
        asr_model="tiny",
        asr_compute_type="int8",
        asr_beam_size=5,
        database_url="sqlite://",
        local_storage_path=str(ROOT / "data" / "tmp-audio"),
    )
    provider = FasterWhisperASR(settings)
    result = provider.transcribe(AUDIO)

    hypothesis = " ".join(segment.text for segment in result.segments)
    reference_wer = word_error_rate(REFERENCE, hypothesis)
    audio_seconds = result.duration_seconds or duration
    rtf = round(result.processing_seconds / audio_seconds, 4) if audio_seconds else None

    report = {
        "report": "asr-smoke",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.asr_model,
        "compute_type": settings.asr_compute_type,
        "provider": result.provider,
        "audio": "single synthetic Windows SAPI TTS clip",
        "audio_seconds": round(audio_seconds, 3),
        "processing_seconds": result.processing_seconds,
        "real_time_factor": rtf,
        "word_error_rate": reference_wer,
        "reference": REFERENCE,
        "hypothesis": hypothesis,
        "segment_count": len(result.segments),
        "caveats": [
            "One synthetic, single-speaker, clean TTS clip.",
            "tiny int8 is the smallest Whisper model, not the production default.",
            "This is not a meeting-audio WER benchmark and has no confidence interval.",
            "Model download time is excluded from processing_seconds.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"audio_seconds={audio_seconds:.2f} processing_seconds={result.processing_seconds:.2f}")
    print(f"real_time_factor={rtf} wer={reference_wer}")
    print(f"segments={len(result.segments)}")
    print(f"transcript: {hypothesis}")
    print(f"report: {REPORT.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
