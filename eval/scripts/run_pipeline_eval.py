#!/usr/bin/env python3
"""Conformance evaluation for the deterministic extraction path.

This measures the rule-based fallback, schema validation, and evidence
verification on three small synthetic transcripts. It is **not** a benchmark of
LLM extraction quality, ASR accuracy, or diarization, and the report says so.
The point is to make the pipeline's grounding guarantees falsifiable and
reproducible without an API key.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))

from app.providers.llm import RuleBasedLLM, SegmentView  # noqa: E402
from app.schemas.llm import ActionPayload, DecisionPayload  # noqa: E402
from app.services.grounding import verify_quote  # noqa: E402

FIXTURES = ROOT / "fixtures" / "transcripts"
REPORT_PATH = ROOT / "reports" / "pipeline_conformance.json"
MATCH_THRESHOLD = 0.6


def norm(text: str) -> str:
    return " ".join(text.lower().split()).strip(".,;:!?")


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, norm(left), norm(right)).ratio()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def match_items(
    predictions: list[dict],
    expected: list[dict],
    predicted_key: str,
) -> tuple[list[dict], set[int], int, int]:
    used: set[int] = set()
    matched: list[dict] = []
    owner_hits = 0
    owner_total = 0

    for reference in expected:
        best_index: int | None = None
        best_score = 0.0
        for index, prediction in enumerate(predictions):
            if index in used:
                continue
            score = similarity(
                str(prediction.get(predicted_key, "")), str(reference.get("text", ""))
            )
            if score > best_score:
                best_score = score
                best_index = index
        if best_index is not None and best_score >= MATCH_THRESHOLD:
            used.add(best_index)
            matched.append(
                {
                    "similarity": round(best_score, 3),
                    "expected": reference["text"],
                    "predicted": predictions[best_index][predicted_key],
                }
            )
            if reference.get("owner"):
                owner_total += 1
                if norm(str(predictions[best_index].get("owner_mention") or "")) == norm(
                    reference["owner"]
                ):
                    owner_hits += 1

    return matched, used, owner_hits, owner_total


def evaluate_sample(payload: dict) -> dict:
    segments = [
        SegmentView(
            id=segment["id"],
            start_ms=segment["start_ms"],
            speaker_label=segment.get("speaker"),
            text=segment["text"],
        )
        for segment in payload["segments"]
    ]
    segment_text = {segment["id"]: segment["text"] for segment in payload["segments"]}

    model = RuleBasedLLM()
    decisions = DecisionPayload.model_validate(model.generate("decisions", segments).payload)
    actions = ActionPayload.model_validate(model.generate("actions", segments).payload)
    predicted_decisions = [item.model_dump() for item in decisions.items]
    predicted_actions = [item.model_dump() for item in actions.items]

    def grounding(items: list[dict]) -> tuple[int, int]:
        verified = 0
        invented = 0
        for item in items:
            evidence = item.get("evidence") or []
            supported = False
            for reference in evidence:
                if verify_quote(segment_text.get(reference["segment_id"], ""), reference["quote"]):
                    supported = True
                    break
            if supported:
                verified += 1
            mention = item.get("owner_mention")
            if mention and not any(
                mention.lower() in reference["quote"].lower() for reference in evidence
            ):
                invented += 1
        return verified, invented

    decision_verified, decision_invented = grounding(predicted_decisions)
    action_verified, action_invented = grounding(predicted_actions)

    decision_matches, decision_used, _, _ = match_items(
        predicted_decisions, payload["expected"]["decisions"], "text"
    )
    action_matches, action_used, owner_hits, owner_total = match_items(
        predicted_actions, payload["expected"]["actions"], "title"
    )

    return {
        "sample_id": payload["sample_id"],
        "description": payload.get("description", ""),
        "counts": {
            "predicted_decisions": len(predicted_decisions),
            "expected_decisions": len(payload["expected"]["decisions"]),
            "predicted_actions": len(predicted_actions),
            "expected_actions": len(payload["expected"]["actions"]),
        },
        "decisions": {
            "true_positives": len(decision_matches),
            "false_positives": len(predicted_decisions) - len(decision_matches),
            "false_negatives": len(payload["expected"]["decisions"]) - len(decision_matches),
            "matches": decision_matches,
        },
        "actions": {
            "true_positives": len(action_matches),
            "false_positives": len(predicted_actions) - len(action_matches),
            "false_negatives": len(payload["expected"]["actions"]) - len(action_matches),
            "owner_hits": owner_hits,
            "owner_total": owner_total,
            "matches": action_matches,
        },
        "grounding": {
            "predicted_items": len(predicted_decisions) + len(predicted_actions),
            "verified_items": decision_verified + action_verified,
            "invented_owners": decision_invented + action_invented,
        },
        "unmatched_predictions": [
            item["text"] for index, item in enumerate(predicted_decisions) if index not in decision_used
        ]
        + [
            item["title"] for index, item in enumerate(predicted_actions) if index not in action_used
        ],
    }


def main() -> int:
    samples = [
        evaluate_sample(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(FIXTURES.glob("*.json"))
    ]
    if not samples:
        print("No fixtures found.", file=sys.stderr)
        return 1

    decision_tp = sum(sample["decisions"]["true_positives"] for sample in samples)
    decision_fp = sum(sample["decisions"]["false_positives"] for sample in samples)
    decision_fn = sum(sample["decisions"]["false_negatives"] for sample in samples)
    action_tp = sum(sample["actions"]["true_positives"] for sample in samples)
    action_fp = sum(sample["actions"]["false_positives"] for sample in samples)
    action_fn = sum(sample["actions"]["false_negatives"] for sample in samples)

    decision_precision = _ratio(decision_tp, decision_tp + decision_fp)
    decision_recall = _ratio(decision_tp, decision_tp + decision_fn)
    action_precision = _ratio(action_tp, action_tp + action_fp)
    action_recall = _ratio(action_tp, action_tp + action_fn)

    predicted_items = sum(sample["grounding"]["predicted_items"] for sample in samples)
    verified_items = sum(sample["grounding"]["verified_items"] for sample in samples)
    invented_owners = sum(sample["grounding"]["invented_owners"] for sample in samples)
    owner_hits = sum(sample["actions"]["owner_hits"] for sample in samples)
    owner_total = sum(sample["actions"]["owner_total"] for sample in samples)

    aggregate = {
        "sample_count": len(samples),
        "decisions": {
            "precision": decision_precision,
            "recall": decision_recall,
            "f1": _f1(decision_precision, decision_recall),
            "true_positives": decision_tp,
            "false_positives": decision_fp,
            "false_negatives": decision_fn,
        },
        "actions": {
            "precision": action_precision,
            "recall": action_recall,
            "f1": _f1(action_precision, action_recall),
            "true_positives": action_tp,
            "false_positives": action_fp,
            "false_negatives": action_fn,
        },
        "owner_accuracy": _ratio(owner_hits, owner_total) if owner_total else None,
        "owner_evaluated_items": owner_total,
        "evidence_grounding_rate": _ratio(verified_items, predicted_items),
        "invented_owner_count": invented_owners,
    }

    report = {
        "report": "pipeline-conformance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "component": "RuleBasedLLM + Pydantic validation + quote verifier",
        "dataset": "3 synthetic text fixtures in eval/fixtures/transcripts",
        "not_measured": [
            "LLM extraction quality",
            "ASR word error rate",
            "speaker diarization error rate",
            "real meeting audio",
        ],
        "limitations": [
            "Synthetic transcripts were written by the author, not collected meetings.",
            "The deterministic fallback is not the production model; these numbers do not "
            "predict LLM performance.",
            "Three samples are too few for statistical claims.",
        ],
        "aggregate": aggregate,
        "samples": samples,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Pipeline conformance — {len(samples)} synthetic transcripts")
    print(
        f"  decisions  P={aggregate['decisions']['precision']:.3f} "
        f"R={aggregate['decisions']['recall']:.3f} F1={aggregate['decisions']['f1']:.3f}"
    )
    print(
        f"  actions    P={aggregate['actions']['precision']:.3f} "
        f"R={aggregate['actions']['recall']:.3f} F1={aggregate['actions']['f1']:.3f}"
    )
    print(f"  owner accuracy      {aggregate['owner_accuracy']}")
    print(f"  evidence grounding  {aggregate['evidence_grounding_rate']:.3f}")
    print(f"  invented owners     {aggregate['invented_owner_count']}")
    print(f"Report: {REPORT_PATH.relative_to(ROOT.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
