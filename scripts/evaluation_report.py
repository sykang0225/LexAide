"""
Generate presentation-ready evaluation reports for Cross-Check AI.

The report is intentionally conservative: it separates exact accuracy from
risk-oriented metrics so the Recall-first compliance strategy can be explained
without pretending that every WARNING boundary is solved.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
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


def load_cases(paths: list[Path]) -> list[dict]:
    cases = []
    for path in paths:
        suite = path.stem.replace("test_cases_", "")
        for case in json.loads(path.read_text(encoding="utf-8")):
            item = dict(case)
            item["_suite"] = suite
            cases.append(item)
    return cases


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
        expected_risk = expected in RISK_LABELS
        predicted_risk = pred in RISK_LABELS
        top_reason = (
            result.violations[0].reason if result.violations
            else result.warnings[0].reason if result.warnings
            else ""
        )
        rows.append({
            "suite": case.get("_suite", ""),
            "id": case["id"],
            "language": case.get("language", "ko"),
            "category": case.get("category", ""),
            "expected": expected,
            "predicted": pred,
            "exact_match": expected == pred,
            "expected_risk": expected_risk,
            "predicted_risk": predicted_risk,
            "risk_tp": expected_risk and predicted_risk,
            "risk_fp": (not expected_risk) and predicted_risk,
            "risk_fn": expected_risk and (not predicted_risk),
            "risk_tn": (not expected_risk) and (not predicted_risk),
            "risk_score": result.risk_score,
            "violations": len(result.violations),
            "warnings": len(result.warnings),
            "elapsed_ms": round(result.elapsed_ms, 1),
            "top_reason": top_reason,
            "text": case["text"],
            "rationale": case.get("rationale", ""),
        })
    return rows


def metric_block(rows: list[dict]) -> dict:
    total = len(rows)
    exact = sum(r["exact_match"] for r in rows)
    tp = sum(r["risk_tp"] for r in rows)
    fp = sum(r["risk_fp"] for r in rows)
    fn = sum(r["risk_fn"] for r in rows)
    tn = sum(r["risk_tn"] for r in rows)
    expected_violation = [r for r in rows if r["expected"] == "VIOLATION"]
    violation_caught = [r for r in expected_violation if r["predicted_risk"]]
    confusion = Counter((r["expected"], r["predicted"]) for r in rows)
    return {
        "total": total,
        "exact_accuracy": exact / total if total else 0.0,
        "risk_precision": tp / (tp + fp) if (tp + fp) else 0.0,
        "risk_recall": tp / (tp + fn) if (tp + fn) else 0.0,
        "risk_fpr": fp / (fp + tn) if (fp + tn) else 0.0,
        "violation_recall_not_pass": (
            len(violation_caught) / len(expected_violation)
            if expected_violation else 0.0
        ),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "confusion": {f"{a}->{b}": confusion[(a, b)] for a in LABELS for b in LABELS},
    }


def grouped_metrics(rows: list[dict]) -> dict[str, dict]:
    groups = defaultdict(list)
    for row in rows:
        groups[row["suite"]].append(row)
    out = {"overall": metric_block(rows)}
    for name in sorted(groups):
        out[name] = metric_block(groups[name])
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "suite", "id", "language", "category", "expected", "predicted",
        "exact_match", "expected_risk", "predicted_risk", "risk_score",
        "violations", "warnings", "elapsed_ms", "top_reason", "text", "rationale",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def pct(v: float) -> str:
    return f"{v:.3f}"


def markdown_report(rows: list[dict], metrics: dict[str, dict], enable_llm: bool) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Cross-Check AI Evaluation Report",
        "",
        f"- Generated: {now}",
        f"- LLM layer: {'ON' if enable_llm else 'OFF'}",
        f"- Total cases: {len(rows)}",
        "",
        "## Executive Summary",
        "",
        "This report evaluates the system as a compliance risk radar. Exact label matching is tracked, but the key safety metric is risk recall: whether expected WARNING/VIOLATION cases are at least escalated for human review.",
        "",
        "## Metrics",
        "",
        "| Suite | Cases | Exact Acc. | Risk Recall | Risk Precision | Risk FPR | Violation Recall | TP/FP/FN/TN |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, m in metrics.items():
        lines.append(
            f"| {name} | {m['total']} | {pct(m['exact_accuracy'])} | "
            f"{pct(m['risk_recall'])} | {pct(m['risk_precision'])} | "
            f"{pct(m['risk_fpr'])} | {pct(m['violation_recall_not_pass'])} | "
            f"{m['tp']}/{m['fp']}/{m['fn']}/{m['tn']} |"
        )

    lines += [
        "",
        "## Confusion Matrix",
        "",
    ]
    for name, m in metrics.items():
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| Expected \\ Predicted | PASS | WARNING | VIOLATION |")
        lines.append("|---|---:|---:|---:|")
        conf = m["confusion"]
        for exp in LABELS:
            lines.append(
                f"| {exp} | {conf.get(exp + '->PASS', 0)} | "
                f"{conf.get(exp + '->WARNING', 0)} | {conf.get(exp + '->VIOLATION', 0)} |"
            )
        lines.append("")

    fn = [r for r in rows if r["risk_fn"]]
    fp = [r for r in rows if r["risk_fp"]]
    mismatches = [r for r in rows if not r["exact_match"]]

    lines += [
        "## Error Review",
        "",
        f"- Risk false negatives: {len(fn)}",
        f"- Risk false positives: {len(fp)}",
        f"- Exact-label mismatches: {len(mismatches)}",
        "",
        "### Risk False Negatives",
        "",
    ]
    if fn:
        lines.append("| ID | Suite | Expected | Predicted | Category | Text |")
        lines.append("|---|---|---|---|---|---|")
        for r in fn[:20]:
            lines.append(
                f"| {r['id']} | {r['suite']} | {r['expected']} | {r['predicted']} | "
                f"{r['category']} | {r['text']} |"
            )
    else:
        lines.append("No risk false negatives.")

    lines += [
        "",
        "### Risk False Positives",
        "",
    ]
    if fp:
        lines.append("| ID | Suite | Expected | Predicted | Category | Top reason |")
        lines.append("|---|---|---|---|---|---|")
        for r in fp[:20]:
            lines.append(
                f"| {r['id']} | {r['suite']} | {r['expected']} | {r['predicted']} | "
                f"{r['category']} | {r['top_reason']} |"
            )
    else:
        lines.append("No risk false positives.")

    lines += [
        "",
        "## Interpretation",
        "",
        "- VIOLATION recall is the primary safety metric for regulatory risk. Missed violations can lead to actual non-compliant content distribution.",
        "- WARNING recall is intentionally harder because many caution cases depend on visual salience, missing-condition analysis, or product/customer context.",
        "- The system is designed as a Human-in-the-loop Regulatory Radar: AI escalates likely risks, and compliance officers make final approval decisions.",
        "- Next tuning should focus on reducing WARNING false negatives while preserving violation recall.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        nargs="+",
        default=[
            str(ROOT / "data" / "evaluation" / "test_cases_ko.json"),
            str(ROOT / "data" / "evaluation" / "test_cases_ko_17.json"),
            str(ROOT / "data" / "evaluation" / "test_cases_ojk.json"),
        ],
    )
    parser.add_argument("--llm", action="store_true")
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "evaluation" / "evaluation_report.md"),
    )
    parser.add_argument(
        "--csv",
        default=str(ROOT / "data" / "evaluation" / "evaluation_report.csv"),
    )
    args = parser.parse_args()

    cases = load_cases([Path(p) for p in args.cases])
    rows = evaluate(cases, enable_llm=args.llm)
    metrics = grouped_metrics(rows)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown_report(rows, metrics, args.llm), encoding="utf-8")
    write_csv(rows, Path(args.csv))
    out_path.with_suffix(".summary.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    overall = metrics["overall"]
    print("=" * 72)
    print("Cross-Check AI Evaluation Report")
    print(f"cases          : {len(cases)}")
    print(f"llm            : {'ON' if args.llm else 'OFF'}")
    print(f"report         : {out_path}")
    print(f"csv            : {args.csv}")
    print("-" * 72)
    print(f"exact accuracy : {overall['exact_accuracy']:.3f}")
    print(f"risk recall    : {overall['risk_recall']:.3f}")
    print(f"risk precision : {overall['risk_precision']:.3f}")
    print(f"risk fpr       : {overall['risk_fpr']:.3f}")
    print(f"viol recall    : {overall['violation_recall_not_pass']:.3f}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
