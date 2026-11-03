# ADR-0007: Model identifiers are configuration; prompt and schema versions are data

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

On 2026-10-14 OpenAI announced the retirement of GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini on **2027-01-14**, with `gpt-6-luna` as the replacement at $0.10/$0.50 per million tokens. `gpt-5-mini` is retired 2026-12-11. A project that hardcodes `gpt-4o-mini` — the default choice in most tutorials — ships code that stops working eight weeks after this repository was created.

More generally, any published extraction metric is a property of `(model, prompt, schema)`, not of "the system". Without recording those, a benchmark cannot be reproduced or compared.

## Decision

1. **Model IDs live in configuration only.** `LLM_MODEL`, `LLM_PROVIDER`, `LLM_ALLOWED_MODELS`, `ASR_MODEL`, `DIARIZATION_MODEL`. No model string appears in business logic.
2. **Startup validation.** The API and workers call the provider's model list at boot (cached, with a short timeout); an unknown or retired model fails fast in production and logs a warning in development. Offline mode skips the check with an explicit log line.
3. **Allowlist enforcement.** Request bodies may request a model only from `LLM_ALLOWED_MODELS` / `ASR_ALLOWED_MODELS`; anything else is `422`. This prevents a caller from selecting an expensive model.
4. **Prompt versions are constants, not file timestamps.** `PROMPT_VERSION = "2026-11-02.1"`, bumped for any behavioural change, recorded on every `meeting_intelligence` row.
5. **Schema versions are explicit.** `SCHEMA_VERSION = "1.0.0"`; the export format has its own version. Breaking schema changes bump the major.
6. **Cost table is versioned.** A price map keyed by model with an effective date, so historical `cost_usd` remains interpretable after pricing changes.
7. **Every evaluation run records `git_sha`, model, prompt version, schema version and hardware.** Comparing runs without them is invalid.

## Consequences

**Positive**

- A provider migration is an environment change plus a re-evaluation, not a code change.
- Benchmark claims are reproducible and comparable.
- Retired or mistyped models fail at startup, not on the first user upload.
- Cost per meeting is auditable historically.

**Negative**

- More configuration surface; a missing `LLM_MODEL` breaks analysis (by design, with a clear error).
- The startup model check adds a network dependency at boot; offline development needs an escape hatch.
- Developers must remember to bump prompt versions, which is easy to forget.

**Mitigations**

- `.env.example` documents every variable with a working default and a comment naming the retirement risk.
- A test asserts that `PROMPT_VERSION` is referenced in the persisted run and that changing it produces a distinct value.
- CI includes a configuration validation test that boots the app with each profile (`local`, `test`, `production`) and asserts clear failure messages.
- The model check is advisory in `ENV=local` and fatal in `ENV=production`.

## Alternatives considered

- **Hardcode current model names.** Rejected: guaranteed breakage within months, and it obscures the fact that quality is model-dependent.
- **Auto-select the newest model at runtime.** Rejected: silent behaviour change between deployments; a benchmark tied to a moving target is worthless.
- **Pin dated snapshots only.** Partially adopted: where a provider offers a dated snapshot, the allowlist may include it, but the default remains a stable alias validated at startup.
