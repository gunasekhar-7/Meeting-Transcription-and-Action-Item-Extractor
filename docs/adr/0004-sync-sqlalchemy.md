# ADR-0004: Synchronous SQLAlchemy 2.0 with psycopg 3, everywhere

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

FastAPI supports both `async def` and `def` endpoints (the latter run in a threadpool). Celery tasks are synchronous. The application has two writers: HTTP handlers and background workers, and both operate on the same ORM models.

The default "modern FastAPI" recommendation is async SQLAlchemy + asyncpg. Applying it here means either duplicating the repository layer for sync and async sessions, or making workers drive an event loop around async sessions.

The workload is not database-bound: a meeting produces a few hundred segment inserts in one transaction and a handful of reads. Transcription and LLM calls dominate latency by orders of magnitude.

## Decision

Use **synchronous** SQLAlchemy 2.0 with `psycopg` 3 throughout. FastAPI endpoints that touch the database are declared as plain `def` and run in the threadpool. Session lifecycle is provided by a dependency that commits on success and rolls back on exception.

## Consequences

**Positive**

- One repository implementation, one session pattern, one test fixture. No dual API.
- Celery tasks use the same session factory naturally.
- Synchronous code is easier to reason about for transaction boundaries, which matters because the architecture requires precise commit points around long inference calls.
- Fewer subtle bugs: no "session used in a different task" errors, no implicit greenlet behaviour, no forgotten `await`.

**Negative**

- Thread-pool concurrency is bounded (default 40), so a very high-concurrency read API would need tuning or an async migration.
- Some libraries in the ecosystem assume async sessions in FastAPI examples, so contributors must not copy-paste them.
- Under heavy I/O-bound database load, async would use fewer resources.

**Mitigations**

- Pool sized explicitly (`pool_size`, `max_overflow`) with a documented limit; load tested at 20 concurrent readers in Stage 6.
- The session dependency is the single place connections are acquired, so an async migration would be localized if the load test ever justifies it.
- ADR documents the threshold: if p95 read latency is dominated by connection waits at the tested concurrency, revisit.

## Alternatives considered

- **Async SQLAlchemy + asyncpg in the API, sync in workers.** Rejected: two repository layers or a generic abstraction that is harder to read than either. The performance gain is not needed at this scale.
- **Raw SQL with `psycopg`.** Rejected: loses type-safe model definitions and migration ergonomics; the schema is complex enough to justify an ORM.
- **SQLModel.** Rejected: thinner ecosystem, awkward for the partial indexes and CHECK constraints this schema depends on.
