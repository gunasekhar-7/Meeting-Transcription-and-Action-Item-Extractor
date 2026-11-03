# ADR-0002: faster-whisper as the default ASR engine, behind a provider port

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

Requirements: accurate timestamped transcription, word-level timestamps for speaker alignment and evidence offsets, language detection, CPU-only deployment, no per-minute cost for development, and no vendor lock-in.

Candidate engines: `openai-whisper` (reference implementation), `faster-whisper` (CTranslate2), WhisperX, and hosted APIs (AssemblyAI, Deepgram, Groq, OpenAI).

Verified facts (2026-11-02): `faster-whisper 1.2.1` is the current PyPI release; it decodes via PyAV (no system FFmpeg needed), bundles Silero VAD, supports `word_timestamps=True`, and runs Whisper weights under MIT. On 8 threads, the project's own benchmark shows `small` int8 processing 13 minutes of audio in 1m42s; extrapolated to 4 vCPU, RTF ≈ 0.2–0.35. No authoritative 4-vCPU benchmark exists — Stage 2 must measure it.

## Decision

Use `faster-whisper` as the default `ASRProvider` implementation, with model, device and compute type configurable. Define `ASRPort` so a hosted provider can be selected without touching services. Default model: `small` with `compute_type=int8`; `base` and `tiny` supported for tests; `distil-large-v3` documented as the accuracy option when CPU budget permits.

Do **not** adopt WhisperX as a dependency. Its main added value is wav2vec2 forced alignment, which is a worthwhile future upgrade but pulls additional model downloads and fragile CUDA/torch alignment dependencies into the default path. Our alignment step uses Whisper's word timestamps plus diarization turns, which is adequate for evidence spans and far easier to test.

## Consequences

**Positive**

- Zero marginal cost locally; the pipeline can be developed and tested without an API key.
- Word timestamps enable both speaker splitting and character-offset evidence.
- MIT licensing is unambiguous for a public portfolio.
- Provider port allows a hosted upgrade when CPU throughput is the bottleneck.

**Negative**

- `large-v3` is not real-time on CPU; the product's accuracy ceiling is limited by the CPU budget.
- English is strongest; other languages inherit Whisper's quality without a measured claim.
- Whisper's word timestamps are DTW-derived and less precise than forced alignment (seconds-level error is possible at segment boundaries).

**Mitigations**

- Stage 2 measures RTF for each model on the reference hardware and records it on every transcript.
- Stage 8 measures WER per model, so the accuracy/throughput trade-off is a published table rather than a guess.
- Evidence verification tolerates approximate timestamps because it matches quote text within a segment, not absolute time.

## Alternatives considered

- **`openai-whisper`.** Rejected: slower CPU path, requires system FFmpeg, no built-in batching or VAD.
- **WhisperX.** Rejected for v1 as a default dependency; documented as an optional alignment upgrade.
- **Hosted-only (AssemblyAI/Deepgram).** Rejected: violates the "works without external services" requirement, adds per-minute cost to every test run, and makes the portfolio demo depend on a funded account. Retained as an adapter.
- **Cloud Speech-to-Text (Google/AWS).** Similar lock-in and cost objections, plus weaker word-level speaker alignment out of the box.
