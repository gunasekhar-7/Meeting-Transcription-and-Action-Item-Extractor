# Product Requirements Document

**Project:** Meeting Transcription & Action-Item Intelligence Platform
**Version:** 1.0 (Stage 0 baseline)
**Status:** Approved for implementation
**Date:** 2026-11-02

---

## 1. Problem statement

A one-hour meeting produces roughly 8,000–9,000 spoken words. Attendees leave with an unreliable memory of what was decided, who committed to what, and by when. Existing tools fail in three distinct ways:

1. **Transcription-only tools** produce an accurate wall of text with no structure. Retrieval is manual; accountability is zero.
2. **Summarisation-first tools** produce fluent prose that cannot be audited. When a summary says "Priya will migrate the billing service by Friday" and the transcript never named Priya, the summary has manufactured a commitment.
3. **Task extractors** optimise for a full-looking task list. Empty fields are filled with plausible defaults, so every failure looks like success.

The gap is not transcription quality. It is **traceability and calibrated ignorance**: a system that produces structured commitments *and* proves where each one came from, while being explicit about what it could not determine.

## 2. Goals and non-goals

### Goals

| ID | Goal | Measured by |
|---|---|---|
| G1 | Turn a recording into a timestamped, speaker-attributed transcript | Segments with start/end ms; WER vs reference |
| G2 | Produce a summary a participant would accept as faithful | Factual-consistency review; coverage of key points |
| G3 | Extract decisions and action items that are grounded in the transcript | Evidence-grounding rate; extraction F1 |
| G4 | Never invent an owner, deadline, decision, or commitment | Fabrication rate on negative cases (target: 0 resolved-but-unsupported owners) |
| G5 | Let a human review, correct, and export the result | Editable action items; JSON/Markdown/SRT/CSV export |
| G6 | Be operable: observable, retryable, recoverable, cost-aware | Job success rate, p95 latency, per-meeting cost |
| G7 | Demonstrate measurable AI quality | Reproducible Stage 8 report with committed artifacts |

### Non-goals (explicitly out of scope for v1)

- Live/streaming transcription during a call. Batch upload only.
- Video understanding, screen-share OCR, or slide extraction.
- Calendar/CRM/Slack integrations and automatic task sync.
- Multi-tenant organisations, SSO/SAML, billing, or subscription management.
- Mobile applications.
- Real-time collaborative editing of transcripts.
- Fine-tuning ASR or LLM models.
- Semantic/vector search. v1 uses PostgreSQL full-text and trigram search; embeddings are a documented future step, not a hidden dependency.
- Speaker identity across meetings (voiceprint recognition). Speaker labels are per-meeting and renamed by the user.

These are excluded deliberately. Each would add surface area without strengthening the claim the project is making: *measured, grounded extraction*.

## 3. Personas

**P1 — Meeting owner (primary).** Runs a weekly project sync. Records it, uploads it, wants a task list they can paste into their tracker within minutes. Cares about: did it catch the deadline we actually agreed, and did it attribute the task to the right person?

**P2 — Team lead / reviewer (secondary).** Reviews action items from several meetings. Cares about: what is overdue, who owns it, and can I trust it without re-reading the transcript?

**P3 — Technical evaluator (portfolio reader).** Reads the repository, runs the tests, reads the benchmark report, and tries one end-to-end upload. Cares about: is the architecture real, are the numbers measured, and does the code respect failure modes?

P3 is a first-class persona here: the repository *is* a deliverable. That justifies investing in documentation, evaluation, and CI that a normal internal tool would defer.

## 4. Functional requirements

Each requirement has an ID, a stage, and acceptance criteria. "MUST" is a hard gate for the stage exit; "SHOULD" may be deferred with a documented reason.

### 4.1 Ingestion

