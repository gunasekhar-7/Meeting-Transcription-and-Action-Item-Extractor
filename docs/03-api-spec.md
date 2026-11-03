# API Specification

**Base URL:** `/api/v1` · **Version:** 1.0 (Stage 0) · **Format:** JSON, UTF-8 · **Auth:** Bearer JWT

This is the design contract. The FastAPI implementation (Stage 4) is generated from Pydantic schemas, and a snapshot test compares the committed OpenAPI document to the live one so drift is a CI failure.

---

## 1. Conventions

| Concern | Decision |
|---|---|
| Versioning | Path prefix `/api/v1`. Breaking changes require `/v2`; additive fields are non-breaking |
| Resource IDs | UUID v4 strings |
| Timestamps | RFC 3339 UTC with `Z` suffix (`2026-11-02T14:05:00Z`) |
| Durations | Milliseconds as integers (`start_ms`, `end_ms`) |
| Field naming | `snake_case` in JSON (Pydantic default; matches Python and SQL) |
| Nullability | Unknown values are explicit `null`, never `""` or `0` |
| Content type | `application/json`, except upload (`multipart/form-data`) and exports |
| Compression | Enabled for JSON responses |
| Request ID | Generated if absent, echoed in `X-Request-ID` and in every error body |
| Casing of enums | Lowercase snake_case strings |

### 1.1 Authentication

- Access token: JWT, HS256, 15-minute lifetime.
- Refresh token: opaque 32-byte value, 7-day lifetime, rotated on every use.
- Header: `Authorization: Bearer <access_token>`.
- Login uses the OAuth2 password form so Swagger's **Authorize** button works out of the box.

**Access token claims**

```json
{
  "sub": "6f0c1a2e-…",
  "role": "user",
  "jti": "b4d1…",
  "typ": "access",
  "iat": 1793620800,
  "exp": 1793621700
}
```

Expired or malformed tokens return `401 unauthenticated`. A valid token for a resource owned by another user returns **`404`**, not `403` — existence is not leaked.

### 1.2 Error model (RFC 9457 `application/problem+json`)

