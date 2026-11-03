# Implementation Status

**Verified:** 2026-11-03 on Windows 11, Python 3.11, SQLite locally.
**Scope:** what is actually in this repository, what is partial, and what is deliberately deferred.

This document exists because the Stage 0 design describes a larger system than the MVP implements. The README and this matrix are the authoritative status; the design docs remain the target architecture.

## Verification summary

| Gate | Command | Result |
|---|---|---|
| Backend tests | `cd backend && ../.venv/Scripts/python.exe -m pytest -q` | **39 passed** |
| Frontend tests | `cd frontend && ../.venv/Scripts/python.exe -m pytest -q` | **3 passed** |
| Backend lint | `cd backend && ../.venv/Scripts/python.exe -m ruff check app tests` | **clean** |
| Frontend lint | `cd frontend && ../.venv/Scripts/python.exe -m ruff check streamlit_app tests` | **clean** |
| Types | `cd backend && ../.venv/Scripts/python.exe -m mypy app` | **success, 46 files** |
| Migrations | `alembic downgrade base && alembic upgrade head` | **both succeeded** |
| Pipeline eval | `.venv/Scripts/python.exe eval/scripts/run_pipeline_eval.py` | **report written** |
| ASR smoke | `.venv/Scripts/python.exe eval/scripts/measure_asr_smoke.py` | **report written (tiny/int8)** |
| Compose | `docker compose config -q` with a local `.env` | **valid** |

## Implemented

| Area | Evidence | Notes |
|---|---|---|
| App factory, config, problem+json errors, request IDs | `backend/app/main.py`, `core/` | Startup validation rejects retired model IDs and placeholder secrets in production |
| 12-table schema + constraints | `backend/app/db/models.py` | Owners, transcripts, speakers, segments, intelligence, decisions, key points, actions, evidence, assets, jobs, refresh tokens |
| Alembic migration | `backend/alembic/versions/052340adacfc_initial_schema.py` | Upgrade and downgrade verified |
| Registration, login, refresh rotation, logout, `/me` | `backend/app/api/auth.py`, `services/auth.py` | Argon2id; refresh reuse revokes the family; commit-before-raise bug fixed and covered by a test |
| Per-user meetings CRUD + ownership scoping | `backend/app/api/meetings.py` | Cross-user reads return 404 |
| Upload, validation, dedupe, storage | `backend/app/services/ingest.py`, `services/storage.py` | Local path verified; S3 adapter present; `list_keys` enabled for orphan detection |
| Pipeline with transcribing/analyzing stages | `backend/app/services/pipeline.py` | Post-commit dispatch; typed failure states; diarization alignment integrated |
| Fake ASR + faster-whisper adapter | `backend/app/providers/asr.py` | Real adapter measured once on synthetic TTS |
| Diarization port + adapters | `backend/app/providers/diarization.py` | Null, fake, and pyannote providers; speaker turns aligned with word timestamps |
| Distributed rate limiting | `backend/app/core/rate_limiter.py` | Redis sorted-set sliding window with memory fallback; process-safe and cluster-ready |
| Stranded-job reconciliation | `backend/app/services/reconciliation.py` | Re-drives queued jobs after commit-dispatch gap; Celery Beat scheduled |
| Audio retention & orphan sweep | `backend/app/services/retention.py` | Enforces `AUDIO_RETENTION_DAYS`, marks `purged_at`, removes abandoned files |
| Rule-based + OpenAI-compatible LLM | `backend/app/providers/llm.py` | Both produce the same Pydantic contract |
| Evidence verification and grounding counts | `backend/app/services/grounding.py`, `intelligence.py` | Tampered-evidence integration test drops the item |
| Speaker alignment | `backend/app/pipelines/alignment.py` | Merges turns and words via maximum overlap; fully tested |
| Exports | `backend/app/services/exports.py` | Markdown, JSON, action-item CSV |
| Streamlit UI | `frontend/streamlit_app/app.py` | Auth, dashboard, upload polling, meeting/transcript views, action-item editing, exports |
| Celery app and pipeline task | `backend/app/workers/` | Compose sets `JOBS_MODE=celery`; beat schedules for reconciliation and retention |
| Dockerfiles + Compose | `infra/docker/`, `docker-compose.yml` | Config validated; Redis rate limiting enabled in Compose |
| CI workflow | `.github/workflows/ci.yml` | Committed; tests and linting automated |
| Evaluation harness | `eval/scripts/run_pipeline_eval.py` | Three synthetic text fixtures |
| Real-ASR smoke harness | `eval/scripts/measure_asr_smoke.py` | One synthetic TTS clip |
| Licensing & Repository | `LICENSE`, `.git` | MIT License added, git initialized |

## Partial

| Area | What exists | What is missing |
|---|---|---|
| Diarization benchmark | Architecture, null/fake/pyannote adapters, pipeline alignment, tests | Real-audio DER evaluation on multi-speaker dataset with HF token |
| Storage | Local and S3-compatible adapters behind one port | Real-bucket integration test against live AWS S3 |
| LLM quality | Adapter, schema validation, retries, grounding | Measured extraction run against a paid LLM at production scale |
| UI | Main workflow | Password reset, user settings, bulk actions |

## Deferred (Future Roadmap)

- Audit log table (for compliance audits)
- Task dependencies and cross-meeting speaker identity graphs
- Full-text/trigram search (PostgreSQL pg_trgm / tsvector)
- Real-meeting academic benchmarks (AMI / ICSI corpora)
- Cloud deployment Terraform manifests & managed PostgreSQL IaC

## Measured artifacts

| Artifact | What it measures | Scope |
|---|---|---|
| `eval/reports/pipeline_conformance.json` | Decision/action P/R/F1, owner accuracy, grounding rate, invented owners | 3 synthetic text fixtures, rule-based extractor |
| `eval/reports/asr_smoke.json` | Latency, RTF, WER | 1 synthetic TTS clip, faster-whisper tiny/int8 |
