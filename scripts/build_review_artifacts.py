# -*- coding: utf-8 -*-
"""Build human-review artifacts for FN tuning and OJK legal audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "data" / "evaluation"


def build_fn_checklist() -> None:
    report = EVAL_DIR / "evaluation_report.csv"
    rows = list(csv.DictReader(report.open(encoding="utf-8-sig")))
    fn = [
        r for r in rows
        if r.get("expected_risk") == "True" and r.get("predicted_risk") == "False"
    ]

    out_csv = EVAL_DIR / "fn_review_checklist.csv"
    fields = [
        "id", "suite", "language", "category", "expected", "predicted",
        "text", "why_expected_risk", "review_question",
        "user_decision", "recommended_fix", "final_action",
    ]
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in fn:
            writer.writerow({
                "id": r["id"],
                "suite": r["suite"],
                "language": r["language"],
                "category": r["category"],
                "expected": r["expected"],
                "predicted": r["predicted"],
                "text": r["text"],
                "why_expected_risk": r.get("rationale", ""),
                "review_question": "이 문구를 준법관리자 검토 대상(WARNING 이상)으로 올릴지, PASS로 둘지 판단",
                "user_decision": "미검수",
                "recommended_fix": "",
                "final_action": "",
            })

    lines = [
        "# FN Review Checklist",
        "",
        "목적: 현재 평가셋에서 위험 케이스인데 PASS로 빠진 문구를 사람이 검수해, 실제로 트리/패턴/LLM 프롬프트를 조정할지 결정합니다.",
        "",
        "판단 기준:",
        "- `WARNING 유지`: 법적으로 단정 위반은 아니지만 준법관리자 검토 대상이면 선택",
        "- `VIOLATION 상향`: 명시적 금지 표현 또는 필수 정보 누락이 명확하면 선택",
        "- `PASS 변경`: 테스트셋 라벨이 과도했고 실무상 통과 가능한 문구라면 선택",
        "- `LLM 전용`: 룰로 잡기에는 넓어서 오탐이 커질 가능성이 있으면 선택",
        "",
        "| ID | Suite | 현재 | 기대 | 유형 | 문구 | 검수 질문 | 네 판단 | 후속 조치 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in fn:
        text = r["text"].replace("|", "/")
        lines.append(
            f"| {r['id']} | {r['suite']} | {r['predicted']} | {r['expected']} | "
            f"{r['category']} | {text} | WARNING 이상으로 올릴까? | 미검수 |  |"
        )
    lines += [
        "",
        "## 검수 우선순위",
        "",
        "1. `ID_VIOL_005`, `ID_VIOL_007`: OJK 명시 위반인데 PASS로 빠진 케이스라 우선 수정 대상입니다.",
        "2. `KO_WARN_018`, `KO_WARN_020`: 실제 광고에서 자주 나올 수 있는 표현이라 WARNING 유지 여부를 먼저 판단해야 합니다.",
        "3. `KO_WARN_008`, `KO_WARN_011`, `KO_WARN_013`, `KO_WARN_015`: 넓게 잡으면 오탐이 늘 수 있어 LLM 전용 또는 약한 WARNING 룰이 적절합니다.",
        "",
        f"CSV 편집용 파일: `{out_csv.name}`",
    ]
    (EVAL_DIR / "fn_review_checklist.md").write_text("\n".join(lines), encoding="utf-8")


def build_ojk_audit() -> None:
    article_map = json.loads(
        (ROOT / "data" / "laws" / "ojk_pojk_22_2023_articles.json").read_text(encoding="utf-8")
    )
    lines = [
        "# OJK Legal Mapping Audit",
        "",
        "## 결론",
        "",
        "기존 MVP의 OJK 방향성은 맞지만, `POJK No. 6/POJK.07/2022`와 `POJK No. 22 Tahun 2023`이 혼재되어 있던 부분은 수정이 필요했습니다. 현재 트리와 로컬 조문 검증 DB는 현행 기준인 `POJK No. 22 Tahun 2023` 중심으로 정리했습니다.",
        "",
        "다만 인도네시아 법령의 세부 문언 해석은 한국 금소법과 달리 현지 법률가 검토가 필요하므로, 발표에서는 `MVP 수준의 조항 매핑 검수 완료, 본선/실무 단계에서 현지 법률전문가 최종 검토`라고 말하는 것이 안전합니다.",
        "",
        "## 공식 출처",
        "",
        f"- OJK official PDF: {article_map['source_url']}",
        "- BPK/JDIH 등 인도네시아 법령 포털에서도 POJK 22/2023의 현행성 확인 가능",
        "",
        "## 핵심 조항 매핑",
        "",
        "| Pasal | 기능상 의미 | 시스템 적용 |",
        "|---|---|---|",
    ]
    for no, info in article_map["articles"].items():
        lines.append(
            f"| {no} | {info['summary_ko']} | {info['recommended_use']} |"
        )
    lines += [
        "",
        "## 트리별 법적 근거",
        "",
        "| 트리 유형 | Primary basis | Supplementary basis | 검수 의견 |",
        "|---|---|---|---|",
        "| 확정 수익 약속 | Pasal 29, Pasal 32 | Pasal 3, Pasal 53 | 확정 수익·보장 표현은 명확·정확·비오인 정보제공 원칙 위반 소지가 큼 |",
        "| 무위험/원금안전 표현 | Pasal 29, Pasal 32 | Pasal 30, Pasal 53 | 위험이 있는 상품을 안전·무위험으로 표현하면 오인 가능성 높음 |",
        "| 위험 미고지 | Pasal 30, Pasal 32 | Pasal 33 | 상품 요약정보에 위험 정보를 포함해야 하므로 탐지 타당 |",
        "| 비용 미고지 | Pasal 30, Pasal 32 | Pasal 33, Pasal 53 | 금리·수익·한도만 강조하고 비용/조건을 누락하면 검토 대상 |",
        "| 근거 없는 비교 | Pasal 3, Pasal 29 | Pasal 32, Pasal 53 | 건전한 경쟁과 비오인 정보제공 원칙에 근거해 WARNING/VIOLATION 분류 가능 |",
        "",
        "## 발표 시 방어 문구",
        "",
        "> OJK 트리는 현행 POJK 22/2023의 소비자보호 원칙과 정보제공 의무를 기준으로 MVP 수준의 조항 매핑을 수행했습니다. 다만 해외 법령의 세부 해석은 현지 법률전문가 검토가 필요하므로, 본 시스템은 최종 법률판단이 아니라 준법관리자의 검토 우선순위를 제시하는 Regulatory Radar로 포지셔닝합니다.",
    ]
    (EVAL_DIR / "ojk_legal_audit.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    build_fn_checklist()
    build_ojk_audit()
    print("wrote fn_review_checklist.md/csv and ojk_legal_audit.md")
