# Security Policy

**Scope:** the MVP in this repository. It is a portfolio/demo system, not a certified product. This document lists what is enforced, what is accepted, and what must change before handling real confidential meetings.

## Reporting a vulnerability

If this repository is hosted with private security advisories enabled, open one there. Otherwise contact the maintainer directly through the repository profile. Do not include live credentials, private meeting audio, or personal data in a report. Please allow a reasonable window to fix the issue before public disclosure.

No bug bounty or formal SLA is offered.

## Supported versions

The `main` branch is the only supported version. There are no long-term-support releases; this is an MVP.

## Implemented controls

### Authentication and sessions

- Argon2id password hashing (`time_cost=3`, `memory_cost=64 MiB`, `parallelism=2`).
- JWT access tokens, HS256, 15-minute default TTL, signed with `JWT_SECRET`; startup validation rejects weak/placeholder secrets in production.
- Opaque 32-byte refresh tokens stored only as SHA-256 hashes, rotated on every use.
- Refresh-token reuse revokes the token family. The reuse path commits the revocation before raising, so a rejected request cannot roll it back.
- Logout revokes the presented refresh token.
- Per-user authorisation on every meeting/action-item query. Cross-user access returns `404`, not `403`, to avoid confirming existence.

### Upload and storage

- Streaming size cap (`MAX_UPLOAD_MB`) and duration cap (`MAX_AUDIO_MINUTES`).
- Content-type/magic-byte validation and `ffprobe` inspection; filenames are display-only and never used as paths.
- Object keys are UUID-based and namespaced by owner. Local storage stays under the configured root.
- SHA-256 dedupe is scoped to the owner.
- Audio retrieval is through the API; there is no permanent public object URL.
- S3 is optional and private-bucket by configuration, but the S3 path has not been integration-tested here.

### Application

- SQLAlchemy parameterised queries; no string-built SQL.
- Pydantic validation on request and model-output boundaries.
- RFC 9457-style problem+json errors with request IDs; internal exceptions are not echoed to clients.
- CORS uses an explicit origin allowlist; credentials are not combined with a wildcard.
- A request-ID middleware propagates `X-Request-ID` through responses and logs. Response security headers are **not** added by the app; a reverse proxy must add HSTS, `X-Content-Type-Options`, and frame protections.
- Structured logs use an allowlist of fields; tokens, passwords, audio paths, and private quotes are not logged at INFO.
- The Streamlit UI never calls `unsafe_allow_html`. Transcript and model text are rendered as text; evidence highlighting uses character offsets, not injected HTML.
- Upload and auth endpoints are covered by a process-local sliding-window rate limiter.

### Secrets and repository hygiene

- Secrets come from environment variables / `.env`; `.env` is gitignored.
- `.env.example` contains placeholders only.
- Startup rejects the known placeholder JWT secret when `ENV=production`.
- No API keys, tokens, model weights, or meeting audio are committed.

## Accepted risks and limitations

| Risk | Current state | Required before production |
|---|---|---|
| Rate limiting on Redis | Implemented via Redis sorted sets with process-local memory fallback | Verify Redis high availability or cluster topology |
| Scheduled retention purge | Implemented via `enforce_audio_retention` and Celery Beat schedule | Configure `AUDIO_RETENTION_DAYS` per compliance policy |
| No audit log | Mutations are not independently attributable beyond row timestamps | Add append-only audit records for edits and deletes |
| Prompt injection in transcripts | Treated as data; evidence verification limits damage to items that quote the transcript | Add adversarial fixtures, output review, and provider-side safety controls |
| No malware/content scanning | Uploads are validated as media, not scanned | Add AV scanning and quarantine if accepting untrusted public uploads |
| No TLS in Compose | The local stack serves plain HTTP | Terminate TLS at a reverse proxy; set secure cookie/transport expectations |
| SQLite default | Suitable for one user; weaker concurrency and file-permission model | Use PostgreSQL with restricted network access |
| S3 path unverified | Adapter exists, no real-bucket test | Test private bucket, presigned URLs, IAM least privilege |
| `ffprobe` is a native dependency | Runs with a timeout and without shell interpolation, but parses untrusted media | Keep the binary patched; run in a constrained container |
| API docs enabled locally | `API_DOCS_ENABLED=true` by default | Disable or protect docs in a public deployment |
| Streamlit server holds tokens in process memory | Tokens are not put in browser storage by this app | Review deployment isolation and session lifetime |
| No CSRF token | The API uses bearer tokens, not ambient cookies; Streamlit calls it server-side | Revisit if cookie-based browser auth is added |

## Production checklist

- [ ] Set `ENV=production`, a random 32+ byte `JWT_SECRET`, and `RATE_LIMIT_ENABLED=true`.
- [ ] Use PostgreSQL with a least-privilege role; do not expose the port publicly.
- [ ] Put the API behind TLS; restrict CORS to the real UI origin.
- [ ] Disable `API_DOCS_ENABLED` or protect `/docs` and `/openapi.json`.
- [ ] Use a private S3 bucket with least-privilege credentials and short presigned TTLs.
- [ ] Run the worker as a non-root user with a read-only root filesystem where possible.
- [ ] Add retention, audit logging, and the Redis rate limiter before storing confidential audio.
- [ ] Back up the database; test restore.
- [ ] Pin and scan dependencies; rebuild images on security updates.
- [ ] Review the accepted-risk table and document any risk you choose to keep.

## Out of scope

This MVP does not claim compliance with SOC 2, ISO 27001, HIPAA, GDPR, or any other regime. It does not provide encryption at rest beyond what the underlying disk/bucket provides, nor formal incident response.