```json
{
  "type": "https://meeting-intelligence.dev/errors/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "code": "validation_error",
  "detail": "1 field failed validation.",
  "instance": "/api/v1/meetings",
  "request_id": "01JCH3…",
  "errors": [
    { "field": "title", "message": "String should have at least 1 character" }
  ]
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | Malformed JSON, unusable query parameters |
| 401 | `unauthenticated` | Missing/expired/invalid token, bad credentials |
| 403 | `forbidden` | Authenticated but not permitted (admin-only routes) |
| 404 | `not_found` | Missing resource **or** not owned by caller |
| 409 | `duplicate_audio` | Same digest already uploaded by this user |
| 409 | `conflict` | Illegal state transition (e.g. analyse before transcript exists) |
| 413 | `audio_too_large` | File exceeds `MAX_UPLOAD_MB` |
| 415 | `unsupported_media_type` | Container/codec not accepted |
| 422 | `validation_error` | Schema validation failure |
| 422 | `audio_unreadable` | `ffprobe` cannot read the file |
| 422 | `audio_too_long` | Duration exceeds `MAX_AUDIO_MINUTES` |
| 429 | `rate_limited` | Limit exceeded; `Retry-After` present |
| 500 | `internal_error` | Unhandled; `request_id` is the support handle |
| 503 | `storage_unavailable` / `queue_unavailable` | Dependency down |
| 503 | `llm_not_configured` | Analysis requested without provider configuration |

Clients must branch on `code`, never on `detail` text.

### 1.3 Pagination

`?page=1&page_size=20` (`page_size` 1–100, default 20).

```json
{ "items": [], "page": 1, "page_size": 20, "total": 137, "total_pages": 7 }
```

Out-of-range `page` returns an empty `items` array, not `404`.

### 1.4 Filtering and sorting

Filters are explicit query parameters — no generic filter DSL. Sorting uses `sort=-created_at` (descending) on a documented allowlist per endpoint; an unknown field is `422`.

### 1.5 Rate limits

| Scope | Limit | Key |
|---|---|---|
| `POST /auth/login`, `/auth/register` | 10 / minute | IP |
| `POST /meetings/{id}/audio` | 20 / hour | user |
| `GET /search`, transcript search | 60 / minute | user |
| All other authenticated routes | 120 / minute | user |

Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (epoch seconds). On rejection: `429`, `Retry-After`. Limits are Redis sliding windows; auth endpoints fail closed, other routes fail open and increment `rate_limiter_degraded_total`.

### 1.6 OpenAPI

- `GET /openapi.json` served by default; Swagger UI at `/docs` enabled when `API_DOCS_ENABLED=true` (default in dev, off in production).
- Every endpoint declares response models, so the schema is complete enough to generate a client.
- A committed `openapi.json` is diffed in CI.

---

## 2. Endpoint summary

| Method | Path | Purpose | Success |
|---|---|---|---|
| POST | `/auth/register` | Create account | 201 |
| POST | `/auth/login` | OAuth2 password form → tokens | 200 |
| POST | `/auth/refresh` | Rotate refresh token | 200 |
| POST | `/auth/logout` | Revoke refresh family | 204 |
| GET | `/auth/me` | Current profile | 200 |
| POST | `/meetings` | Create meeting metadata | 201 |
| GET | `/meetings` | List/filter meetings | 200 |
| GET | `/meetings/{id}` | Meeting detail | 200 |
| PATCH | `/meetings/{id}` | Update title/description/date | 200 |
| DELETE | `/meetings/{id}` | Delete meeting + assets | 204 |
| POST | `/meetings/{id}/audio` | Upload audio, enqueue pipeline | 202 |
| GET | `/meetings/{id}/status` | Pipeline status (poll target) | 200 |
| GET | `/meetings/{id}/jobs` | Job history | 200 |
| POST | `/meetings/{id}/transcription` | Re-run transcription | 202 |
| GET | `/meetings/{id}/transcript` | Active transcript | 200 |
| GET | `/meetings/{id}/transcript/search` | Search within transcript | 200 |
| PATCH | `/meetings/{id}/speakers/{speaker_id}` | Rename a speaker | 200 |
| POST | `/meetings/{id}/intelligence` | Re-run analysis | 202 |
| GET | `/meetings/{id}/intelligence` | Summary, points, decisions, actions | 200 |
| GET | `/meetings/{id}/decisions` | Decisions only | 200 |
| GET | `/meetings/{id}/action-items` | Action items for meeting | 200 |
| GET | `/meetings/{id}/export` | Export transcript + intelligence | 200 |
| GET | `/action-items` | Cross-meeting action items | 200 |
| POST | `/action-items` | Create manual action item | 201 |
| GET | `/action-items/{id}` | Action item detail | 200 |
| PATCH | `/action-items/{id}` | Edit action item | 200 |
| DELETE | `/action-items/{id}` | Delete action item | 204 |
| PUT | `/action-items/{id}/dependencies` | Replace dependency set | 200 |
| GET | `/action-items/export` | CSV export | 200 |
| GET | `/search` | Cross-entity search | 200 |
| GET | `/dashboard/summary` | Dashboard aggregates | 200 |
| GET | `/meta` | Version, git SHA, prompt/schema versions | 200 |
| GET | `/health/live` | Liveness | 200 |
| GET | `/health/ready` | Readiness (DB, Redis, storage) | 200 / 503 |
| GET | `/metrics` | Prometheus exposition | 200 |

---

## 3. Auth

### `POST /auth/register`

```json
{ "email": "ada@example.com", "password": "correct horse battery staple", "display_name": "Ada" }
```

`201` → user profile. Password policy: 12–128 characters, rejected if in a small common-password list, never logged. Duplicate email → `409 conflict` (not `422`) with a generic message that does not confirm account existence beyond the duplicate case — accepted trade-off for usability.

### `POST /auth/login`

`application/x-www-form-urlencoded`: `username` (email), `password`.

```json
{
  "access_token": "eyJ…",
  "refresh_token": "9f2c…",
  "token_type": "bearer",
  "expires_in": 900
}
```

Bad credentials → `401 unauthenticated`, constant-time comparison, and a per-IP rate limit.

### `POST /auth/refresh`

```json
{ "refresh_token": "9f2c…" }
```

Returns a new pair. The presented token is revoked immediately. Reuse of an already-rotated token revokes the entire family and returns `401`.

### `POST /auth/logout`

Body: `{ "refresh_token": "…" }` → `204`. Idempotent: logging out twice is not an error.

### `GET /auth/me`

```json
{ "id": "…", "email": "ada@example.com", "display_name": "Ada", "role": "user", "created_at": "2026-11-02T09:00:00Z" }
```

---

## 4. Meetings

### `POST /meetings`

```json
{ "title": "Q4 roadmap sync", "description": "Weekly planning", "meeting_date": "2026-11-01T15:00:00Z" }
```

`201` → meeting resource. `meeting_date` is optional and stored as `null` when absent; the API never substitutes the upload time.

```json
{
  "id": "0b0f…",
  "title": "Q4 roadmap sync",
  "description": "Weekly planning",
  "meeting_date": "2026-11-01T15:00:00Z",
  "status": "created",
  "intelligence_status": "pending",
  "duration_seconds": null,
  "language": null,
  "created_at": "2026-11-02T09:01:00Z",
  "updated_at": "2026-11-02T09:01:00Z"
}
```

### `GET /meetings`

Query: `page`, `page_size`, `status`, `intelligence_status`, `date_from`, `date_to`, `q` (title/description/summary), `sort` (`created_at`,`meeting_date`,`title`, `-` prefix for descending).

```json
{
  "items": [
    {
      "id": "0b0f…",
      "title": "Q4 roadmap sync",
      "status": "ready",
      "intelligence_status": "ready",
      "meeting_date": "2026-11-01T15:00:00Z",
      "duration_seconds": 1842.5,
      "action_item_count": 7,
      "open_action_item_count": 5,
      "speaker_count": 3,
      "created_at": "2026-11-02T09:01:00Z"
    }
  ],
  "page": 1, "page_size": 20, "total": 1, "total_pages": 1
}
```

### `GET /meetings/{id}`

Detail adds `audio` (filename, size, duration, purged flag — never a permanent URL), `active_transcript_id`, `active_intelligence_id`, `counts`, and `latest_error`.

### `PATCH /meetings/{id}`

Accepts any subset of `title`, `description`, `meeting_date` (`null` clears). Returns the updated resource. Writes an audit row.

### `DELETE /meetings/{id}`

`204`. Captures object keys, deletes rows in dependency order (evidence → items → decisions → key points → intelligence → segments → speakers → transcripts → asset → jobs → meeting), commits, then attempts to delete the objects. A failed object delete is logged for the orphan sweep; the meeting remains deleted. Repeated delete → `404`.

### `POST /meetings/{id}/audio`

`multipart/form-data`, field `file`. Optional header `Idempotency-Key`.

Processing is streaming: the API enforces `MAX_UPLOAD_MB` while writing to a temp file, then sniffs magic bytes, runs `ffprobe` with a 20-second timeout, hashes, uploads to object storage, inserts the asset, and enqueues `ingest`.

`202 Accepted`:

```json
{
  "meeting_id": "0b0f…",
  "audio_asset_id": "c7a2…",
  "job_id": "5e19…",
  "job_type": "ingest",
  "status": "queued",
  "status_url": "/api/v1/meetings/0b0f…/status"
}
```

Failure modes: `413 audio_too_large`, `415 unsupported_media_type`, `422 audio_unreadable`, `422 audio_too_long`, `409 duplicate_audio` (body includes `existing_meeting_id`), `503 storage_unavailable`.

Two uploads for the same meeting while one is in flight → `409 conflict` (`audio_already_uploaded`).

### `GET /meetings/{id}/status`

The polling contract used by the UI. Cheap: joins current jobs, no transcript payload.

```json
{
  "meeting_id": "0b0f…",
  "status": "processing",
  "intelligence_status": "pending",
  "stages": [
    { "name": "ingest", "status": "succeeded", "progress": 100, "duration_ms": 1840 },
    { "name": "transcribe", "status": "running", "progress": 45, "duration_ms": null },
    { "name": "analyze", "status": "queued", "progress": 0, "duration_ms": null }
  ],
  "error": null,
  "updated_at": "2026-11-02T09:04:12Z"
}
```

`error` when present:

```json
{ "code": "asr_model_oom", "message": "Transcription ran out of memory. Try a smaller model or a shorter recording.", "retryable": true, "request_id": "01JCH3…" }
```

`progress` is a coarse, honest estimate derived from stage and elapsed time — not a fabricated precision. The UI labels it as estimated until the stage completes.

### `GET /meetings/{id}/jobs`

Paginated job history with `job_type`, `status`, `attempt`, `error_code`, `duration_ms`, `metadata`.

### `POST /meetings/{id}/transcription`

```json
{ "diarize": true, "asr_model": "small" }
```

Both fields optional; defaults come from configuration. `asr_model` must be in the configured allowlist (`422` otherwise) — this prevents a request from selecting an arbitrary or expensive model. Requires audio present (`409` if not). Returns `202` with the job. Creates a new transcript version on success.

---

## 5. Transcript

### `GET /meetings/{id}/transcript`

Query: `format=json|text|srt|vtt` (default `json`), `offset`, `limit` (segments, default 500, max 2000).

```json
{
  "transcript_id": "7d2c…",
  "version": 1,
  "meeting_id": "0b0f…",
  "language": "en",
  "language_probability": 0.98,
  "duration_seconds": 1842.5,
  "real_time_factor": 0.24,
  "asr": { "provider": "faster_whisper", "model": "small", "compute_type": "int8" },
  "diarization": { "provider": "pyannote", "model": "speaker-diarization-community-1" },
  "capability_notes": {},
  "speakers": [
    { "id": "a1…", "label": "SPEAKER_00", "display_name": "Ada", "total_speaking_seconds": 612.4, "segment_count": 88 }
  ],
  "segments": [
    {
      "id": 42,
      "sequence": 12,
      "start_ms": 84210,
      "end_ms": 89150,
      "speaker_id": "a1…",
      "text": "So we agreed to move the launch to the fourteenth of November.",
      "is_low_confidence": false
    }
  ],
  "offset": 0,
  "limit": 500,
  "total": 268
}
```

`format=srt|vtt|text` returns the corresponding media type with `Content-Disposition: attachment`. Those formats include speaker prefixes when diarization exists.

### `GET /meetings/{id}/transcript/search`

`?q=launch&limit=20`. Uses PostgreSQL full-text search over the active transcript.

```json
{
  "query": "launch",
  "total": 3,
  "hits": [
    {
      "segment_id": 42,
      "start_ms": 84210,
      "end_ms": 89150,
      "speaker_label": "SPEAKER_00",
      "snippet": "…we agreed to move the <mark>launch</mark> to the fourteenth…",
      "rank": 0.87
    }
  ]
}
```

### `PATCH /meetings/{id}/speakers/{speaker_id}`

```json
{ "display_name": "Ada Lovelace" }
```

`display_name: null` clears the name. Returns the speaker. This is the only way a speaker is ever named — the system does not guess names from context.

---

## 6. Intelligence

### `GET /meetings/{id}/intelligence`

`404 not_found` with `code=intelligence_not_ready` if no active run exists. Includes provenance so a reviewer can see exactly what produced the result.

```json
{
  "intelligence_id": "e3b9…",
  "meeting_id": "0b0f…",
  "transcript_id": "7d2c…",
  "version": 1,
  "status": "ready",
  "llm": { "provider": "openai", "model": "gpt-6-luna", "prompt_version": "2026-11-02.1", "schema_version": "1.0.0" },
  "usage": { "input_tokens": 7420, "output_tokens": 1810, "cost_usd": 0.00165, "latency_ms": 4180, "attempt_count": 1 },
  "quality": { "grounding_failures": 1, "items_dropped": 1, "duplicates_merged": 0, "chunk_count": 1 },
  "summary_short": "The team agreed to move the launch to 14 November and assigned the migration and pricing updates to Ada and Ravi.",
  "summary_detailed": "…",
  "topics": ["launch planning", "pricing", "migration"],
  "key_points": [
    {
      "id": "b7…",
      "sequence": 0,
      "text": "The launch date moved from 7 to 14 November.",
      "evidence": [
        { "segment_id": 42, "start_ms": 84210, "end_ms": 89150, "quote": "we agreed to move the launch to the fourteenth of November", "char_start": 12, "char_end": 73 }
      ]
    }
  ],
  "decisions": [
    {
      "id": "d4…",
      "sequence": 0,
      "text": "Launch moved to 14 November.",
      "rationale": "Two weeks are needed for the pricing review.",
      "made_by_speaker_id": "a1…",
      "made_by_speaker_label": "SPEAKER_00",
      "confidence": 0.82,
      "evidence": [
        { "segment_id": 42, "start_ms": 84210, "end_ms": 89150, "quote": "we agreed to move the launch to the fourteenth of November", "char_start": 12, "char_end": 73 }
      ]
    }
  ],
  "action_items": [
    {
      "id": "61…",
      "sequence": 0,
      "title": "Migrate the billing service",
      "description": "Move billing to the new cluster before the launch.",
      "owner_speaker_id": "a1…",
      "owner_label": "SPEAKER_00",
      "owner_resolution": "matched_speaker",
      "owner_text": "Ada, can you take the migration?",
      "due_date": "2026-11-12",
      "due_date_text": "before the fourteenth",
      "due_date_precision": "day",
      "priority": "high",
      "status": "open",
      "confidence": 0.79,
      "is_user_edited": false,
      "blocked_by": [],
      "evidence": [
        { "segment_id": 51, "start_ms": 102400, "end_ms": 108900, "quote": "Ada, can you take the migration?", "char_start": 0, "char_end": 33 }
      ]
    }
  ]
}
```

### `GET /meetings/{id}/decisions`

`{ "items": [...], "total": n }` — decisions with evidence, for a focused UI panel.

### `GET /meetings/{id}/action-items`

Same shape as `/action-items` filtered by `meeting_id`.

### `POST /meetings/{id}/intelligence`

Body optional: `{ "force": false }`. Requires an active ready transcript (`409 transcript_not_ready`). If an analysis is already running, returns the existing job (`202`) rather than duplicating work. If the LLM is unconfigured, `503 llm_not_configured`.

---

## 7. Action items

### `GET /action-items`

Query: `page`, `page_size`, `meeting_id`, `status` (repeatable), `priority`, `owner_speaker_id`, `assigned` (`true|false`), `overdue` (`true`), `due_before`, `due_after`, `q`, `sort` (`due_date`,`created_at`,`priority`,`status`).

```json
{
  "items": [
    {
      "id": "61…",
      "meeting_id": "0b0f…",
      "meeting_title": "Q4 roadmap sync",
      "title": "Migrate the billing service",
      "owner_speaker_id": "a1…",
      "owner_display_name": "Ada Lovelace",
      "owner_resolution": "matched_speaker",
      "due_date": "2026-11-12",
      "due_date_precision": "day",
      "priority": "high",
      "status": "open",
      "is_user_edited": false,
      "evidence_count": 1
    }
  ],
  "page": 1, "page_size": 20, "total": 1, "total_pages": 1
}
```

### `POST /action-items`

For items a human adds after reading the transcript. `meeting_id` required and must be owned. `owner_speaker_id` must belong to the meeting's active transcript. Evidence is **not** accepted from clients — a manual item has no evidence and is marked `intelligence_id = null`.

```json
{
  "meeting_id": "0b0f…",
  "title": "Send updated pricing deck",
  "description": null,
  "owner_speaker_id": "a1…",
  "due_date": "2026-11-10",
  "priority": "medium"
}
```

`201` → action item.

### `PATCH /action-items/{id}`

Any subset of: `title`, `description`, `owner_speaker_id` (nullable), `due_date` (nullable), `priority`, `status`. Sets `is_user_edited = true` and writes an audit row with before/after values.

**Re-analysis does not overwrite user edits.** A new intelligence version is created; items with `is_user_edited = true` are re-linked by `(title similarity, meeting)` where possible and otherwise preserved as manual items. This rule is tested explicitly in Stage 6.

### `PUT /action-items/{id}/dependencies`

```json
{ "blocker_ids": ["8f21…", "9a02…"] }
```

Replaces the set atomically. Rejects self-reference, cycles, and items from another meeting (`422 dependency_cycle`, `422 cross_meeting_dependency`).

### `GET /action-items/export`

`?format=csv&status=open&overdue=true` → `text/csv` with columns: `meeting_title, meeting_date, title, description, owner, owner_resolution, due_date, due_date_text, due_date_precision, priority, status, evidence_quote, evidence_start_ms`.

---

## 8. Search

### `GET /search`

`?q=migration&scope=all|meetings|transcripts|action_items&limit=20`

```json
{
  "query": "migration",
  "results": {
    "meetings": [ { "id": "0b0f…", "title": "Q4 roadmap sync", "snippet": "…migration of the billing service…", "rank": 0.61 } ],
    "transcripts": [ { "meeting_id": "0b0f…", "meeting_title": "Q4 roadmap sync", "segment_id": 51, "start_ms": 102400, "snippet": "…take the <mark>migration</mark>?", "rank": 0.74 } ],
    "action_items": [ { "id": "61…", "title": "Migrate the billing service", "meeting_title": "Q4 roadmap sync" } ]
  },
  "total": 3
}
```

Every query is scoped by `owner_id` inside the SQL; there is no post-filter in Python. Transcript results are limited to active transcripts.

---

## 9. Dashboard and metadata

### `GET /dashboard/summary`

```json
{
  "meetings": { "total": 12, "ready": 10, "processing": 1, "failed": 1 },
  "action_items": { "open": 18, "in_progress": 4, "overdue": 3, "done": 9 },
  "recent_meetings": [ { "id": "…", "title": "Q4 roadmap sync", "status": "ready", "created_at": "…" } ],
  "upcoming_due": [ { "id": "61…", "title": "Migrate the billing service", "due_date": "2026-11-12", "meeting_title": "Q4 roadmap sync" } ]
}
```

Computed with three aggregate queries, not by loading rows into the API process.

### `GET /meta`

```json
{
  "api_version": "1.0.0",
  "git_sha": "a1b2c3d",
  "environment": "production",
  "schema_version": "1.0.0",
  "prompt_version": "2026-11-02.1",
  "asr": { "provider": "faster_whisper", "default_model": "small", "diarization_enabled": false },
  "llm": { "provider": "openai", "default_model": "gpt-6-luna" }
}
```

Exposes no secrets, but it does expose which capabilities are active — used by the UI to explain why speaker labels are absent.

---

## 10. Health and metrics

| Endpoint | Behaviour |
|---|---|
| `GET /health/live` | `200 {"status":"ok"}` if the process is serving. No dependency checks |
| `GET /health/ready` | Checks DB (`SELECT 1`), Redis (`PING`), object storage (bucket HEAD). `200` when all pass; `503` with a per-dependency map otherwise |
| `GET /metrics` | Prometheus text format; unauthenticated but bound to the internal network in production |

---

## 11. Export format (versioned)

`GET /meetings/{id}/export?format=json` returns `application/json` with `Content-Disposition: attachment; filename="q4-roadmap-sync.json"`.

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-11-02T10:00:00Z",
  "generator": { "api_version": "1.0.0", "git_sha": "a1b2c3d" },
  "meeting": { "id": "0b0f…", "title": "Q4 roadmap sync", "description": null, "meeting_date": "2026-11-01T15:00:00Z", "duration_seconds": 1842.5, "language": "en" },
  "audio": { "original_filename": "sync.m4a", "size_bytes": 41232201, "codec": "aac", "sample_rate": 44100, "channels": 2, "sha256": "…", "purged": false },
  "transcript": {
    "asr": { "provider": "faster_whisper", "model": "small", "compute_type": "int8", "real_time_factor": 0.24 },
    "diarization": { "provider": "pyannote", "model": "speaker-diarization-community-1" },
    "speakers": [ { "id": "a1…", "label": "SPEAKER_00", "display_name": "Ada Lovelace" } ],
    "segments": [ { "id": 42, "start_ms": 84210, "end_ms": 89150, "speaker_id": "a1…", "speaker_label": "SPEAKER_00", "text": "…" } ]
  },
  "intelligence": {
    "llm_model": "gpt-6-luna",
    "prompt_version": "2026-11-02.1",
    "summary_short": "…",
    "summary_detailed": "…",
    "topics": ["launch planning"],
    "key_points": [ { "text": "…", "evidence": [ { "segment_id": 42, "start_ms": 84210, "quote": "…", "char_start": 12, "char_end": 73 } ] } ],
    "decisions": [ { "text": "…", "rationale": null, "made_by_speaker_label": "SPEAKER_00", "confidence": 0.82, "evidence": [ ] } ],
    "action_items": [ { "title": "…", "owner_label": "SPEAKER_00", "owner_resolution": "matched_speaker", "due_date": "2026-11-12", "due_date_text": "before the fourteenth", "due_date_precision": "day", "priority": "high", "status": "open", "confidence": 0.79, "blocked_by_titles": [], "evidence": [ ] } ]
  },
  "quality": { "grounding_failures": 1, "items_dropped": 1, "unassigned_items": 2 }
}
```

Other formats: `md` (human-readable report with evidence quotes inline), `txt` (timestamped transcript), `srt`/`vtt` (subtitles with speaker prefixes). `model_dump` of the response schemas produces this document; the schema version is bumped for any breaking change.

---

## 12. Compatibility and client contracts

- The Streamlit client generates no code; it validates golden fixtures against its own DTOs in tests. This keeps the UI decoupled while catching drift.
- Deprecation policy: additive fields any time; removals/renames only with a version bump and one release of overlap.
- All list endpoints are stable under pagination; clients must not assume page contents persist across requests.
- No endpoint returns a permanent audio URL. `GET /meetings/{id}/audio` is deliberately absent; playback/download uses a short-lived presigned URL embedded in meeting detail only when `audio.purged = false`.
