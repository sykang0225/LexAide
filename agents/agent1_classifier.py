"""
agents/agent1_classifier.py
────────────────────────────────────────────────────────────────
Agent 1 — 언어 감지 · 규제 분류

역할
  1. 입력 텍스트의 언어를 감지 (langdetect)
  2. 언어에 따라 적용할 법령 트리를 결정
  3. 감지 신뢰도가 낮으면 한국어로 폴백 (Recall 우선)

언어 → 트리 매핑
  ko  → 금소법 (금융소비자보호법)
  id  → OJK POJK (인도네시아 금융감독청)

흐름에서의 위치
  사용자 입력 → [Agent 1] → Agent 2 (위반 탐지)
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from langdetect import detect_langs, LangDetectException

logger = logging.getLogger(__name__)

_TREES_DIR = Path(__file__).parent.parent / "data" / "trees"

# 언어 코드 → 법령 정보 매핑
_LANG_META: dict[str, dict] = {
    "ko": {
        "label":       "한국어",
        "jurisdiction":"대한민국",
        "law_name":    "금융소비자보호법",
        "trees":       [
            "금소법_22조_광고규제.yaml",
            "금소법_21조_부당권유.yaml",
            "금소법_17조_적합성원칙.yaml",
        ],
    },
    "id": {
        "label":       "인도네시아어",
        "jurisdiction":"인도네시아",
        "law_name":    "OJK POJK",
        "trees":       ["OJK_POJK.yaml"],
    },
}

# langdetect 신뢰도 임계값 — 이 미만이면 unknown 처리
_CONFIDENCE_THRESHOLD = 0.70


# ─────────────────────────────────────────────────────────────
# 결과 데이터 클래스
# ─────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    """Agent 1 출력 — Agent 2로 전달되는 라우팅 정보"""
    language: str               # "ko" / "id" / "unknown"
    confidence: float           # langdetect 신뢰도 0.0~1.0
    label: str                  # "한국어" / "인도네시아어" / "감지 불가"
    jurisdiction: str           # 적용 관할권
    law_name: str               # 적용 법령명
    available_trees: list[str] = field(default_factory=list)   # 실제 존재하는 트리 파일
    fallback_used: bool = False # 신뢰도 부족으로 폴백 적용 여부
    raw_candidates: list[dict] = field(default_factory=list)   # langdetect 후보 목록

    def to_dict(self) -> dict:
        return {
            "language":        self.language,
            "confidence":      round(self.confidence, 3),
            "label":           self.label,
            "jurisdiction":    self.jurisdiction,
            "law_name":        self.law_name,
            "available_trees": self.available_trees,
            "fallback_used":   self.fallback_used,
        }


# ─────────────────────────────────────────────────────────────
# 메인 분류기
# ─────────────────────────────────────────────────────────────

class LanguageClassifier:
    """
    입력 텍스트의 언어를 감지하고 적용 법령 트리를 결정한다.

    사용 예시
    ---------
    clf = LanguageClassifier()
    result = clf.classify("안정적인 수익을 추구하는 상품입니다")
    print(result.language)      # "ko"
    print(result.available_trees)
    """

    def __init__(self, trees_dir: str | Path = _TREES_DIR):
        self.trees_dir = Path(trees_dir)

    def classify(self, text: str) -> ClassificationResult:
        """
        텍스트 언어를 감지하고 적용 트리를 반환.

        - 한국어(ko) / 인도네시아어(id) 만 지원
        - 신뢰도 < 0.70 이면 한국어로 폴백 (Recall 우선)
        - 지원 외 언어도 한국어로 폴백
        """
        if not text or not text.strip():
            return self._build_result("ko", 0.0, fallback=True)

        # langdetect 실행
        try:
            candidates = detect_langs(text)
        except LangDetectException:
            logger.warning("[Agent1] 언어 감지 실패 → 한국어 폴백")
            return self._build_result("ko", 0.0, fallback=True)

        raw = [{"lang": c.lang, "prob": round(c.prob, 3)} for c in candidates]
        logger.debug(f"[Agent1] langdetect 결과: {raw}")

        # 최고 신뢰도 후보 선택
        top = candidates[0]
        lang_code = top.lang
        confidence = top.prob

        # ko / id 만 지원, 나머지는 폴백
        if lang_code not in _LANG_META:
            # 2순위 후보도 확인 (예: 한·인니 혼합 문장)
            for c in candidates[1:]:
                if c.lang in _LANG_META:
                    lang_code = c.lang
                    confidence = c.prob
                    break
            else:
                logger.info(
                    f"[Agent1] 지원 외 언어({top.lang}, conf={confidence:.2f}) → 한국어 폴백"
                )
                return self._build_result("ko", confidence, fallback=True, raw=raw)

        # 신뢰도 임계값 미달 → 폴백
        if confidence < _CONFIDENCE_THRESHOLD:
            logger.info(
                f"[Agent1] 신뢰도 부족({lang_code}, conf={confidence:.2f} < {_CONFIDENCE_THRESHOLD}) "
                f"→ 한국어 폴백"
            )
            return self._build_result("ko", confidence, fallback=True, raw=raw)

        result = self._build_result(lang_code, confidence, fallback=False, raw=raw)
        logger.info(
            f"[Agent1] 분류 완료: {result.label}({lang_code}) "
            f"conf={confidence:.2f} | 트리={result.available_trees}"
        )
        return result

    def _build_result(
        self,
        lang: str,
        confidence: float,
        fallback: bool = False,
        raw: list[dict] | None = None,
    ) -> ClassificationResult:
        """ClassificationResult 생성 + 실제 파일 존재 여부 확인"""
        meta = _LANG_META.get(lang, _LANG_META["ko"])
        available = [
            f for f in meta["trees"]
            if (self.trees_dir / f).exists()
        ]
        return ClassificationResult(
            language=lang,
            confidence=confidence,
            label=meta["label"],
            jurisdiction=meta["jurisdiction"],
            law_name=meta["law_name"],
            available_trees=available,
            fallback_used=fallback,
            raw_candidates=raw or [],
        )


# ─────────────────────────────────────────────────────────────
# 모듈 수준 편의 함수
# ─────────────────────────────────────────────────────────────

_clf: LanguageClassifier | None = None


def classify(text: str) -> ClassificationResult:
    """
    전역 분류 함수.

    from agents.agent1_classifier import classify
    result = classify("안정적인 수익 보장")
    """
    global _clf
    if _clf is None:
        _clf = LanguageClassifier()
    return _clf.classify(text)


# ─────────────────────────────────────────────────────────────
# 직접 실행 테스트
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    TEST_CASES = [
        ("한국어 명확",     "이 상품은 연 8% 수익을 보장합니다. 원금 손실이 없습니다."),
        ("인니어 명확",     "Produk ini memberikan keuntungan stabil sebesar 8% per tahun."),
        ("한국어 짧은 문장", "수익 보장"),
        ("영어 (폴백)",     "This product guarantees a stable return of 8% per year."),
        ("빈 문자열",       ""),
    ]

    print("=" * 55)
    print("Agent 1 — 언어 감지 테스트")
    print("=" * 55)

    clf = LanguageClassifier()
    for label, text in TEST_CASES:
        r = clf.classify(text)
        fb = " [폴백]" if r.fallback_used else ""
        print(f"\n[{label}]")
        print(f"  입력   : {text[:50] or '(빈 문자열)'}")
        print(f"  언어   : {r.label}({r.language}){fb}  conf={r.confidence:.2f}")
        print(f"  법령   : {r.law_name}")
        print(f"  트리   : {r.available_trees or '없음'}")
