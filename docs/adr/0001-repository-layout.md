# ADR-0001: Two-project monorepo with `uv`

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

The system has four deployable surfaces (API, ASR worker, NLP worker, Streamlit UI), an offline evaluation harness, and infrastructure definitions. They share a data model and an environment but have incompatible dependency sets: the Streamlit image must not install torch, and the API image must not install Streamlit.

Options: a single Python package with extras, two Python projects in one repository, or separate repositories per service.

## Decision

One repository, two `uv` projects:

- `backend/` — FastAPI, SQLAlchemy, Alembic, Celery, ASR/LLM providers, tests.
- `frontend/` — Streamlit app, its own API client and DTOs, its own tests.

Shared Docker images are built from the backend project with different extras (`api` installs no ASR extras; `worker` installs `[asr]` and optionally `[diarization]`). Evaluation lives in `eval/` as scripts that import the backend package, not a third project. Infrastructure lives in `infra/`.

The frontend does **not** import backend Pydantic models. It talks to a versioned HTTP API and validates golden fixtures against its own DTOs.

## Consequences

**Positive**

- Image sizes stay honest: the API image is ~200 MB, the worker image carries the model stack.
- CI can run backend and frontend jobs in parallel with independent caches.
- The frontend cannot accidentally couple to internal modules; the API contract is the only seam.
- One clone, one `docker compose up`, one history for a portfolio reviewer.

**Negative**

- Two `pyproject.toml`/`uv.lock` pairs to maintain.
- DTO duplication in the frontend can drift.

**Mitigations**

- A contract test validates frontend fixtures against the committed OpenAPI schema; drift fails CI.
- A `Makefile` at the root runs both projects' checks so the two-project split is invisible day to day.

## Alternatives considered

- **Single package with extras.** Rejected: one `pyproject.toml` with optional dependency groups works, but import paths and lock resolution couple the UI to the API's dependency graph, and a single CI job hides which surface broke.
- **Separate repositories.** Rejected for a portfolio project: reviewers will not clone three repositories, and cross-cutting changes (schema change + API + UI) become three PRs.
- **Nx/Turborepo-style monorepo tooling.** Rejected as unnecessary for two Python projects.
