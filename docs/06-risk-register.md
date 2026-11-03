# Risk Register

**Version:** 1.0 (Stage 0) · Reviewed at every stage gate · Scoring: likelihood × impact (1–5 each)

---

## 1. Top risks

| ID | Risk | L | I | Score | Trigger (early warning) | Mitigation | Owner |
|---|---|---|---|---|---|---|---|
| R1 | **CPU transcription is too slow for the demo.** `large-v3` int8 on 4 vCPU has an estimated RTF of 1.5–3.0, so a 30-minute meeting could take 45–90 minutes. | 5 | 4 | **20** | Measured RTF > 0.5 with the default model at Stage 2 | Default to `small`/`base` int8; enforce a 20-minute demo sample; ship the hosted-ASR adapter; publish measured RTF instead of claiming real-time; label processing time in the UI | Stage 2 |
| R2 | **Scope exceeds available time**, ending with many half-built stages. | 4 | 5 | **20** | A stage gate slips by > 50%, or Stage 3 starts before Stage 2's gate | Explicit non-goals; sequential gates; timeboxed stages; cut polish before cutting evaluation | All |
| R3 | **LLM model deprecation breaks the demo.** The GPT-4o/4.1 family retires 2027-01-14; hardcoded names become 404s. | 4 | 4 | **16** | Startup model validation warning | Model IDs in config, validated against the provider at startup; no model strings in business logic; prompt/schema versioning; re-run evaluation when the model changes | Stage 3 |
| R4 | **Hallucinated owners or deadlines undermine the core claim.** | 4 | 4 | **16** | Any non-zero `invented_owner_count` in a spot check | Nullable schema fields; owner name must appear in the evidence quote; quote must be a verified substring; negative-case evaluation; drop-and-count rather than store ungrounded items | Stage 3 |
| R5 | **Diarization dependency is too heavy or gated.** `torch` + `torchcodec` adds ~2 GB and requires HF terms acceptance; the install may fail on the target host. | 4 | 3 | **12** | Image > 2 GB or `pip install` failure in CI | Optional extra; default `NullDiarizationProvider`; separate worker image tag; document the HF acceptance step; never make the product's core path depend on it | Stage 2 |
| R6 | **Extraction F1 misses the 0.70 target.** | 3 | 4 | **12** | Stage 8 dev-sample F1 < 0.60 | Iterate prompts on the dev set only; chunking tuning; few-shot examples; report the achieved number and an error analysis rather than redefining success | Stage 8 |
| R7 | **Evidence verification has a bug that lets ungrounded items through** — the most damaging possible defect, because the product's claim is false. | 2 | 5 | **10** | Mutation test survives; grounding rate ≠ 1.0 | Property-based tests over quote/offset handling; explicit tamper tests; verification is a separate tested function, not inline in the task | Stage 3 |
| R8 | **No usable evaluation data** (licensing, consent, or recording failures). | 2 | 5 | **10** | Fewer than 10 self-recorded meetings by mid-Stage 8 | AMI/ICSI are CC BY 4.0 and sufficient for ASR/DER; record in batches from Stage 2; scripted outlines make sessions repeatable | Stage 8 |
| R9 | **Docker build time and image size** make CI slow and the demo fragile. | 4 | 2 | **8** | CI build > 10 min | Multi-stage builds; `uv` cache mounts; separate lightweight API image; only the worker installs ASR extras | Stage 1 |
| R10 | **Flaky integration tests** (container startup, model downloads) erode trust in CI. | 3 | 3 | **9** | A test passes locally and fails in CI twice | Health-checked service containers; fakes for model work; retry only infrastructure readiness, never assertions; deterministic fixtures and clocks | Stage 7 |
| R11 | **Prompt injection from meeting content** manipulates extraction. | 3 | 3 | **9** | A test transcript containing instructions produces an ungrounded item | Transcript delimited as untrusted data with explicit hierarchy; evidence verification bounds damage; documented as a known limitation, not "solved" | Stage 6 |
| R12 | **Secret leakage** into git, logs, or images. | 2 | 5 | **10** | `gitleaks` finding; token in a log line | `.gitignore` from day one; `.env.example` only; startup validation; allowlisted log fields; `gitleaks` + `pip-audit` in CI | Stage 1 |
| R13 | **Cost overrun** from repeated re-analysis or a large model accidentally selected. | 3 | 2 | **6** | Daily cost metric rising without new meetings | Per-meeting token/cost accounting; model allowlist; per-user daily minute cap; hard retry cap | Stage 6 |
| R14 | **PostgreSQL/Redis/MinIO unavailable in the demo environment** during review. | 3 | 3 | **9** | Readiness probe failing | Health checks + restart policy; documented restart runbook; demo works with a precomputed meeting if the LLM is down | Stage 9 |
| R15 | **Over-engineering**: Kubernetes, Kafka, vector DB, microservices added for appearance. | 3 | 4 | **12** | A dependency cannot be justified by a requirement | ADRs require an alternative and consequences; "no new technology without a driver" rule; PR self-review checklist | All |

## 2. Accepted risks (documented, not mitigated)

| Risk | Why accepted | Consequence |
|---|---|---|
| Overlapping speech is attributed to a single speaker | Solving it requires a dedicated overlap-aware model and substantially more scope | DER/collusion errors on overlapping segments; flagged `is_low_confidence` |
| No cross-meeting speaker identity | Voiceprint recognition raises consent and accuracy issues disproportionate to the value | Users rename speakers per meeting |
| No distributed transactions | A reconciliation sweep covers the crash window at a fraction of the complexity | Rare duplicate dispatch, deduped by idempotency key |
| Single-region, single-primary database | HA is not achievable at the demo budget | Downtime during maintenance; documented |
| English-centric evaluation | Corpora and annotators available are English | Other languages inherit the model's quality without a measured claim |
| No tracing (OpenTelemetry) | Correlation IDs cover the debugging need | Harder to profile cross-service latency at scale |

## 3. Review protocol

- Reviewed at every stage gate; a risk that materialises becomes a stage blocker.
- New risks are added with the stage that discovered them.
- Closed risks stay in the table with a resolution note, so the history is auditable.
- Scores are re-assessed after Stage 6 (reliability) and Stage 8 (evaluation), when the largest uncertainties resolve.