| ID | Requirement | Stage |
|---|---|---|
| FR-01 | The system MUST accept multipart audio uploads in WAV, MP3, M4A, FLAC, OGG and WebM containers. | 2 |
| FR-02 | The system MUST reject uploads larger than `MAX_UPLOAD_MB` (default 200) with `413`, and audio longer than `MAX_AUDIO_MINUTES` (default 180) with `422`, without persisting the file. | 2 |
| FR-03 | The system MUST validate the actual container/codec via `ffprobe`; filename extensions and client-supplied `Content-Type` MUST NOT be trusted. | 2 |
| FR-04 | The system MUST compute a SHA-256 digest while streaming to a temporary file and MUST dedupe per user: re-uploading identical bytes returns `409` with the existing meeting ID. | 2 |
| FR-05 | The system MUST store the original file in object storage under a non-guessable key and MUST NOT route audio through the API process on download. | 2 |
| FR-06 | The system MUST extract and persist duration, sample rate, channel count, codec and size before enqueuing processing. | 2 |

### 4.2 Transcription and diarization

| ID | Requirement | Stage |
|---|---|---|
| FR-07 | Transcription MUST produce ordered segments with `start_ms`, `end_ms`, text, and word-level timestamps. | 2 |
| FR-08 | The system MUST attempt language detection and persist the detected language and its confidence. | 2 |
| FR-09 | When diarization is enabled and available, segments MUST be attributed to speakers, and a segment spanning a speaker change MUST be split at the word boundary. | 2 |
| FR-10 | When diarization is disabled, unavailable, or fails, transcription MUST still complete, with `speaker_id = NULL` and a recorded capability note. This is graceful degradation, not silent success. | 2 |
| FR-11 | Transcript runs MUST be versioned and record ASR provider, model, model revision, compute type, language, duration, processing time and real-time factor. | 2 |
| FR-12 | A failed transcription MUST NOT leave a partially written transcript visible to readers. | 2 |

### 4.3 Meeting intelligence

| ID | Requirement | Stage |
|---|---|---|
| FR-13 | The system MUST generate a short summary (≤ 80 words) and a detailed summary. | 3 |
| FR-14 | The system MUST extract key discussion points and topic tags. | 3 |
| FR-15 | The system MUST extract decisions, each with the decision text, optional rationale, optional attributing speaker, and transcript evidence. | 3 |
| FR-16 | The system MUST extract action items with title, description, owner resolution, due date resolution, priority, status, and transcript evidence. | 3 |
| FR-17 | Owner resolution MUST be one of `matched_speaker` (a diarized speaker was identified), `unresolved_mention` (a name was said but cannot be mapped to a speaker), or `unassigned`. A name MUST NOT be presented as an owner unless it appears in the evidence quote. | 3 |
| FR-18 | Due dates MUST store the verbatim phrase, a precision (`day`/`week`/`month`/`quarter`/`unknown`), and an optional resolved date. A resolved date MUST be derived from an explicit phrase or the meeting date plus an explicit relative expression. | 3 |
| FR-19 | Priority MUST default to `unknown` unless the conversation expresses urgency or importance. | 3 |
| FR-20 | Every decision and action item MUST carry at least one evidence link (transcript segment ID, verbatim quote, character offsets). Items whose evidence fails server-side verification MUST be dropped and counted, not stored ungrounded. | 3 |
| FR-21 | All LLM output MUST validate against a Pydantic model derived from a strict JSON Schema; invalid output MUST trigger bounded repair, then a typed failure. | 3 |
| FR-22 | Intelligence runs MUST record LLM provider, model, prompt version, schema version, token usage, cost, latency and attempt count. | 3 |
| FR-23 | If the LLM provider is unavailable or unconfigured, the meeting MUST remain usable with its transcript, the meeting MUST be marked `intelligence_status = failed` with a retryable error code, and a deterministic extractive fallback summary SHOULD be produced. | 3 |
| FR-24 | Meetings longer than the model context window MUST be processed by anchored chunking with deterministic merge/dedupe, not truncation. | 3 |

### 4.4 Review, search, export

| ID | Requirement | Stage |
|---|---|---|
| FR-25 | Users MUST be able to edit action-item title, description, owner, due date, priority, status and dependencies. | 4 |
| FR-26 | Users MUST be able to rename diarized speakers per meeting. | 4 |
| FR-27 | Users MUST be able to search meetings by title/summary, and search within a transcript returning timestamped hits with highlighted fragments. | 4 |
| FR-28 | Users MUST be able to filter action items by status, owner, priority, meeting, due window and free text. | 4 |
| FR-29 | Users MUST be able to export a meeting as JSON (schema-versioned), Markdown, plain text, SRT and WebVTT, and export action items as CSV. | 4 |
| FR-30 | The UI MUST show dashboard totals, recent meetings, pipeline status, and pending/overdue action items. | 5 |

