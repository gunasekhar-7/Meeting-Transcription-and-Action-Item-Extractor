# Evaluation and Benchmarking Plan

**Version:** 1.0 (Stage 0) · **Executed:** Stage 8 · **Principle:** every published number has an artifact.

---

## 1. Why this document exists first

The project's claim is not "it transcribes audio". It is "the extracted commitments are trustworthy and measurably good." That claim is only credible if the evaluation was designed before the prompts were tuned, on data the prompts were not written against, with negative cases where the correct answer is *nothing*.

Three failure modes this plan is built to prevent:

1. **Tuning on the test set.** Prompts are written against development samples; the evaluation set is held out and only run at Stage 8.
2. **Metric laundering.** Reporting only extraction recall (easy) and omitting precision (which punishes invented tasks), or reporting WER on clean audio only.
3. **Unfalsifiable prose.** "Summaries are high quality" with no rubric, no raters, no numbers.

## 2. Evaluation sets

### 2.1 `ami-ihm-mini` — ASR and diarization reference

**Source:** AMI Meeting Corpus, CC BY 4.0, [groups.inf.ed.ac.uk/ami/download](https://groups.inf.ed.ac.uk/ami/download/).
**Selection:** 15 scenario meetings spanning different groups and recording conditions, using the IHM **Mix-Headset** channel (a single mixed track, which is what a user would actually upload) plus the corresponding manual annotation.

Why AMI: real four-person meetings, manual orthographic transcripts, manual speaker segments, redistributable licence, and published DER/WER baselines for comparison. It is the most defensible public reference available.

**What it does not test:** it is scripted scenario meetings with headset microphones; it is not a noisy conference room, and it is not spontaneous business conversation. That gap is what the second set covers.

**Preprocessing (recorded in `eval/datasets/manifests/ami-ihm-mini.json`):**
- Decode to 16 kHz mono WAV.
- Manual transcript → normalised JSONL of `(speaker, start, end, text)`.
- Manual speaker annotation → RTTM.
- No audio is committed; a download script fetches and verifies SHA-256.

### 2.2 `self-recorded-v1` — extraction ground truth

**Source:** 12 meetings recorded by the author with consenting participants (2–4 speakers, 8–15 minutes). Consent form and template scripts live in `eval/scripts/record_kit/`.

"Self-recorded" does not mean "scripted read-aloud". Each meeting follows a topic outline with **planted facts** (a decision, a named owner, an explicit date) delivered in natural conversation, plus unscripted discussion. This gives ground truth without making the language artificial.

**Composition (12 meetings):**

| # | Type | Planted content | Tests |
|---|---|---|---|
| 4 | Standard planning | 3–5 decisions, 4–6 action items with owner + explicit date | Core extraction |
| 2 | Unassigned work | Tasks discussed with no owner named | `unassigned` correctness |
| 2 | Vague timing | "soon", "after the holidays", "end of next sprint" | Deadline precision, no invented dates |
| 2 | Decision-light | Discussion with no decisions, 1–2 tasks | False-positive control |
| 1 | Task-free | Status update, no commitments | Zero-item output |
| 1 | Long, multi-topic | 15 min, topic shifts, cross-references | Chunking and merge |

**Annotation format** (`eval/annotations/self-recorded-v1/<meeting>.jsonl`):

```json
{
  "kind": "action_item",
  "title": "Migrate the billing service",
  "owner": "SPEAKER_01",
  "owner_stated_as": "Ada",
  "due_date": "2026-11-12",
  "due_date_text": "before the fourteenth",
  "due_date_precision": "day",
  "priority": "high",
  "evidence_segment_hint": 51,
  "evidence_quote": "Ada, can you take the migration before the fourteenth?"
}
```

Negative cases are annotated explicitly (`"kind": "no_decision"` with a rationale) so that emitting a decision there is measurable as a false positive.

**Annotation quality:** the author annotates all 12; a second reviewer independently annotates 4 (30%), and Cohen's κ is reported for action-item identification. A κ below 0.6 triggers a rubric revision before evaluation, not after.

### 2.3 Development set (never reported)

2 AMI meetings and 2 self-recorded meetings are reserved for prompt development. They are excluded from every reported metric. The split is recorded in the dataset manifest by `sample_ref`.

## 3. Metrics

### 3.1 Speech recognition

| Metric | Definition | Tool |
|---|---|---|
| WER | `(S + D + I) / N` after normalisation | `jiwer.wer` |
| CER | Character-level equivalent | `jiwer.cer` |
| RTF | `processing_seconds / audio_seconds` | recorded per transcript |
| Latency | Wall clock per sample, and median/p95 across the set | runner |

**Normalisation v1** (`eval/scripts/normalize.py`, versioned; changing it requires re-running every reported number):
1. Unicode NFKC; collapse whitespace.
2. Lowercase.
3. Remove punctuation except intra-word apostrophes and hyphens.
4. Expand a fixed list of numerals and common contractions (`14` → `fourteen`) for both reference and hypothesis.
5. Remove filler tokens (`uh`, `um`, `erm`) from **both** sides — reported separately as a sensitivity check.

Reported both raw and normalised. The normaliser is unit-tested so a silent change cannot alter published numbers.

### 3.2 Diarization

| Metric | Definition |
|---|---|
| DER | `(missed + false_alarm + confusion) / total_speech`, `pyannote.metrics`, collar 0.25 s, overlap scored (`skip_overlap=False`) |
| Components | Missed speech, false alarm, speaker confusion reported separately |
| Speaker-count error | `predicted_speaker_count - reference_speaker_count` per meeting |

Reported for `community-1` only if diarization is enabled; otherwise marked `not run` with the reason (no HF token in the evaluation environment).

**Known limitation reported alongside:** overlapping speech is scored but the system cannot attribute it; confusion is expected to rise on overlap-heavy samples.

### 3.3 Extraction

Matching is the hard part; the rule must be written down before looking at results.

**Strict match** — a predicted action item matches a reference item when:
1. Title similarity ≥ 0.80 (`rapidfuzz.fuzz.token_set_ratio`, normalised), **and**
2. Owner matches exactly (both `unassigned`, or the same resolved speaker after mapping reference names to diarized labels), **and**
3. If the reference has an exact `due_date`, the predicted date equals it.

**Semantic match** — conditions 1 and 2 only, using similarity ≥ 0.70. Reported separately; never the headline.

**Metrics:** micro-averaged precision, recall, F1 across all meetings; per-meeting breakdown; owner accuracy on items where the reference states an owner; due-date accuracy on items with an exact reference date; decision F1 under the same strict/semantic split.

**Grounding:** for every stored item, the evidence quote must be a normalised substring of the cited segment. Rate = `verified_links / stored_items`. Must be 1.000 by construction; the measured value detects verifier bugs.

**Anti-hallucination metrics:**
- `invented_owner_count`: items whose stored owner name does not appear in any evidence quote, or whose owner is a speaker who was not the one addressed. Manually audited.
- `fabricated_deadline_count`: a resolved `due_date` with no supporting phrase.
- `phantom_decision_count`: decisions emitted for meetings annotated as decision-free.

Target for all three: **0**. Any non-zero result is a defect with a named cause, reported in the failure analysis.

### 3.4 Summarisation

Automated similarity metrics (ROUGE) are close to meaningless for abstractive meeting summaries, so they are not used as a headline. Instead:

- **Factual consistency:** a rater marks each summary claim as supported / unsupported / contradicted by the transcript. Report `unsupported_claims / total_claims`.
- **Coverage:** proportion of annotated key points represented (semantically) in the summary.
- **Usefulness:** 1–5 rubric (would a participant accept this as an accurate recap?), mean and distribution.
- **Length compliance:** short summary ≤ 80 words, enforced and measured.

Two raters on all 12 self-recorded meetings; disagreements resolved by discussion, with the initial agreement rate reported.

### 3.5 Cost and performance

Per meeting: ASR seconds and RTF, LLM input/output tokens, computed cost, end-to-end wall clock, and retry count. Aggregated as median and p95. Reported per configuration, because "cost" without a model and prompt version is meaningless.

## 4. Configurations to compare

| ID | ASR | Diarization | LLM / prompt | Purpose |
|---|---|---|---|---|
| C1 | `tiny` int8 | off | — | Speed floor, quality floor |
| C2 | `base` int8 | off | — | Cheap default check |
| C3 | `small` int8 | off | — | Proposed default |
| C4 | `distil-large-v3` | off | — | Accuracy/CPU trade-off |
| C5 | hosted ASR | hosted | — | Upper bound for ASR quality and cost |
| C6 | best of above | `community-1` | prompt v1 | Baseline intelligence |
| C7 | C6 ASR | `community-1` | prompt v2 | Prompt iteration effect |
| C8 | C7 | `community-1` | v2, single-call | Tests the three-call design |

Not every configuration runs on every set (hosted ASR on all 15 AMI meetings is affordable; `distil-large-v3` on 12 recordings may not be). The report states which cells were run and which were skipped for cost or hardware reasons.

## 5. Procedure

1. Freeze `git` SHA, model revisions, prompt version, normaliser version.
2. Download and verify corpora; build manifests.
3. Run the pipeline via the public API or the service layer (identical code path; the API is the default to also exercise serialisation).
4. Persist results to `evaluation_runs` / `evaluation_results`.
5. Generate `eval/reports/<run-id>.json` and `.md` from the database — never by hand.
6. Write the failure analysis by reading actual samples, not by guessing.
7. Update README only by copying values from the report.

**Repeatability:** ASR runs with greedy decoding / beam 5 and no sampling; LLM temperature 0 where supported. Residual nondeterminism in hosted APIs is acknowledged; each configuration is run once for the headline and twice for LLM-only metrics when cost permits, reporting variance.

## 6. Failure analysis (mandatory section)

For each configuration, the report includes the top five error types with verbatim examples (redacted where needed) and a root-cause classification:

| Class | Example | Fix direction |
|---|---|---|
| ASR error | Name misheard ("Ada" → "Aida") | Owner matching alias, model upgrade |
| Segmentation | Speaker change mid-sentence mis-assigned | Alignment improvement, low-confidence flag |
| Extraction miss | Implicit commitment not stated imperatively | Prompt guidance on implicit commitments |
| Extraction false positive | Suggestion treated as a commitment | Tighten criteria, require commitment language |
| Resolution error | "next sprint" mapped to a wrong date | Remove derivation, keep precision only |

This section is where the project earns credibility. A report with 0.68 F1 and a clear account of why is stronger than 0.9 with no analysis.

## 7. Anti-fabrication policy

1. **No number appears in the README, resume bullets, or documentation without a path to a committed artifact.**
2. Estimates are labelled "estimate" and show their derivation.
3. A metric that could not be computed is `not measured` **with the reason** (no HF token, no reference annotation, cost).
4. Targets are stated before measurement and are not revised afterwards. Missing a target is a reported result.
5. Screenshots and demo videos show real runs of this code, on the sample data in the repository.
6. The evaluation harness is committed and runnable; a reviewer can reproduce or contradict the numbers.

## 8. Ethics, consent, privacy

- Self-recorded participants sign a consent form covering use in a public portfolio; names are replaced with speaker labels in committed artifacts.
- No employer, client, or third-party meeting audio is used.
- AMI/ICSI audio is not redistributed; only derived annotations and the download script are committed, with attribution.
- Committed transcripts from self-recorded meetings are reviewed to remove personal or sensitive content.
- Published failure examples are paraphrased when they contain incidental personal information.

## 9. Deliverables from Stage 8

- `eval/datasets/manifests/*.json` — sample lists, hashes, licences, splits.
- `eval/annotations/self-recorded-v1/*.jsonl` — ground truth.
- `eval/scripts/` — download, normalise, metrics, report generation, annotation lint.
- `eval/reports/<run-id>.json` + `.md` — raw and human-readable results.
- `docs/evaluation-results.md` — the one-page summary linked from the README.
- `THIRD_PARTY_NOTICES.md` — corpus and model attribution.

## 10. What this evaluation will not prove

Stated up front, because overclaiming is the failure mode this whole document exists to prevent:

- It will not prove performance on **noisy, far-field, accented, or code-switched** audio beyond the AMI SDM subset, and only if that subset is run.
- It will not prove enterprise-scale concurrency; that is a load test, not an accuracy evaluation.
- It will not prove that a 12-meeting extraction set generalises to another organisation's meeting culture. It is a small, honest sample with reported confidence intervals where appropriate.
- It will not prove that the LLM's confidence scores are calibrated. They are not treated as such.
- It will not prove absence of hallucinations outside the annotated categories; it measures the categories that matter for the product claim.
