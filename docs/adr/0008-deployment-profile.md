# ADR-0008: Single-VM Docker Compose for the demo; ECS documented but not provisioned

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

The system needs a public demo URL, HTTPS, a background worker with enough CPU for Whisper, PostgreSQL, Redis and object storage. Realistic options:

| Option | Monthly cost | Operational effort | Notes |
|---|---|---|---|
| Single 4 vCPU/8 GB VM + Compose + managed Postgres | ~$30–60 | Low | One host, TLS via Caddy, GHCR images |
| Fly.io / Render containers | ~$25–70 | Low | Managed TLS, but worker resource limits and ephemeral storage need care |
| ECS Fargate + RDS + S3 + ALB | ~$150+ | High | Real production topology, Terraform, IAM, networking |
| Kubernetes (EKS) | ~$200+ | Very high | Unjustifiable for one service |

A portfolio reviewer will not pay for ECS. A reviewer *will* notice an unsupported claim of "production-grade Kubernetes deployment".

## Decision

Deploy the demo on a **single VM** running Docker Compose:

- `caddy` (TLS, security headers, body-size limit matching the API cap)
- `api` (uvicorn, 2 workers)
- `worker-asr` (concurrency 1, memory limit, diarization extra enabled for the demo)
- `worker-nlp` (concurrency 4)
- `beat`
- `frontend` (Streamlit)
- managed PostgreSQL (backups, no self-managed database)
- S3 bucket (private, lifecycle rule), not MinIO, for durability

Images are built once in CI and pushed to GHCR; deployment pulls a pinned tag. Migrations run as a one-shot container before the API starts.

The AWS scale path (ECS Fargate + RDS + ALB) is **documented with a Terraform skeleton and a cost table, but not provisioned**. The README says so explicitly.

## Consequences

**Positive**

- Cost is defensible and the whole topology fits in one diagram a reviewer can follow.
- No Kubernetes/ECS knowledge is asserted that the project does not demonstrate.
- Caddy provides automatic certificates with a ten-line config.
- The same Compose file is used locally with MinIO, so dev/prod drift is limited to the storage backend and database host.

**Negative**

- Single point of failure; a host reboot takes the demo down.
- Vertical scaling only; concurrent transcription capacity is bounded by the VM.
- Streamlit and the API compete for CPU on the same host.
- Not a demonstration of cloud-native orchestration, which some job descriptions value.

**Mitigations**

- Health checks and restart policies; a documented runbook for restart and rollback.
- ASR concurrency fixed at 1 and the queue absorbs bursts; the UI shows honest queue position.
- The documented ECS path, cost table and migration mapping show the scaling thought process even though it is not deployed.
- ADR states the trigger for moving to ECS: sustained queue depth > 5 jobs or p95 wait > 15 minutes.

## Alternatives considered

- **ECS from day one.** Rejected on cost and unverifiable claims; a broken ECS deployment would be worse than a working VM deployment.
- **Fly.io.** Attractive, but machine sizing for Whisper and the persistent worker model are less predictable than a plain VM, and the Compose file would not transfer as directly.
- **Kubernetes.** Rejected: operationally disproportionate, and the resource cost exceeds the demo budget.
- **Serverless (Lambda + API Gateway).** Rejected: 15-minute execution limits and cold-start model loading are hostile to ASR workloads; container image size limits are also a constraint.
