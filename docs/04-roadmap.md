# Development Roadmap

**Version:** 1.0 · **Created:** 2026-11-02 · **Execution model:** sequential stages, each gated

A stage is complete only when its **exit gate** passes with evidence (test output, a measured artifact, a running stack). Generating code is not completion. A failed gate is diagnosed and fixed before the next stage starts; if a gate cannot be met, the stage is reported as blocked with the reason, not silently skipped.

| Stage | Scope | Status | Effort |
|---|---|---|---|
| 0 | Discovery and architecture | ✅ **Complete** | 2 d |
| 1 | Repository foundation and CI | ⬜ Not started | 3 d |
| 2 | Audio ingestion and transcription | ⬜ Not started | 5 d |
| 3 | Meeting intelligence and LLM processing | ⬜ Not started | 6 d |
| 4 | Database and backend API | ⬜ Not started | 7 d |
| 5 | Streamlit frontend | ⬜ Not started | 4 d |
| 6 | Reliability, security, production engineering | ⬜ Not started | 5 d |
| 7 | Testing and QA hardening | ⬜ Not started | 4 d |
| 8 | Evaluation and benchmarking | ⬜ Not started | 8 d |
| 9 | Deployment and CI/CD | ⬜ Not started | 4 d |
| 10 | Documentation and portfolio readiness | ⬜ Not started | 3 d |

Total ≈ 51 developer-days; ≈ 49 remaining. Estimates are for a single developer working part-time and include testing and documentation, not just coding.

---

## Stage 0 — Product discovery and architecture ✅

**Objective:** freeze the product contract, data model, API surface and quality bars before writing code.

**Delivered**

- `docs/00-prd.md` — personas, 35 functional requirements, 15 non-functional requirements, non-goals, cost model.
- `docs/01-architecture.md` — context/container diagrams, pipeline and transaction boundaries, degradation matrix, security model, deployment profiles.
- `docs/02-data-model.md` — 19 tables with constraints and indexes, state machines, retention.
- `docs/03-api-spec.md` — 35 endpoints, error taxonomy, pagination, rate limits, export schema.
- `docs/05-evaluation-plan.md` — corpora, licensing, annotation protocol, metrics.
- `docs/06-risk-register.md`, nine ADRs, `.gitignore`, README.

**Exit gate:** every Stage 1–10 deliverable traces to a requirement ID or endpoint; no implementation work has begun. ✅

**Deliberately deferred:** directory skeleton materialisation (Stage 1), so the repository contains no empty placeholder files.

---

## Stage 1 — Repository foundation and engineering setup

**Objective:** a clone-and-run development environment with enforced quality gates.

**Depends on:** Stage 0.

**Tasks**

- [ ] `git init`; MIT `LICENSE`; `CONTRIBUTING.md`; PR/issue templates; branch protection notes.
- [ ] Two `uv` projects: `backend/` (FastAPI, SQLAlchemy, Alembic) and `frontend/` (Streamlit), each with pinned `uv.lock`.
- [ ] Layout from `docs/01-architecture.md §13`; no empty modules — each package contains its first real symbol.
- [ ] `core/config.py`: Pydantic Settings, typed env vars, `.env.example` with every variable documented, startup validation (fail fast on weak/missing secrets in production).
- [ ] `core/logging.py`: structlog JSON, request-ID contextvar, uvicorn access log integration.
- [ ] `core/errors.py`: exception hierarchy mapped to the RFC 9457 body.
- [ ] `main.py`: FastAPI app factory, `/health/live`, `/health/ready`, request-ID middleware, CORS allowlist.
- [ ] `ruff` (format + lint, including `I`, `B`, `UP`, `ASYNC`, `S` rules) and `mypy` configuration.
- [ ] `pytest` scaffolding: `unit/`, `integration/`, `e2e/`, markers (`slow`, `model`, `integration`), no-network guard via `pytest-socket`.
- [ ] `infra/docker/Dockerfile.api` (multi-stage, non-root user, no compilers in the final layer).
- [ ] `docker-compose.yml`: postgres 16, redis 7, minio, api. Health checks on every service.
- [ ] `Makefile`: `make up`, `down`, `logs`, `test`, `lint`, `typecheck`, `fmt`, `migrate`.
- [ ] `.github/workflows/ci.yml`: lint → typecheck → unit tests → integration tests (Postgres + MinIO service containers) → docker build. Cached `uv`.
- [ ] `gitleaks` job and `pip-audit`/`uv audit` on dependencies.

