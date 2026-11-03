# ADR-0005: Celery + Redis with per-stage queues and idempotent jobs

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

Transcription takes minutes and must not block HTTP requests. The pipeline has three stages with different resource profiles and different failure semantics:

- `ingest` — I/O, fast, client-error failures.
- `transcribe` — CPU/RAM-heavy, one at a time per worker, retryable.
- `analyze` — network-bound, concurrency-friendly, retryable with backoff.

Candidates: Celery, RQ, Dramatiq, arq, FastAPI `BackgroundTasks`, and a database-backed queue.

## Decision

Celery 5 with Redis 7 as broker and result backend, two queues (`asr`, `nlp`) and one beat scheduler. Configuration:

- `acks_late=True` and `worker_prefetch_multiplier=1` so a killed worker's message is redelivered.
- `task_reject_on_worker_lost=True`.
- Soft/hard time limits per task; `max_retries` with exponential backoff and jitter.
- Separate worker containers for the two queues; ASR concurrency 1 to bound memory.
- Idempotency enforced in PostgreSQL (`processing_jobs.idempotency_key` unique, partial unique index on active job per meeting/type), not by trusting the broker.
- Beat handles retention purge, stuck-job reconciliation, and orphan cleanup.

Redis is also the rate-limiting store. One dependency, two uses, both appropriate.

## Consequences

**Positive**

- Mature retry, routing, time-limit and scheduling features that would otherwise be hand-built.
- Separate queues prevent a 30-minute transcription from starving analysis work.
- Recognition: Celery appears in most backend job descriptions; the implementation is idiomatic and defensible in an interview.
- `acks_late` plus a persisted job row gives at-least-once processing with idempotent effects.

**Negative**

- Celery's configuration surface is large, and misconfiguration (early ack, prefetch, result backend bloat) is a real hazard.
- Redis is not durable; a broker restart can lose queued messages. The job rows in PostgreSQL are the source of truth, and reconciliation re-dispatches.
- Two more containers to operate.

**Mitigations**

- Result backend is used only for task metadata; durable state lives in `processing_jobs`.
- A reconciliation sweep finds `queued` jobs with no live task and `running` jobs past their limit.
- Configuration is centralized in `workers/celery_app.py` with comments explaining each non-default setting.
- Integration tests cover redelivery and duplicate dispatch.

## Alternatives considered

- **RQ.** Simpler, but weaker scheduling/retry semantics and no first-class beat equivalent; would require custom reconciliation for periodic jobs.
- **Dramatiq.** Cleaner API and good retry middleware, but a smaller hiring signal and fewer answers available for operational problems.
- **arq.** Async-native and elegant, but it would force an async ORM path (see ADR-0004) and has a smaller ecosystem.
- **`BackgroundTasks`.** Rejected: dies with the process, no retries, no visibility, no separation of resources. It is not a job queue.
- **PostgreSQL-only queue (e.g. `pgmq`, SKIP LOCKED).** Genuinely attractive — one fewer dependency, transactional enqueue. Rejected for v1 because it means building retry, scheduling and worker lifecycle by hand; noted as a legitimate future simplification.
