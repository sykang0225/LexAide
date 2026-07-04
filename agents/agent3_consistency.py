"""
agents/agent3_consistency.py
────────────────────────────────────────────────────────────────
Agent 3 — 번역 정합성 검증

역할
  한국어 원본과 인도네시아어 번역본을 각각 독립 심의한 후
  두 결과를 비교하여 '번역 오류로 인한 규제 위반'을 탐지한다.

핵심 탐지 로직
  1. 한국어 심의 (Agent 2, 금소법)
  2. 인도네시아어 심의 (Agent 2, OJK — 트리 준비 시)
  3. 결과 불일치 비교:
       KO=PASS + ID=VIOLATION → 번역 오류 (핵심 차별점)
       KO=VIOLATION + ID=PASS → 한국어 원본 위반, 번역 개선
       둘 다 위반              → 복합 위반
  4. 한·인니 금융 용어집(Termbase) 기반 용어 일관성 검증

흐름에서의 위치
  [한·인니 쌍 입력] → Agent 1 → Agent 2 × 2 → [Agent 3] → 통합 판정
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents.agent2_detector import ViolationDetector, DetectionResult

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 한·인니 금융 용어집 (Termbase)
# 키: 한국어 용어, 값: 올바른 인니어 번역
# ─────────────────────────────────────────────────────────────

TERMBASE: dict[str, dict] = {
    "이자율":   {"id": "bunga",         "wrong": ["suku bunga tinggi", "bunga besar"]},
    "수익률":   {"id": "imbal hasil",   "wrong": ["keuntungan pasti", "hasil pasti"]},
    "원금":     {"id": "pokok",         "wrong": ["modal aman", "pokok terjamin"]},
    "만기":     {"id": "jatuh tempo",   "wrong": []},
    "투자":     {"id": "investasi",     "wrong": []},
    "예금":     {"id": "deposito",      "wrong": ["tabungan aman"]},
    "대출":     {"id": "pinjaman",      "wrong": []},
    "보험":     {"id": "asuransi",      "wrong": []},
    "추구하다": {"id": "mengejar",      "wrong": ["memberikan", "menjamin"]},
    "수익 추구":{"id": "mengejar keuntungan", "wrong": ["memberikan keuntungan", "menjamin keuntungan"]},
    "안정적":   {"id": "stabil",        "wrong": ["aman", "terjamin"]},
    "손실":     {"id": "kerugian",      "wrong": []},
    "원금손실": {"id": "kerugian pokok","wrong": ["tidak ada kerugian", "pokok aman"]},
}


# ─────────────────────────────────────────────────────────────
# 결과 데이터 클래스
# ─────────────────────────────────────────────────────────────

@dataclass
class TermbaseViolation:
    """용어집 불일치 항목"""
    ko_term: str          # 한국어 원문 용어
    expected_id: str      # 올바른 인니어 번역
    found_wrong: str      # 발견된 잘못된 번역
    severity: str         # VIOLATION / WARNING
    suggestion: str       # 수정 권고


@dataclass
class ConsistencyResult:
    """Agent 3 최종 출력"""
    ko_text: str
    id_text: str

    # 각 언어 심의 결과 (Agent 2 출력)
    ko_result: DetectionResult | None = None
    id_result: DetectionResult | None = None

    # 정합성 판정
    consistency_status: str = "CONSISTENT"   # CONSISTENT / TRANSLATION_ERROR / BOTH_VIOLATION / KO_ONLY_VIOLATION
    translation_errors: list[TermbaseViolation] = field(default_factory=list)
    mismatch_summary: str = ""

    # OJK 트리 미준비 시 부분 결과 허용
    id_skipped: bool = False
    id_skip_reason: str = ""

    @property
    def has_translation_error(self) -> bool:
        return self.consistency_status == "TRANSLATION_ERROR"

    @property
    def overall_status(self) -> str:
        """대시보드용 최종 통합 등급"""
        statuses = []
        if self.ko_result:
            statuses.append(self.ko_result.overall)
        if self.id_result:
            statuses.append(self.id_result.overall)
        if self.translation_errors:
            statuses.append("VIOLATION")
        if "VIOLATION" in statuses:
            return "VIOLATION"
        if "WARNING" in statuses:
            return "WARNING"
        return "PASS"

    def summary(self) -> str:
        lines = []
        emoji_map = {"VIOLATION": "🔴", "WARNING": "🟡", "PASS": "🟢"}

        # 한국어 결과
        if self.ko_result:
            e = emoji_map.get(self.ko_result.overall, "⚪")
            lines.append(f"{e} 한국어(금소법): {self.ko_result.overall}  score={self.ko_result.risk_score:.2f}")

        # 인도네시아어 결과
        if self.id_skipped:
            lines.append(f"⏭️  인도네시아어(OJK): 스킵 — {self.id_skip_reason}")
        elif self.id_result:
            e = emoji_map.get(self.id_result.overall, "⚪")
            lines.append(f"{e} 인도네시아어(OJK): {self.id_result.overall}  score={self.id_result.risk_score:.2f}")

        # 정합성 결과
        lines.append("")
        if self.consistency_status == "TRANSLATION_ERROR":
            lines.append("⚠️  [번역 오류 탐지] 원본은 통과했지만 번역본에서 위반 발생")
            lines.append(f"   → {self.mismatch_summary}")
        elif self.consistency_status == "BOTH_VIOLATION":
            lines.append("🔴 [복합 위반] 원본·번역본 모두 위반")
        elif self.consistency_status == "KO_ONLY_VIOLATION":
            lines.append("🔴 [원본 위반] 한국어 원본 자체가 위반")
        else:
            lines.append("✅ [정합성 통과] 원본·번역본 일치")

        # 용어집 오류
        if self.translation_errors:
            lines.append("")
            lines.append("📚 [용어집 불일치]")
            for t in self.translation_errors:
                lines.append(f"  ❌ '{t.ko_term}': '{t.found_wrong}' → 권고: '{t.expected_id}'")
                lines.append(f"     {t.suggestion}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "consistency_status": self.consistency_status,
            "overall_status":     self.overall_status,
            "mismatch_summary":   self.mismatch_summary,
            "id_skipped":         self.id_skipped,
            "id_skip_reason":     self.id_skip_reason,
            "ko_result":  self.ko_result.to_dict() if self.ko_result else None,
            "id_result":  self.id_result.to_dict() if self.id_result else None,
            "translation_errors": [
                {
                    "ko_term":      t.ko_term,
                    "expected_id":  t.expected_id,
                    "found_wrong":  t.found_wrong,
                    "severity":     t.severity,
                    "suggestion":   t.suggestion,
                }
                for t in self.translation_errors
            ],
        }


# ─────────────────────────────────────────────────────────────
# 정합성 검증기
# ─────────────────────────────────────────────────────────────

class ConsistencyChecker:
    """
    한국어 원본 + 인도네시아어 번역본을 각각 심의하고
    결과를 비교하여 번역 오류를 탐지한다.

    사용 예시
    ---------
    checker = ConsistencyChecker()
    result = checker.check(
        ko_text="안정적인 수익을 추구하는 상품입니다",
        id_text="Produk yang memberikan keuntungan stabil",
    )
    print(result.summary())
    """

    def __init__(self, enable_llm: bool = True, enable_embedding: bool = False):
        # enable_embedding 기본값 False: sentence-transformers 충돌 방지 (Anaconda 환경)
        self._detector = ViolationDetector(enable_llm=enable_llm, enable_embedding=enable_embedding)

    def check(self, ko_text: str, id_text: str) -> ConsistencyResult:
        """
        한·인니 쌍을 심의하고 정합성을 검증한다.

        Parameters
        ----------
        ko_text : 한국어 원본 광고 문구
        id_text : 인도네시아어 번역본 광고 문구
        """
        result = ConsistencyResult(ko_text=ko_text, id_text=id_text)

        # ── 1. 한국어 심의 ─────────────────────────────────────
        logger.info("[Agent3] 한국어 심의 시작")
        result.ko_result = self._detector.detect(ko_text, language="ko")
        logger.info(f"[Agent3] 한국어 결과: {result.ko_result.overall}")

        # ── 2. 인도네시아어 심의 ───────────────────────────────
        trees_dir = Path(__file__).parent.parent / "data" / "trees"
        ojk_exists = (trees_dir / "OJK_POJK.yaml").exists()

        if not ojk_exists:
            result.id_skipped = True
            result.id_skip_reason = "OJK_POJK.yaml 준비 중 (3주차 추가 예정)"
            logger.info("[Agent3] OJK 트리 미준비 — 인니어 심의 스킵")
        else:
            logger.info("[Agent3] 인도네시아어 심의 시작")
            result.id_result = self._detector.detect(id_text, language="id")
            logger.info(f"[Agent3] 인도네시아어 결과: {result.id_result.overall}")

        # ── 3. 결과 비교 → 정합성 판정 ────────────────────────
        result = self._compare_results(result)

        # ── 4. 용어집 일관성 검증 ──────────────────────────────
        result.translation_errors = self._check_termbase(ko_text, id_text)

        logger.info(
            f"[Agent3] 정합성 검증 완료: {result.consistency_status} | "
            f"용어오류={len(result.translation_errors)}"
        )
        return result

    def _compare_results(self, result: ConsistencyResult) -> ConsistencyResult:
        """두 심의 결과를 비교하여 consistency_status 결정"""
        ko = result.ko_result
        id_ = result.id_result

        # OJK 트리 없어서 인니어 스킵된 경우 — 한국어 결과만 반영
        if result.id_skipped or id_ is None:
            if ko and ko.overall == "VIOLATION":
                result.consistency_status = "KO_ONLY_VIOLATION"
                result.mismatch_summary = "한국어 원본 자체 위반 — 번역 전 원본부터 수정 필요"
            else:
                result.consistency_status = "CONSISTENT"
                result.mismatch_summary = "한국어 통과 (인니어 심의 미실시)"
            return result

        ko_status = ko.overall if ko else "PASS"
        id_status = id_.overall if id_ else "PASS"

        # 등급 서열: PASS(0) < WARNING(1) < VIOLATION(2)
        RANK = {"PASS": 0, "WARNING": 1, "VIOLATION": 2}
        kr, ir = RANK.get(ko_status, 0), RANK.get(id_status, 0)
        KOR = {"PASS": "통과", "WARNING": "주의", "VIOLATION": "위반"}

        if ko_status == "VIOLATION" and id_status == "VIOLATION":
            # 양측 모두 위반
            result.consistency_status = "BOTH_VIOLATION"
            result.mismatch_summary = "원본·번역본 모두 위반 — 원본부터 전면 수정 필요"

        elif ir > kr:
            # 번역본이 원본보다 더 심각 → 번역 과정에서 문제 발생/악화 (★ 핵심 탐지)
            reasons = [v.reason for v in (id_.violations[:2] if id_ else [])] or \
                      [w.reason for w in (id_.warnings[:2] if id_ else [])]
            if id_status == "VIOLATION":
                result.consistency_status = "TRANSLATION_ERROR"
                result.mismatch_summary = (
                    f"한국어 원본은 '{KOR[ko_status]}'이나 인도네시아어 번역본은 'OJK 위반'. "
                    f"번역 과정에서 규제 위반이 발생·악화됨. "
                    f"위반 사유: {'; '.join(reasons)}"
                )
            else:
                # KO=PASS, ID=WARNING 등 — 위반까진 아니나 번역에서 위험도 상승
                result.consistency_status = "TRANSLATION_DISCREPANCY"
                result.mismatch_summary = (
                    f"한국어 원본은 '{KOR[ko_status]}'이나 인도네시아어 번역본은 '{KOR[id_status]}'. "
                    f"번역 과정에서 규제 위험도가 상승함 — 번역 표현 재검토 권장. "
                    f"사유: {'; '.join(reasons)}"
                )

        elif kr > ir:
            # 원본이 번역본보다 더 심각
            if ko_status == "VIOLATION":
                result.consistency_status = "KO_ONLY_VIOLATION"
                result.mismatch_summary = "한국어 원본 위반 — 번역 전 원본부터 수정 필요"
            else:
                result.consistency_status = "TRANSLATION_DISCREPANCY"
                result.mismatch_summary = (
                    f"한국어 원본은 '{KOR[ko_status]}'이나 인도네시아어 번역본은 '{KOR[id_status]}'로 "
                    f"등급이 불일치 — 양측 표현 재검토 권장"
                )

        else:
            # 등급 동일
            if ko_status == "WARNING":
                result.consistency_status = "CONSISTENT"
                result.mismatch_summary = "원본·번역본 모두 '주의' 수준으로 일치 (양측 표현 점검 권장)"
            else:
                result.consistency_status = "CONSISTENT"
                result.mismatch_summary = "원본·번역본 모두 '통과'로 일치 — 번역 정합성 양호"

        return result

    def _check_termbase(self, ko_text: str, id_text: str) -> list[TermbaseViolation]:
        """
        한·인니 금융 용어집으로 번역 용어 일관성을 검증한다.
        한국어 용어가 존재하면 인니어 번역에서 잘못된 번역이 쓰였는지 확인.
        """
        violations: list[TermbaseViolation] = []

        for ko_term, info in TERMBASE.items():
            # 한국어 텍스트에 해당 용어가 없으면 스킵
            if ko_term not in ko_text:
                continue

            correct_id = info["id"]
            wrong_list = info.get("wrong", [])

            # 잘못된 번역 존재 여부 확인
            for wrong in wrong_list:
                if re.search(re.escape(wrong), id_text, re.IGNORECASE):
                    violations.append(TermbaseViolation(
                        ko_term=ko_term,
                        expected_id=correct_id,
                        found_wrong=wrong,
                        severity="VIOLATION",
                        suggestion=(
                            f"'{wrong}' → '{correct_id}'으로 수정 권고. "
                            f"'{wrong}'은(는) 수익 보장 의미를 함축하여 OJK 위반 가능"
                        ),
                    ))
                    break   # 한 용어당 첫 번째 오류만 보고

            # 올바른 번역도 없고 잘못된 번역도 없으면 미번역 경고
            if wrong_list and correct_id not in id_text and ko_term in ko_text:
                # 관련 번역 자체가 없는 경우는 경고 수준으로만 처리
                pass

        return violations


# ─────────────────────────────────────────────────────────────
# 모듈 수준 편의 함수
# ─────────────────────────────────────────────────────────────

_checker: ConsistencyChecker | None = None


def check_consistency(
    ko_text: str, id_text: str,
    enable_llm: bool = True,
    enable_embedding: bool = False,
) -> ConsistencyResult:
    """
    전역 정합성 검증 함수.

    from agents.agent3_consistency import check_consistency
    result = check_consistency("수익 추구 상품", "Produk memberikan keuntungan")
    """
    global _checker
    if _checker is None:
        _checker = ConsistencyChecker(enable_llm=enable_llm, enable_embedding=enable_embedding)
    return _checker.check(ko_text, id_text)


# ─────────────────────────────────────────────────────────────
# 직접 실행 테스트
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    # PROJECT_CONTEXT.md 핵심 시연 시나리오
    TEST_CASES = [
        (
            "★ 핵심 시나리오: 원본 통과, 번역 오류",
            "안정적인 수익을 추구하는 상품입니다",
            "Produk yang memberikan keuntungan stabil",  # memberikan = 보장 암시 (OJK 위반)
        ),
        (
            "원본 위반 케이스",
            "연 10% 수익을 보장합니다. 원금은 절대 안전합니다.",
            "Produk investasi dengan imbal hasil 10% per tahun",
        ),
        (
            "둘 다 통과 케이스",
            "이 상품은 원금손실이 발생할 수 있습니다. 투자 전 설명서를 확인하세요.",
            "Produk ini memiliki risiko kerugian pokok. Bacalah prospektus sebelum berinvestasi.",
        ),
    ]

    checker = ConsistencyChecker(enable_llm=True)

    print("=" * 65)
    print("Agent 3 — 번역 정합성 검증 테스트")
    print("=" * 65)

    for label, ko, id_ in TEST_CASES:
        print(f"\n{'─' * 65}")
        print(f"📋 {label}")
        print(f"  한국어: {ko}")
        print(f"  인니어: {id_}")
        print()
        result = checker.check(ko, id_)
        print(result.summary())

    print("\n" + "=" * 65)
    print("테스트 완료")