### 4.5 Operations

| ID | Requirement | Stage |
|---|---|---|
| FR-31 | The API MUST expose liveness and readiness probes; readiness MUST verify database, Redis and object-storage reachability. | 4 |
| FR-32 | Every request and background job MUST carry a correlation ID that appears in logs and in the API error body. | 6 |
| FR-33 | Retries MUST be bounded and use exponential backoff with jitter; exhausted jobs MUST be terminal with a typed, user-visible error code. | 6 |
| FR-34 | Re-running transcription or analysis MUST create a new version and atomically switch the active pointer. | 6 |
| FR-35 | Audio objects MUST be purged by a scheduled retention job after `AUDIO_RETENTION_DAYS`, while transcript and intelligence records remain. | 6 |

## 5. Non-functional requirements

Targets are for the documented reference environment (4 vCPU, 8 GB RAM worker; managed PostgreSQL; object storage in-region). They are commitments to measure, not assertions of achieved performance.

| ID | Category | Target |
|---|---|---|
| NFR-01 | Read latency | p95 ≤ 300 ms for JSON read endpoints (excluding export streaming), at 20 concurrent users |
| NFR-02 | Upload | 100 MB upload accepted and acknowledged with `202` in ≤ 5 s on a 50 Mbps link; request body streaming, no full in-memory buffering |
| NFR-03 | Job success | ≥ 98% of valid uploads reach `ready` without operator intervention |
| NFR-04 | Transcription throughput | With `small` int8 on 4 vCPU, RTF ≤ 0.35 (a 30-min meeting ≤ ~10.5 min). Measured, not assumed; `large-v3` is documented as CPU-infeasible |
| NFR-05 | Concurrency | 5 concurrent transcription jobs queue without failure; API stays responsive (p95 ≤ 500 ms) under that load |
| NFR-06 | Availability | API restarts recover within 30 s; no job is lost on worker SIGTERM (graceful drain) |
| NFR-07 | Security | Argon2id password hashing; JWT access ≤ 15 min; refresh rotation with reuse detection; 100% of resource queries scoped by owner |
| NFR-08 | Rate limits | Auth 10/min/IP; upload 20/hour/user; default 120/min/user; search 60/min/user |
| NFR-09 | Data integrity | All multi-row writes transactional; no orphaned evidence links; FK constraints enforced; migrations reversible |
| NFR-10 | Observability | Structured JSON logs with `request_id`/`job_id`/`meeting_id`; `/metrics` exposes request and job counters/histograms |
| NFR-11 | Privacy | No audio in logs; presigned URLs ≤ 15 min; delete removes audio objects and cascades DB rows |
| NFR-12 | Cost | ≤ $0.02 LLM per 30-min meeting at the documented default model; total hosted cost per 30-min meeting ≤ $0.20 |
| NFR-13 | Portability | `docker compose up` brings the full stack up on Windows, macOS and Linux with no host FFmpeg or PostgreSQL |
| NFR-14 | Accessibility / UX | UI keyboard-navigable, status never conveyed by colour alone, all long operations show determinate or staged progress |
| NFR-15 | Maintainability | `ruff` clean, `mypy` clean on `domain/`, `services/`, `providers/`; global coverage ≥ 80%, core ≥ 90% |

## 6. Constraints and assumptions

