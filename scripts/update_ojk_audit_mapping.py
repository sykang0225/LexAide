# -*- coding: utf-8 -*-
"""Update OJK YAML citations to the audited POJK 22/2023 article map."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TREE_PATH = ROOT / "data" / "trees" / "OJK_POJK.yaml"

MAP_BASIS = {
    "ojk_1_keuntungan_pasti": {
        "law": "POJK No. 22 Tahun 2023 Pasal 29, Pasal 32, Pasal 53",
        "primary": ["POJK No. 22 Tahun 2023 Pasal 29", "POJK No. 22 Tahun 2023 Pasal 32"],
        "supplementary": ["POJK No. 22 Tahun 2023 Pasal 3", "POJK No. 22 Tahun 2023 Pasal 53"],
        "reason": "확정 수익·보장 표현은 상품/서비스 정보가 명확·정확·정직하고 오인을 유발하지 않아야 한다는 POJK 22/2023 정보제공·마케팅 의무 위반 소지가 있습니다.",
    },
    "ojk_2_bebas_risiko": {
        "law": "POJK No. 22 Tahun 2023 Pasal 29, Pasal 32, Pasal 53",
        "primary": ["POJK No. 22 Tahun 2023 Pasal 29", "POJK No. 22 Tahun 2023 Pasal 32"],
        "supplementary": ["POJK No. 22 Tahun 2023 Pasal 30", "POJK No. 22 Tahun 2023 Pasal 53"],
        "reason": "무위험·원금안전 표현은 위험 정보와 실제 제공조건에 대한 소비자 오인 가능성이 있어 POJK 22/2023상 정보제공 의무 위반 소지가 있습니다.",
    },
    "ojk_3_risiko_tidak_diungkap": {
        "law": "POJK No. 22 Tahun 2023 Pasal 30, Pasal 32, Pasal 33",
        "primary": ["POJK No. 22 Tahun 2023 Pasal 30", "POJK No. 22 Tahun 2023 Pasal 32"],
        "supplementary": ["POJK No. 22 Tahun 2023 Pasal 33"],
        "reason": "투자성 상품에서 위험(risiko) 정보를 충분히 제시하지 않으면 상품 요약정보와 마케팅 전 정보제공 의무 위반 소지가 있습니다.",
    },
    "ojk_4_biaya_tidak_diungkap": {
        "law": "POJK No. 22 Tahun 2023 Pasal 30, Pasal 32, Pasal 33",
        "primary": ["POJK No. 22 Tahun 2023 Pasal 30", "POJK No. 22 Tahun 2023 Pasal 32"],
        "supplementary": ["POJK No. 22 Tahun 2023 Pasal 33", "POJK No. 22 Tahun 2023 Pasal 53"],
        "reason": "수익률·금리·한도 등 유리한 조건을 표시하면서 비용·조건 정보를 충분히 제공하지 않으면 POJK 22/2023상 핵심정보 제공 의무 위반 소지가 있습니다.",
    },
    "ojk_5_perbandingan_tanpa_dasar": {
        "law": "POJK No. 22 Tahun 2023 Pasal 3, Pasal 29, Pasal 32",
        "primary": ["POJK No. 22 Tahun 2023 Pasal 3", "POJK No. 22 Tahun 2023 Pasal 29"],
        "supplementary": ["POJK No. 22 Tahun 2023 Pasal 32", "POJK No. 22 Tahun 2023 Pasal 53"],
        "reason": "근거 없는 비교·최상급 표현은 건전한 경쟁 및 명확·정확·비오인 정보제공 원칙 위반 소지가 있습니다.",
    },
}


def main() -> None:
    data = yaml.safe_load(TREE_PATH.read_text(encoding="utf-8"))
    meta = data.setdefault("meta", {})
    meta["law"] = "POJK No. 22 Tahun 2023"
    meta["law_legacy"] = "POJK No. 6/POJK.07/2022 (replaced by POJK No. 22 Tahun 2023)"
    meta["article"] = "Pasal 3, 29, 30, 32, 33, 35, 36, 37, 53"
    meta["legal_audit_status"] = (
        "MVP 법학 검수 완료: OJK 공식 POJK 22/2023 PDF 기준 핵심 조항 매핑. "
        "세부 문언은 현지 법률전문가 최종 검토 필요."
    )
    meta["description"] = (
        "인도네시아 금융서비스 사업자(PUJK)의 정보제공·마케팅·광고는 명확하고 정확하며 정직하고, "
        "소비자를 오인하게 하지 않아야 한다. 본 트리는 POJK No. 22 Tahun 2023의 소비자보호 원칙, "
        "상품/서비스 정보제공, 위험·비용 고지, 광고/프로모션 표시, 적합성 및 광고 내용과 실제 제공조건의 "
        "일치 의무를 금소법 17·21·22조 리스크 유형과 대응되도록 5개 위반유형으로 구조화한다."
    )

    for rule in data.get("rules", []):
        info = MAP_BASIS.get(rule.get("id"))
        if not info:
            continue
        rule["law"] = info["law"]
        rule["legal_basis"] = {
            "primary": info["primary"],
            "supplementary": info["supplementary"],
        }
        for node in rule.get("nodes", []):
            on_match = node.get("on_match") or {}
            if "citation" in on_match:
                on_match["citation"] = info["law"]
            if "reason" in on_match and "POJK" in on_match["reason"]:
                on_match["reason"] = info["reason"]

    TREE_PATH.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    print(f"updated {TREE_PATH}")


if __name__ == "__main__":
    main()
