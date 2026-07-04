"""
Groq(소형) vs Claude(Opus 4.8) 성능 비교 — 본선 근거 산출용.

같은 평가셋을 LLM 계층만 각각 Groq / Claude로 돌려 지표를 나란히 출력한다.
목적: "판정 본체는 소형 로컬/Groq 모델로 충분하다"를 정량으로 증명하는 표.
(제품 런타임은 Groq 유지 — 이 스크립트는 baseline 비교 전용)

주의: LLM 노드는 규칙이 못 잡은 경계 케이스에서만 호출되므로, 두 provider의
차이는 그 경계 케이스에서만 드러난다 — 그게 정확히 보고 싶은 지점.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))  # evaluate_baseline 재사용

from evaluate_baseline import load_cases, evaluate, metrics  # noqa: E402

KEYS = [
    ("exact_accuracy", "exact accuracy"),
    ("risk_recall_warning_or_violation", "risk recall (WARN/VIOL)"),
    ("violation_recall_not_pass", "violation recall (not PASS)"),
    ("pass_specificity", "pass specificity"),
]


def run(provider: str, cases: list[dict]) -> tuple[list[dict], dict]:
    os.environ["LLM_PROVIDER"] = provider
    rows = evaluate(cases, enable_llm=True)
    return rows, metrics(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "data" / "evaluation" / "test_cases_ko.json"))
    parser.add_argument("--out", default=str(ROOT / "data" / "evaluation" / "compare_groq_vs_claude.json"))
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))

    print("=" * 72)
    print(f"Groq vs Claude 비교  |  cases={len(cases)}  |  LLM 계층 ON")
    print("=" * 72)

    rows_g, m_g = run("groq", cases)
    rows_c, m_c = run("anthropic", cases)

    print(f"{'metric':<28}{'Groq(Llama)':>14}{'Claude(Opus)':>14}{'Δ':>10}")
    print("-" * 72)
    for key, label in KEYS:
        g, c = m_g[key], m_c[key]
        print(f"{label:<28}{g:>14.3f}{c:>14.3f}{c - g:>+10.3f}")

    # 두 provider의 예측이 갈린 케이스 (= LLM 계층이 실제로 개입한 지점)
    diffs = []
    by_id_c = {r["id"]: r for r in rows_c}
    for rg in rows_g:
        rc = by_id_c.get(rg["id"])
        if rc and rg["predicted"] != rc["predicted"]:
            diffs.append({
                "id": rg["id"], "expected": rg["expected"],
                "groq": rg["predicted"], "claude": rc["predicted"],
                "text": rg["text"][:60],
            })

    print("-" * 72)
    print(f"예측이 갈린 케이스: {len(diffs)}건")
    for d in diffs:
        print(f"  [{d['id']}] 기대={d['expected']:<9} Groq={d['groq']:<9} Claude={d['claude']:<9} | {d['text']}")
    print("=" * 72)

    out = {
        "cases": len(cases),
        "groq": {k: m_g[k] for k, _ in KEYS},
        "claude": {k: m_c[k] for k, _ in KEYS},
        "disagreements": diffs,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
