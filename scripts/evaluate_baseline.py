"""
Baseline evaluator for Cross-Check AI.

Runs the curated evaluation set and writes repeatable metrics for tuning.
Default mode is rule-first without LLM/embedding so the baseline is fast and
deterministic. Use --llm when checking the Groq-assisted recall layer.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("PRELOAD_EMBEDDING", "0")
os.environ.setdefault("MAX_LLM_NODES_PER_TREE", "1")
os.environ.setdefault("LLM_TIMEOUT_SEC", "5")

from agents.agent2_detector import detect  # noqa: E402

LABELS = ("PASS", "WARNING", "VIOLATION")
RISK_LABELS = {"WARNING", "VIOLATION"}


def load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(cases: list[dict], enable_llm: bool = False) -> list[dict]:
    rows = []
    for case in cases:
        result = detect(
            case["text"],
            language=case.get("language", "ko"),
            enable_llm=enable_llm,
            enable_embedding=False,
        )
        pred = result.overall
        expected = case["label"]
        rows.append({
            "id": case["id"],
            "category": case.get("category", ""),
            "expected": expected,
            "predicted": pred,
            "exact_match": expected == pred,
            "expected_risk": expected in RISK_LABELS,
            "predicted_risk": pred in RISK_LABELS,
            "risk_caught": (expected not in RISK_LABELS) or (pred in RISK_LABELS),
            "risk_score": result.risk_score,
            "violations": len(result.violations),
            "warnings": len(result.warnings),
            "elapsed_ms": result.elapsed_ms,
            "top_reason": (
                result.violations[0].reason if result.violations
                else result.warnings[0].reason if result.warnings
                else ""
            ),
            "text": case["text"],
            "rationale": case.get("rationale", ""),
        })
    return rows


def metrics(rows: list[dict]) -> dict:
    n = len(rows)
    exact = sum(r["exact_match"] for r in rows)
    expected_risk = [r for r in rows if r["expected_risk"]]
    expected_violation = [r for r in rows if r["expected"] == "VIOLATION"]
    expected_pass = [r for r in rows if r["expected"] == "PASS"]
    false_negative_risk = [r for r in expected_risk if not r["predicted_risk"]]
    false_positive_risk = [r for r in expected_pass if r["predicted_risk"]]
    violation_caught = [r for r in expected_violation if r["predicted_risk"]]

    confusion = Counter((r["expected"], r["predicted"]) for r in rows)
    return {
        "total": n,
        "exact_accuracy": exact / n if n else 0.0,
        "risk_recall_warning_or_violation": (
            (len(expected_risk) - len(false_negative_risk)) / len(expected_risk)
            if expected_risk else 0.0
        ),
        "violation_recall_not_pass": (
            len(violation_caught) / len(expected_violation)
            if expected_violation else 0.0
        ),
        "pass_specificity": (
            (len(expected_pass) - len(false_positive_risk)) / len(expected_pass)
            if expected_pass else 0.0
        ),
        "false_negative_risk_ids": [r["id"] for r in false_negative_risk],
        "false_positive_risk_ids": [r["id"] for r in false_positive_risk],
        "confusion": {f"{a}->{b}": confusion[(a, b)] for a in LABELS for b in LABELS},
    }


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "category", "expected", "predicted", "exact_match",
        "expected_risk", "predicted_risk", "risk_score",
        "violations", "warnings", "elapsed_ms", "top_reason",
        "text", "rationale",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        default=str(ROOT / "data" / "evaluation" / "test_cases_ko.json"),
        help="Path to evaluation JSON cases.",
    )
    parser.add_argument("--llm", action="store_true", help="Enable Groq LLM layer.")
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "evaluation" / "baseline_results.csv"),
        help="CSV output path.",
    )
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    rows = evaluate(cases, enable_llm=args.llm)
    summary = metrics(rows)

    out_path = Path(args.out)
    write_csv(rows, out_path)
    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("Cross-Check AI Baseline Evaluation")
    print(f"cases      : {len(cases)}")
    print(f"llm        : {'ON' if args.llm else 'OFF'}")
    print(f"csv        : {out_path}")
    print(f"summary    : {summary_path}")
    print("-" * 72)
    print(f"exact accuracy             : {summary['exact_accuracy']:.3f}")
    print(f"risk recall (WARN/VIOL)    : {summary['risk_recall_warning_or_violation']:.3f}")
    print(f"violation recall (not PASS): {summary['violation_recall_not_pass']:.3f}")
    print(f"pass specificity           : {summary['pass_specificity']:.3f}")
    print(f"false negatives            : {summary['false_negative_risk_ids']}")
    print(f"false positives            : {summary['false_positive_risk_ids']}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