- **Single developer, portfolio timeline.** Scope is bounded by the non-goals; effort estimates in the roadmap assume part-time work.
- **CPU-first.** No GPU is assumed. This is why `large-v3` cannot be the default and why hosted ASR is a supported adapter rather than an afterthought.
- **Provider churn is expected.** The GPT-4o/4.1 family retires 2027-01-14. Model identifiers are configuration validated at startup; prompt/schema versioning is mandatory.
- **Gated model access.** Diarization requires a Hugging Face token and accepting pyannote's model terms. The system must be fully functional without it.
- **Evaluation data must be legally redistributable.** Only CC BY 4.0 corpora (AMI, ICSI) and self-recorded, consented audio. No scraping, no real employer meetings.
- **Single-tenant per user.** Authorisation is owner-based; no organisation hierarchy.
- **No fabricated benchmarks.** Any number published in the README must come from a committed artifact produced by a script in this repository.

## 7. Success metrics

### Engineering (portfolio-credible)

| Metric | Target | Evidence |
|---|---|---|
| Validated structured-output rate (first attempt) | ≥ 95% | `evaluation_results.metrics` |
| Evidence-grounding rate (stored items with verified quotes) | 100% by construction; measured | dropped-item counter + report |
| Invented-owner rate on negative cases | 0 | annotated negative cases |
| Job success rate under fault injection | ≥ 95% | integration test report |
| Test suite runtime | unit < 60 s, full integration < 10 min | CI log |

### AI quality (Stage 8, measured)

| Metric | Target |
|---|---|
| WER on AMI IHM, `small` int8 | ≤ 0.20 |
| WER on AMI IHM, best available model | ≤ 0.15 |
| DER on AMI IHM, `community-1` | ≤ 0.25 |
| Action-item extraction strict F1 | ≥ 0.70 |
| Owner accuracy (when owner is stated) | ≥ 0.85 |
| Due-date accuracy (exact day, when stated) | ≥ 0.80 |
| Decision extraction F1 | ≥ 0.70 |
| Summary factual consistency (human review, 1–5) | ≥ 4.0 mean |

Failure to hit a target is a finding to report, not a number to revise. The report will include the achieved value and an error analysis.

## 8. Cost model

Per 30-minute meeting (estimates from published pricing, to be replaced by measured values):

| Component | Local profile | Hosted profile |
|---|---|---|
| ASR | $0 marginal; ~6–11 min CPU at RTF 0.2–0.35 (`small` int8) | AssemblyAI ~$0.12 with diarization; Deepgram ~$0.29; Groq ~$0.02 without speaker labels |
| Diarization | $0 marginal, but adds ~30 min CPU at RTF ~0.9 on 4 vCPU | included in the AssemblyAI figure |
| LLM (3 calls, ~7.5k in / 1.8k out) | ~$0.002 at $0.10/$0.50 per 1M tokens | same |
| Object storage | ~$0.001/month per 30-min file | same |

**Infrastructure:** a single 4 vCPU / 8 GB VM (~$24–48/month) plus managed PostgreSQL (~$15/month) runs the demo profile. The stack is idle-cost-free if paused. GPU is explicitly not required; the AWS scale path is documented but not provisioned by default.

Cost controls: per-meeting token accounting, a per-user daily transcription-minute cap, maximum audio duration, and a hard cap on LLM retry attempts.

## 9. Release criteria (portfolio-ready)

The project is releasable when all of the following are true and demonstrable:

1. `docker compose up` yields a working stack from a clean clone.
2. Upload → transcript → intelligence → edit → export completes on a real recording.
3. All automated tests pass in CI, including integration tests against real PostgreSQL and object storage.
4. Evidence verification rejects tampered quotes (test proves it).
5. Evaluation report exists with measured WER/DER/extraction metrics and a failure analysis.
6. README metrics match committed artifacts exactly.
7. Security controls in NFR-07/08/11 have tests.
8. Known limitations are documented, including CPU transcription throughput and diarization's HF gating.

## 10. Open questions (resolved by Stage 8 or explicitly deferred)

| Question | Resolution path |
|---|---|
| Is `small` int8 accurate enough on accented/native AMI audio? | Stage 8 measures `small` vs `distil-large-v3` vs hosted |
| Does chunked extraction lose cross-chunk commitments? | Stage 8 compares single-pass vs chunked on long meetings |
| Is a resolved `due_date` from "next sprint" defensible? | Store `precision=week` and the verbatim phrase; report separately in metrics |
| Should decisions be editable? | Deferred; v1 is read-only, documented as a future improvement |