**Deliverables:** runnable API returning `{"status":"ok"}`, Compose stack, CI green on an empty-but-real test suite.

**Acceptance criteria**

1. `docker compose up` starts api + postgres + redis + minio; `/health/ready` returns 200 with all dependencies reported.
2. `make test` runs locally on Windows (Git Bash) and Linux.
3. CI passes lint, typecheck, tests and image build on a fresh clone.
4. `.env` is never required to be committed; `.env.example` documents every variable.
5. `docker compose config` validates; no secrets in images or the repository.

**Exit gate:** CI badge green on `main`; screenshots/logs of `/health/ready` attached to the stage report.

**Risks:** over-configuring tooling before code exists. Mitigation: the only settings added are those used in this stage; the rest arrive with their feature.

---

## Stage 2 — Audio ingestion and transcription pipeline

**Objective:** a validated upload becomes a timestamped, speaker-attributed transcript, reproducibly.

**Depends on:** Stage 1.

**Tasks**

- [ ] `providers/storage`: `StoragePort` + `S3Storage` (MinIO-compatible) + in-memory fake for tests.
- [ ] `services/ingest.py`: streamed multipart handling, size cap enforced mid-stream, temp-file cleanup in `finally`, magic-byte sniff, `ffprobe` (20 s timeout, no shell), SHA-256, dedupe, object put.
- [ ] `providers/asr`: `ASRPort` returning a normalised `ASRResult` (segments, words, language, probability, model metadata); `FasterWhisperProvider` with process-level model cache keyed by `(model, device, compute_type)`; `FakeASRProvider` for deterministic tests.
- [ ] `providers/diarization`: `DiarizationPort`; `PyannoteProvider` (optional extra); `NullDiarizationProvider` returning `capability_notes`.
- [ ] `pipelines/alignment.py`: word-level overlap assignment, segment splitting, low-confidence flags — pure functions, no I/O.
- [ ] `pipelines/audio.py`: `ffmpeg` normalisation to 16 kHz mono PCM WAV, duration probe, reject silent/empty output.
- [ ] Celery app + `ingest`, `transcribe` tasks; retries with backoff+jitter; `acks_late`; `worker_prefetch_multiplier=1`; soft/hard time limits.
- [ ] Persist transcript/speakers/segments in one transaction; active-version pointer flip.
- [ ] Alembic revisions for Stage 2 tables.
- [ ] Unit tests: alignment (synthetic turns/words), validation (magic bytes, caps), fake-provider pipeline.
- [ ] Integration test: real 60-second WAV → transcribe with `tiny` model → rows in Postgres. Marked `model`; skipped by default in unit runs.
- [ ] `scripts/make_sample_audio.py`: generates a consented, synthetic sample for the demo and tests.

**Acceptance criteria**

1. WAV/MP3/M4A upload → `202` → transcript with monotonic, non-overlapping segments and word timestamps.
2. Corrupt, oversized, over-duration and wrong-container files are rejected with the specified codes and leave no rows or objects behind.
3. A duplicate upload returns `409` with the existing meeting ID.
4. With diarization enabled, multi-speaker sample yields ≥ 2 distinct speakers and split segments at turn boundaries (asserted on a fixture).
5. With diarization disabled, transcription still succeeds and `capability_notes` explains the absence.
6. Killing the worker mid-job leaves no visible transcript; retry produces exactly one active transcript.
7. Measured RTF is recorded on the transcript row.

**Exit gate:** an end-to-end integration run on a real recording, with timings and the resulting segment table attached.

**Risks:** model memory on 4 vCPU; `ffprobe` edge cases; pyannote install weight. Mitigations: model allowlist, explicit caps, optional extra with a separate image tag.

---

## Stage 3 — Meeting intelligence and LLM processing

**Objective:** transcript → validated, evidence-grounded structured intelligence.

**Depends on:** Stage 2.

**Tasks**

