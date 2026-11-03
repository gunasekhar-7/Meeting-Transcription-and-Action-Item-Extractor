# ADR-0009: AMI/ICSI for ASR and DER, self-recorded meetings for extraction ground truth

- **Status:** Accepted
- **Date:** 2026-11-02
- **Stage:** 0

## Context

The evaluation needs (a) audio with reference transcripts and speaker annotations for WER/CER/DER, and (b) meetings with annotated decisions and action items for extraction metrics. It must be legally redistributable in a public repository, and it must not involve employer or third-party confidential recordings.

Options considered:

- **AMI Meeting Corpus.** 100 hours of 4-person scenario meetings; manual orthographic transcripts and speaker annotations; IHM/SDM/MDM channels. Licence confirmed as **CC BY 4.0** on the official download page.
- **ICSI Meeting Corpus.** Real meetings with manual transcripts and speaker annotations; licence page confirms **CC BY 4.0**.
- **LibriSpeech / Common Voice.** Read speech, single speaker, no meeting structure or diarization reference — useless for this product.
- **Scraped podcasts/YouTube.** Unclear licensing, no reference annotations, no ground-truth action items.
- **Synthetic TTS meetings.** Ground truth is exact, but the language is unnatural and the LLM extraction results would not transfer.
- **Collected meetings from the author's workplace.** Rejected outright: consent and confidentiality risk.

## Decision

Two complementary sets:

1. **`ami-ihm-mini`** — 15 AMI meetings, Mix-Headset channel, manual transcript and speaker annotation. Used for WER, CER, DER, RTF and cost.
2. **`self-recorded-v1`** — 12 meetings recorded by the author with consenting participants, following topic outlines with planted and natural content, annotated by the author with 30% second-annotator review. Used for extraction, grounding, and anti-hallucination metrics.

No corpus audio is committed. `eval/scripts/download_ami.py` fetches and verifies it; `eval/datasets/manifests/*.json` records samples, hashes, licence and split. `THIRD_PARTY_NOTICES.md` provides CC BY 4.0 attribution and states the modifications (NXT → JSONL, RTTM extraction, 16 kHz mono conversion).

## Consequences

**Positive**

- Metrics are computed against human references, not model output.
- The licence permits public use with attribution, so the repository can publish derived artifacts.
- AMI's published DER/WER numbers give external context for our results.
- Self-recorded meetings test the actual product behaviour, including negative cases that no public corpus annotates.

**Negative**

- AMI is scripted scenario speech with headset microphones; it overstates real-world ASR quality compared with far-field noisy rooms.
- 12 self-recorded meetings is a small sample; confidence intervals will be wide and must be reported.
- Annotation is labour-intensive (estimated 1.5–2 days) and the author is not a professional annotator.
- Self-recorded audio is not redistributable without participant consent, so the demo sample is limited to excerpts with consent.

**Mitigations**

- Report AMI IHM and, if time permits, the SDM subset to show the far-field gap.
- Report per-meeting variance and a bootstrap confidence interval rather than a single F1.
- Publish the annotation rubric and measure inter-annotator agreement (Cohen's κ); a low κ revises the rubric before results are reported.
- Keep the committed sample short (≤ 3 minutes) and explicitly consented.

## Alternatives considered

- **ICSI only.** Valuable for spontaneity but its audio quality and annotation format are less convenient; kept as an optional extension.
- **Buying a commercial meeting dataset.** Rejected: cost, and most licences forbid redistribution of derived annotations.
- **Fully synthetic generation.** Rejected as the primary set: the extraction task would be trivially easy and the reported F1 would be meaningless.
- **Human-written transcripts only (no audio).** Useful for isolating extraction, and used as a supplementary fixture, but it cannot validate the ASR→alignment→extraction path end to end.
