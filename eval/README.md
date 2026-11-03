# Evaluation

## What is measured here

`scripts/run_pipeline_eval.py` runs the **deterministic fallback extractor** plus
Pydantic schema validation and the evidence verifier over three synthetic
transcripts. It reports decision/action precision, recall and F1, owner accuracy,
grounding rate, and the number of invented owners.

Reproduce:

```bash
python eval/scripts/run_pipeline_eval.py
```

Output: `eval/reports/pipeline_conformance.json`.

## What this is not

- It is **not** an LLM quality benchmark. No model API is called.
- It is **not** a WER/CER/DER benchmark. No audio is transcribed.
- Three hand-written transcripts cannot support statistical claims.

The purpose is narrower and defensible: it shows that the deterministic path is
reproducible, that every stored item is quote-verified, and that an unsupported
owner is never emitted. The three fixtures include a negative case with no
commitments and a case where the owner is implicit, which is where naive
extractors invent information.

## Planned (not implemented)

- AMI/ICSI (CC BY 4.0) WER, CER and DER with reference annotations.
- 12 consented, self-recorded meetings for extraction evaluation.
- Prompt/model comparison and a failure-case appendix.

Those require audio ingestion, manual annotation and a funded model account;
they are documented in `docs/05-evaluation-plan.md` and are not claimed as done.