- [ ] `providers/llm`: `LLMPort` (`complete_json(system, user, schema) -> RawCompletion`), `OpenAICompatibleProvider` (configurable base URL, so Groq/OpenAI/other compatible gateways share one adapter), `FakeLLMProvider`.
- [ ] Model registry: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_ALLOWED_MODELS`; startup validation against `GET /models` (cached, tolerant of offline mode); no model string hardcoded in business logic.
- [ ] Versioned price table for cost accounting.
- [ ] Pydantic schemas in `schemas/llm.py`: `SummaryPayload`, `DecisionPayload`, `ActionItemPayload`, `EvidenceRef`; JSON Schema generated, not hand-written.
- [ ] `pipelines/chunking.py`: segment-anchored chunks, overlap, token budget from a real tokenizer/estimate with a safety margin.
- [ ] `pipelines/prompts/`: versioned prompt modules with a `PROMPT_VERSION` constant and golden-output expectations.
- [ ] Three-call orchestration + map-reduce summary for long meetings.
- [ ] Validation ladder: parse → Pydantic → resolve segment IDs → verify quote substring (whitespace/case normalised, offsets recomputed) → owner sanity (name must appear in quote) → deadline sanity.
- [ ] Repair strategy: one repair prompt with the validator's exact error; then typed failure.
- [ ] Merge/dedupe across chunks; `quality_metrics` counters for drops and merges.
- [ ] Extractive fallback summary (deterministic, no LLM) for the degraded path.
- [ ] Celery `analyze` task with retries and terminal error codes.
- [ ] Alembic revisions for intelligence tables.
- [ ] Unit tests: every validator branch, including tampered quotes and hallucinated owners.
- [ ] Prompt regression fixtures: canned provider responses → asserted stored items.

**Acceptance criteria**

1. Every stored decision and action item has ≥ 1 verified evidence link; the test that tampers a quote proves rejection.
2. An owner name absent from the evidence quote cannot be stored as `matched_speaker`.
3. "No owner mentioned" yields `unassigned`; "next sprint" yields `due_date_text="next sprint"`, `due_date_precision="week"`, and either a derived date or `due_date=null`.
4. Malformed JSON triggers one repair, then a typed failure that leaves the previous meeting state intact.
5. With no API key, transcript remains readable, `intelligence_status=failed` with `llm_not_configured`, and a fallback summary exists.
6. Token usage, model, prompt version and cost are persisted per run.
7. A 90-minute synthetic transcript is processed without truncation; `chunk_count > 1`.

**Exit gate:** a real meeting's intelligence payload with evidence, plus a deliberate-failure transcript showing correct drop behaviour and counters.

---

## Stage 4 — Database and backend API

**Objective:** a complete, authorised, documented HTTP API independent of the frontend.

**Depends on:** Stages 2–3.

**Tasks**

- [ ] All 19 tables migrated; `pgcrypto` and `pg_trgm` enabled; partial unique indexes verified.
- [ ] Repositories with owner-scoped signatures; no session exposed to routers.
- [ ] Auth: Argon2id, JWT, refresh rotation + reuse detection, `/auth/*` endpoints.
- [ ] Meetings, upload, status, jobs, transcript, transcript search, speaker rename, intelligence, decisions, action-items CRUD, dependencies, export, global search, dashboard, meta.
- [ ] Offset pagination helper, filter/sort allowlists, `page_size` caps.
- [ ] Redis sliding-window rate limiter with the documented limits and fail-open/closed policy.
- [ ] RFC 9457 error handlers for every exception type, including validation.
- [ ] Presigned URL issuance inside meeting detail (no dedicated audio endpoint).
- [ ] Export renderers: JSON, Markdown, text, SRT, WebVTT, CSV.
- [ ] OpenAPI snapshot committed; `/docs` gated by env.
- [ ] Integration tests per endpoint: happy path, authz (cross-user 404), validation, conflict, pagination.
- [ ] Migration test: upgrade from empty → head → downgrade → upgrade.

**Acceptance criteria**

1. Every endpoint in `docs/03-api-spec.md` exists with the documented status codes and body shape.
2. A second user receives `404` for every resource of the first — tested per resource type.
3. Long jobs return `202` and never block; a 200 ms p95 read latency holds under 20 concurrent readers (measured with `hey`/`k6`).
4. Rate limits reject at the documented thresholds with correct headers.
5. Exports validate against the committed JSON Schema; SRT/VTT parse with a standard library parser.
6. OpenAPI diff is empty in CI.

**Exit gate:** full endpoint test suite green, plus a recorded `curl` walkthrough: register → upload → poll → read → edit → export.

---

## Stage 5 — Frontend and user experience

**Objective:** a dashboard a non-technical participant can use without reading the API docs.

**Depends on:** Stage 4.

**Tasks**

- [ ] `frontend/streamlit_app/api_client.py`: typed client, token refresh, retry on 401, typed errors surfaced as user messages.
- [ ] Pages: Dashboard, Upload, Meetings, Meeting detail, Action items, Search/Export.
- [ ] Upload: drag-and-drop, client-side size hint, staged progress from `/status` (upload → ingest → transcribe → analyse), explicit error states with retry.
- [ ] Meeting detail: transcript with timestamp navigation, speaker chips, low-confidence markers, summary/decisions/actions tabs.
- [ ] Clicking an action item scrolls the transcript to its evidence and highlights the quoted span using `char_start`/`char_end`.
- [ ] Action-item editor: inline form, optimistic-free (server-confirmed), dependency picker, status transitions.
- [ ] Search: meeting search + within-transcript search with highlighted hits.
- [ ] Export buttons for every format.
- [ ] Session handling: token in server-side session state, never in URLs; logout clears state.
- [ ] Empty, loading, error and partial states designed — not an afterthought.
- [ ] Frontend tests: API-client unit tests against golden fixtures; a headless smoke test with `streamlit.testing.v1.AppTest`.

**Acceptance criteria**

1. A new user can register, upload, watch progress, read the transcript, edit an owner, and export JSON without touching the API.
2. Every API error code maps to a human-readable message; no raw exception reaches the UI.
3. Evidence click-through lands on the correct transcript segment.
4. Keyboard navigation works for the primary flows; status is not conveyed by colour alone.
5. No secret, token, or full audio URL appears in browser-visible state.
6. `AppTest` smoke suite passes in CI without a browser.

**Exit gate:** screenshots of each page (committed under `docs/images/`) and a scripted manual walkthrough.

---

## Stage 6 — Reliability, security and production engineering

**Objective:** behave correctly when things fail, and prove it.

**Depends on:** Stages 4–5.

**Tasks**

- [ ] Retry policy per task with exponential backoff + jitter; distinct retryable vs terminal error taxonomy.
- [ ] Idempotency keys and the partial unique index in the enqueue path; reconciliation sweep for `queued` jobs with no task ID and for stuck `running` jobs past their limit.
- [ ] Graceful shutdown: stop consuming, finish or requeue in-flight work within a grace period, then exit.
- [ ] Timeouts: LLM request, ffprobe, ffmpeg, ASR per-file cap; memory guard for ASR workers.
- [ ] Security hardening sweep against the threat list in the architecture document; `bandit`/`pip-audit` in CI.
- [ ] Presigned URL TTL enforcement; bucket-private assertion at startup.
- [ ] Startup validation: production refuses default JWT secret, debug mode, wildcard CORS, or missing bucket.
- [ ] Audit logging on all mutations with before/after values.
- [ ] Retention purge job + orphan-object sweep.
- [ ] Prompt-injection handling: transcript wrapped as quoted data with explicit instruction hierarchy; test with an injection fixture.
- [ ] Failure-injection integration tests: provider 429/500, DB connection loss, storage 503, worker SIGTERM.
- [ ] Load test: 20 concurrent readers + 5 queued transcriptions; record p95 and queue behaviour.
- [ ] `SECURITY.md` with threat model, assumptions, limitations.

**Acceptance criteria**

1. Killing a worker during transcription results in a retried job and exactly one active transcript.
2. Provider 500 → retries → terminal failure with a typed code; the meeting remains readable.
3. Reuse of a rotated refresh token revokes the family (test).
4. Two concurrent analyses of one meeting produce one job (test on the partial unique index).
5. A tampered/expired presigned URL fails; bucket is not public.
6. Retention job purges objects and preserves transcripts (test with a fake clock).
7. `SECURITY.md` lists every control and every accepted risk.

**Exit gate:** failure-injection report with observed behaviour and logs; no unhandled 500s in the injected scenarios.

---

## Stage 7 — Testing and quality assurance

**Objective:** critical behaviour is protected by tests that fail when the behaviour breaks.

**Depends on:** Stage 6.

**Tasks**

- [ ] Fill unit gaps: alignment, chunking, validators, prompt rendering, export renderers, rate limiter, security helpers.
- [ ] Integration: upload→transcribe→analyse→persist (fake providers); real-model nightly job marked `model`.
- [ ] E2E (API level): full lifecycle including edit-after-reanalysis and export.
- [ ] Adversarial suite: empty audio, silence, 1-word audio, 3-hour cap boundary, wrong codec, unicode/CJK transcript, RTL text, 200 action items, concurrent edits.
- [ ] Contract tests: OpenAPI snapshot, frontend DTO golden fixtures.
- [ ] Mutation spot-check on `domain/` and validation logic (target: ≥ 70% mutants killed) — used as a diagnostic, not a gate.
- [ ] Coverage report with per-package thresholds; CI fails below them.
- [ ] Flakiness policy: no `sleep`-based waits; deterministic clocks and IDs.
- [ ] `tests/README.md` explaining the pyramid, fixtures and how to run model tests.

**Acceptance criteria**

1. Unit suite < 60 s; integration < 10 min; full suite green and deterministic across 3 consecutive runs.
2. Global coverage ≥ 80%; `domain/` + `services/` ≥ 90%.
3. Every documented error code has a test that produces it.
4. A deliberately introduced bug in evidence verification is caught by the suite (mutation check).
5. No test requires network access except those marked `model`.

**Exit gate:** coverage report + mutation results committed.

---

## Stage 8 — Evaluation and benchmarking (mandatory)

**Objective:** replace every quality claim with a measured, reproducible number.

**Depends on:** Stages 3, 4, 7.

**Tasks**

- [ ] `eval/scripts/download_ami.py`: fetch 15 AMI meetings (Mix-Headset + manual annotations), verify hashes, convert NXT → normalised JSONL; never commit audio.
- [ ] `eval/scripts/record_kit/`: script templates and consent form for 12 self-recorded meetings; annotation UI/format.
- [ ] Annotation: 12 meetings, 2–4 speakers, planted and natural items; negative cases (no decision, no owner, vague deadline, no tasks at all).
- [ ] Second-annotator review on 30% of samples; Cohen's κ reported.
- [ ] Metrics: `jiwer` WER/CER with a versioned normaliser; `pyannote.metrics` DER with collar 0.25; extraction P/R/F1 with strict and semantic matching; owner/deadline/decision accuracy; grounding rate; invented-owner count.
- [ ] Runner: `make eval` executes configurations (ASR model × diarization × prompt version), writes `evaluation_runs` rows and JSON reports.
- [ ] Reports: per-configuration table, per-sample breakdown, failure-case appendix with transcript excerpts.
- [ ] Baseline comparisons: `tiny`/`base`/`small`/`distil-large-v3`, hosted provider, prompt v1 vs v2, single-pass vs chunked.
- [ ] `eval/reports/README.md` states what was measured, when, on which hardware, and what was not.

**Acceptance criteria**

1. `make eval` reproduces a report from a clean environment given the corpus download script and API keys.
2. Every report row records git SHA, model, prompt version and hardware.
3. At least 15 AMI meetings and 12 self-recorded meetings are evaluated.
4. Negative-case results explicitly report invented owners and fabricated deadlines (target: zero).
5. Failure analysis identifies the top 5 recurring error types with examples.
6. README numbers match report artifacts exactly.

**Exit gate:** committed report + a one-page summary of achieved vs target metrics, including misses.

**Explicit policy:** no estimate is presented as a measurement; a metric that could not be computed is marked `not measured` with the reason.

---

## Stage 9 — Deployment and CI/CD

**Objective:** a public, reproducible demo with an honest cost and operating story.

**Depends on:** Stages 7–8.

**Tasks**

- [ ] `infra/compose/prod.yml`: api, worker-asr, worker-nlp, beat, caddy; no database container in production (managed Postgres).
- [ ] Caddy TLS with automatic certificates; security headers; request size limit matching the API cap.
- [ ] GitHub Actions: `ci.yml` (PR), `release.yml` (tag → multi-arch images to GHCR), manual `deploy.yml` with environment protection.
- [ ] Migration step in deploy, with a pre-migration backup and a documented rollback.
- [ ] Object storage: S3 bucket, private, lifecycle rule, CORS only if required.
- [ ] Secrets via GitHub Environments / host env file, never in images.
- [ ] Monitoring: healthcheck-based restart policy, log retention, optional Grafana Cloud scrape of `/metrics`.
- [ ] Runbook: deploy, rollback, rotate secrets, recover a stuck job, restore a backup.
- [ ] `docs/deployment.md` with cost table, sizing, and the documented (not provisioned) ECS path.
- [ ] Production smoke test: register, upload a 3-minute file, verify ready, export.

**Acceptance criteria**

1. Tagged release builds and pushes images; deploy is a documented, repeatable command.
2. Public HTTPS demo serves the UI and API; `/health/ready` returns 200.
3. A production smoke test passes on the deployed origin.
4. Migrations run automatically and are reversible.
5. `docker compose -f infra/compose/prod.yml config` validates with placeholder env.
6. Cost estimate documented with the actual instance size used.

**Exit gate:** live demo URL, smoke-test output, and a rollback rehearsal recorded.

**Note:** this stage is only executed when the author authorises provisioning. Until then, it is *prepared*, not *claimed*.

---

## Stage 10 — Documentation and portfolio readiness

**Objective:** a reviewer understands the project in five minutes and can verify it in fifteen.

**Depends on:** Stage 9.

**Tasks**

- [ ] Final README: problem, demo GIF, architecture, measured results table with artifact links, quick start, limitations.
- [ ] `docs/` consolidation: ADRs, security, evaluation, deployment, API (generated), database schema diagram.
- [ ] Screenshots of every page, light and dark; 3–5 minute end-to-end video script and recording.
- [ ] Committed sample: short consented recording, its transcript, and structured JSON output.
- [ ] `THIRD_PARTY_NOTICES.md`: AMI/ICSI attribution, CC BY 4.0 links, modifications, model licences (Whisper MIT, pyannote weights CC BY 4.0).
- [ ] "Known limitations" section that is specific and honest (CPU RTF, overlapping speech, no cross-meeting identity, English-centric evaluation).
- [ ] Resume bullets with only measured outcomes.
- [ ] Final repository audit: no secrets, no audio, no dead code, no TODOs in shipped paths, `make verify` green.

**Acceptance criteria**

1. A cold reader can run the stack from the README without asking a question.
2. Every claim links to code, a test, or a report.
3. Repository size < 20 MB excluding history; no binary audio committed.
4. `git log` reads as a coherent progression, not one dump commit.
5. Resume bullets contain numbers that exist in `eval/reports/`.

**Exit gate:** final review checklist signed off; `make verify` green from a fresh clone.

---

## Cross-cutting test strategy

| Layer | Scope | Tools | Runtime target |
|---|---|---|---|
| Unit | Pure logic: alignment, chunking, validation, matching, rendering, security helpers | pytest, no network (`pytest-socket`), fakes | < 60 s |
| Integration | Real Postgres + MinIO + Redis; fake ASR/LLM | pytest, Compose service containers | < 10 min |
| E2E (API) | Full lifecycle through HTTP | httpx + ASGI transport | < 2 min |
| Model smoke | Real faster-whisper `tiny` on a 30 s fixture | pytest marker `model` | nighty/manual |
| Frontend | API client + `AppTest` | pytest, streamlit testing | < 60 s |
| Contract | OpenAPI snapshot, DTO fixtures | pytest, `jsonschema` | < 10 s |
| Load | 20 readers + 5 queued jobs | k6 | manual, Stage 6 |
| Evaluation | Corpora metrics | `make eval` | hours, Stage 8 |

**Fakes are first-class.** `FakeASRProvider` and `FakeLLMProvider` are deterministic, configurable (including failure modes: timeout, invalid JSON, refusal, 500), and used by every integration test. This is why the suite runs offline and why failure paths are testable at all.

**Coverage gates:** global ≥ 80%, `domain/` + `services/` ≥ 90%. Coverage is a floor, not a goal; the mutation spot-check exists to catch tests that execute code without asserting anything.

## Quality gates in CI

| Gate | Fails when |
|---|---|
| `ruff format --check` | Any formatting drift |
| `ruff check` | Any lint rule violation |
| `mypy` (strict on core packages) | Any type error |
| `pytest -m "not model"` | Any failure |
| Coverage | Below thresholds |
| `gitleaks` | Any detected secret |
| `pip-audit` | Any known high/critical vulnerability without an accepted risk note |
| OpenAPI diff | API drift without schema commit |
| Docker build | Image build failure |
| `alembic upgrade head` on empty DB | Migration failure |

## Definition of done (every stage)

1. Code complete, typed, and documented where non-obvious.
2. Tests written alongside; relevant suites pass locally and in CI.
3. No critical defect known and unresolved; deferred issues recorded in the stage report.
4. Documentation updated in the same change.
5. Acceptance criteria checked individually with evidence.
6. Stage completion report written: what was built, what was measured, what failed, what is next.

## Sequencing constraints

- Stage 3 must not begin before Stage 2 produces real transcripts — prompt work against invented transcript text produces a system tuned to fiction.
- Stage 4's API is built *after* the services it exposes, not before; routers are thin by construction.
- Stage 5 is not started until Stage 4's contract is stable, otherwise the UI bakes in churn.
- Stage 8 requires Stage 7's fakes to isolate extraction metrics from ASR errors.
- Stage 9 requires Stage 8's report, because deployment claims "it works" and evaluation defines what working means.
