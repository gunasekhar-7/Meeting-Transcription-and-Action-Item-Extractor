# ADR-0003: Diarization is an optional capability, never a hard dependency

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

Speaker attribution is required for action-item ownership. Candidates: `pyannote.audio` (self-hosted), hosted diarization (AssemblyAI, Deepgram, pyannote.ai), NVIDIA NeMo/Sortformer, and sherpa-onnx.

Verified facts: `pyannote.audio 4.0.7` is current; the recommended pipeline is `speaker-diarization-community-1` (powerset segmentation + WeSpeaker embeddings + VBx), with CC BY 4.0 weights gated behind Hugging Face terms acceptance. Version 4 requires FFmpeg (torchcodec). Published speed is GPU-only; community CPU measurements suggest RTF ≈ 0.6–1.2, making it comparable to or slower than ASR itself on CPU.

## Decision

Diarization is an **opt-in extra**:

- `DiarizationPort` with `NullDiarizationProvider` as the default, plus `PyannoteProvider` and a hosted adapter later if needed.
- `DIARIZATION_PROVIDER=none|pyannote|hosted`; `pyannote` requires `HF_TOKEN` and fails with a typed `diarization_not_configured` note rather than blocking transcription.
- The default Docker worker image excludes torch; a separate `worker:diarization` image tag includes it.
- The UI explains the absence of speakers through `capability_notes` and `/meta`, rather than silently showing a single unnamed speaker.

## Consequences

**Positive**

- Default install is small, fast, and licence-unencumbered.
- A gated model or failed download cannot take down the product's core path.
- Evaluation can run ASR-only configurations cheaply, which is exactly what the ASR metrics need.
- The trade-off (no speakers) is visible and explainable, not hidden.

**Negative**

- The default demo has no speaker labels, which weakens the ownership story.
- Two worker image variants complicate CI slightly.
- Users who enable diarization get a slower pipeline (near real-time CPU) with no warning beyond documentation.

**Mitigations**

- The demo profile enables diarization on the worker (with the HF token) and publishes measured DER, showing the capability honestly.
- `/meetings/{id}/status` reports the active capabilities so the UI can explain why labels are missing.
- Stage 8 reports both configurations (with and without diarization) so ownership accuracy is not conflated with diarization availability.

## Alternatives considered

- **Mandatory pyannote.** Rejected: 2 GB dependency, gated weights, and a near-real-time CPU cost imposed on every user for a feature that may be disabled.
- **Hosted diarization only.** Rejected: cost and external dependency; retained as an adapter option.
- **NeMo Sortformer.** Rejected: 4-speaker hard limit and research-workflow ergonomics.
- **No diarization at all.** Rejected: ownership is central to the product; the capability must exist, just not be mandatory.
