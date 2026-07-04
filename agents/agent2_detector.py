"""
agents/agent2_detector.py
────────────────────────────────────────────────────────────────
Agent 2 — 위반 탐지 엔진 (3단계 하이브리드)

파이프라인
  1단계: 룰 베이스드  — 정규식 패턴 (tree_engine rule 노드)
  2단계: LLM 추론    — Groq Llama 3.3 70B (애매한 케이스만)
  3단계: 임베딩      — FAISS 유사도 (플레이스홀더, 3주차 구현)

주요 클래스
  ViolationDetector : 단일 텍스트 심의 진입점
  DetectionResult   : 최종 판정 결과 (Agent 1/3/4 연동용 인터페이스)

Recall 우선 설계
  - rule VIOLATION 확정 → LLM 스킵 (비용 절감)
  - rule 모두 PASS     → LLM 실행 (미탐지 케이스 캐치)
  - 임계값 0.35        → FN(위반 누락) 최소화
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from core.tree_engine import TreeEngine, TreeResult
from utils.llm_client import call_llm

logger = logging.getLogger(__name__)

# 프로젝트 루트 기준 trees 디렉터리
_TREES_DIR = Path(__file__).parent.parent / "data" / "trees"

# 임베딩 판정 기여 임계값 — 입력이 기존 제재사례와 이 값 이상으로 유사하면
# embedding WARNING 항목을 생성(룰이 놓친 의미적 위반을 보완). FP 억제를 위해 보수적 설정.
_EMB_RISK_THRESHOLD = float(os.environ.get("EMB_RISK_THRESHOLD", "0.72"))

# 언어 → 관할(region) 매핑. 트리 파일은 하드코딩하지 않고 trees/ 에서 관할로 동적 탐색.
# → 새 법령 YAML(예: 보험업법, region=KR)을 넣으면 코드 수정 없이 해당 언어 심의에 자동 편입.
_LANG_REGION: dict[str, str] = {"ko": "KR", "id": "ID", "unknown": "KR"}

# 파일별 관할 캐시 (mtime 기반) — 매 심의마다 메타 재파싱 방지
_region_cache: dict[str, tuple[float, str]] = {}


def _tree_region(path: Path) -> str:
    """트리의 관할(KR/ID) 판별 — meta.jurisdiction/law + 파일명 휴리스틱. mtime 캐시."""
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return "KR"
    cached = _region_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    meta = {}
    try:
        with open(path, encoding="utf-8") as f:
            meta = (yaml.safe_load(f) or {}).get("meta", {}) or {}
    except Exception:
        meta = {}
    j = str(meta.get("jurisdiction") or "")
    law = str(meta.get("law") or "")
    region = "ID" if ("OJK" in path.name or "POJK" in law or "인도네시아" in j or "OJK" in j) else "KR"
    _region_cache[key] = (mtime, region)
    return region


# ─────────────────────────────────────────────────────────────
# 결과 데이터 클래스
# ─────────────────────────────────────────────────────────────

@dataclass
class ViolationItem:
    """개별 위반/경고 항목"""
    rule_id: str
    law: str
    result: str               # VIOLATION / WARNING
    reason: str
    citation: str
    action: str
    confidence: float
    node_type: str            # rule / llm / embedding
    matched_text: str = ""
    node_id: str = ""         # 트리 내 정확한 노드 id (규칙 편집 타겟)
    tree_file: str = ""       # 이 판정을 낸 트리 파일명 (규칙 편집 타겟)


@dataclass
class DetectionResult:
    """
    Agent 2 최종 출력 — Agent 1/3/4 및 통합 판정 엔진으로 전달되는 인터페이스

    Attributes
    ----------
    text          : 심의 원문
    language      : 탐지 언어 (ko / id / unknown)
    overall       : 최종 등급 (VIOLATION / WARNING / PASS)
    risk_score    : 0.0~1.0 리스크 점수
    violations    : 확정 위반 목록
    warnings      : 경고 목록
    applied_trees : 적용된 YAML 트리 파일 목록
    elapsed_ms    : 처리 시간 (밀리초)
    """
    text: str
    language: str
    overall: str
    risk_score: float
    violations: list[ViolationItem] = field(default_factory=list)
    warnings: list[ViolationItem] = field(default_factory=list)
    applied_trees: list[str] = field(default_factory=list)
    similar_sanctions: list[dict] = field(default_factory=list)  # FAISS 유사 제재사례
    elapsed_ms: float = 0.0
    error: str = ""

    @property
    def is_violation(self) -> bool:
        return self.overall == "VIOLATION"

    @property
    def is_warning(self) -> bool:
        return self.overall == "WARNING"

    @property
    def is_pass(self) -> bool:
        return self.overall == "PASS"

    def summary(self) -> str:
        """Streamlit 대시보드용 요약 문자열"""
        emoji = {"VIOLATION": "🔴", "WARNING": "🟡", "PASS": "🟢"}.get(self.overall, "⚪")
        lines = [f"{emoji} [{self.overall}] 리스크 점수: {self.risk_score:.2f}"]
        for v in self.violations:
            lines.append(f"  ❌ {v.reason}")
            if v.action:
                lines.append(f"     → 조치: {v.action}")
        for w in self.warnings:
            lines.append(f"  ⚠️  {w.reason}")
        if not self.violations and not self.warnings:
            lines.append("  ✅ 위반 사항 없음")
        lines.append(f"  (처리시간: {self.elapsed_ms:.0f}ms)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "risk_score": round(self.risk_score, 3),
            "language": self.language,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "law": v.law,
                    "reason": v.reason,
                    "citation": v.citation,
                    "action": v.action,
                    "confidence": round(v.confidence, 3),
                    "node_type": v.node_type,
                    "matched_text": v.matched_text,
                    "node_id": v.node_id,
                    "tree_file": v.tree_file,
                }
                for v in self.violations
            ],
            "warnings": [
                {
                    "rule_id": w.rule_id,
                    "law": w.law,
                    "reason": w.reason,
                    "citation": w.citation,
                    "confidence": round(w.confidence, 3),
                    "node_type": w.node_type,
                    "node_id": w.node_id,
                    "tree_file": w.tree_file,
                }
                for w in self.warnings
            ],
            "applied_trees": self.applied_trees,
            "similar_sanctions": self.similar_sanctions,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


# ─────────────────────────────────────────────────────────────
# 리스크 스코어 계산 (Recall 우선 임계값)
# ─────────────────────────────────────────────────────────────

class RiskScorer:
    """
    베이지안 앙상블 리스크 스코어 산출

    가중치: rule(0.5) > llm(0.35) > embedding(0.15)
    OR 결합: rule 또는 llm 단독으로 0.8 이상이면 최소 0.75 보장
    """
    WEIGHTS = {"rule": 0.5, "llm": 0.35, "embedding": 0.15}
    THRESHOLD_PASS      = 0.35   # < 0.35  → PASS
    THRESHOLD_WARNING   = 0.60   # < 0.60  → WARNING
    THRESHOLD_VIOLATION = 0.80   # >= 0.80 → VIOLATION (엄격 확정)

    @classmethod
    def compute(cls, items: list[ViolationItem]) -> tuple[float, str]:
        """
        위반/경고 항목 목록으로 리스크 스코어와 최종 등급 계산.

        Returns
        -------
        (risk_score: float, grade: str)
        """
        if not items:
            return 0.0, "PASS"

        # 노드 타입별 최고 confidence 추출
        rule_score = max(
            (i.confidence for i in items if i.node_type == "rule"), default=0.0
        )
        llm_score = max(
            (i.confidence for i in items if i.node_type == "llm"), default=0.0
        )
        emb_score = max(
            (i.confidence for i in items if i.node_type == "embedding"), default=0.0
        )

        combined = (
            rule_score * cls.WEIGHTS["rule"]
            + llm_score * cls.WEIGHTS["llm"]
            + emb_score * cls.WEIGHTS["embedding"]
        )

        # OR 결합: 하나라도 고신뢰 위반이면 최소 0.75 보장
        if rule_score >= 0.8 or llm_score >= 0.8:
            combined = max(combined, 0.75)

        # VIOLATION 항목이 하나라도 있으면 최소 0.6 보장
        has_violation = any(i.result == "VIOLATION" for i in items)
        has_warning   = any(i.result == "WARNING" for i in items)
        if has_violation:
            combined = max(combined, 0.60)

        # 등급 결정 (Recall 우선: 경고 존재 시 최소 WARNING 보장)
        if combined >= cls.THRESHOLD_VIOLATION or has_violation:
            grade = "VIOLATION"
        elif combined >= cls.THRESHOLD_WARNING or has_warning:
            grade = "WARNING"
        elif combined >= cls.THRESHOLD_PASS:
            grade = "WARNING"
        else:
            grade = "PASS"

        return round(combined, 3), grade


# ─────────────────────────────────────────────────────────────
# 메인 탐지 클래스
# ─────────────────────────────────────────────────────────────

class ViolationDetector:
    """
    Agent 2 위반 탐지 엔진.

    사용 예시
    ---------
    detector = ViolationDetector()
    result = detector.detect("연 10% 수익을 보장합니다", language="ko")
    print(result.summary())
    """

    def __init__(self, trees_dir: str | Path = _TREES_DIR, enable_llm: bool = True,
                 enable_embedding: bool = True):
        """
        Parameters
        ----------
        trees_dir        : YAML 트리 파일 디렉터리
        enable_llm       : False 이면 LLM 노드 스킵 (테스트·오프라인 모드)
        enable_embedding : False 이면 FAISS 유사 제재사례 검색 스킵
        """
        self.trees_dir = Path(trees_dir)
        self.enable_embedding = enable_embedding
        llm_fn = call_llm if enable_llm else None
        self._engine = TreeEngine(llm_client=llm_fn)
        logger.info(
            f"[Agent2] 초기화 완료 | LLM={'활성' if enable_llm else '비활성'} | "
            f"임베딩={'활성' if enable_embedding else '비활성'} | "
            f"트리 경로={self.trees_dir}"
        )

    def _find_similar_sanctions(self, text: str, language: str, k: int = 3) -> list[dict]:
        """FAISS로 의미적 유사 제재사례 검색 (실패해도 빈 리스트 반환 — 안전)"""
        if not self.enable_embedding:
            return []
        try:
            from utils.faiss_store import search
            lang = language if language in ("ko", "id") else None
            return search(text, k=k, lang=lang, min_score=0.55)
        except Exception as e:
            logger.warning(f"[Agent2] 유사 제재사례 검색 스킵: {e}")
            return []

    # ── 메인 진입점 ───────────────────────────────────────────

    def detect(self, text: str, language: str = "ko") -> DetectionResult:
        """
        입력 텍스트를 해당 언어의 법령 트리 전체로 심의.

        Parameters
        ----------
        text     : 심의 대상 광고 문구
        language : 'ko' (한국어) / 'id' (인도네시아어) / 'unknown'
        """
        start = time.perf_counter()

        if not text or not text.strip():
            return DetectionResult(
                text=text, language=language,
                overall="PASS", risk_score=0.0,
                error="입력 텍스트가 비어있습니다.",
            )

        # 적용할 트리 파일 목록 결정
        tree_files = self._resolve_trees(language)
        if not tree_files:
            logger.warning(f"[Agent2] 적용할 트리 없음 (language={language})")
            return DetectionResult(
                text=text, language=language,
                overall="PASS", risk_score=0.0,
                error=f"language='{language}' 에 해당하는 트리 파일 없음",
            )

        # 모든 트리 실행 → 위반/경고 수집
        all_items: list[ViolationItem] = []
        applied: list[str] = []

        for tree_path in tree_files:
            try:
                tree_result: TreeResult = self._engine.evaluate_file(tree_path, text)
                items = self._extract_items(tree_result)
                all_items.extend(items)
                applied.append(tree_path.name)
                logger.debug(
                    f"[Agent2] {tree_path.name} → "
                    f"{tree_result.overall_result} "
                    f"(violations={len(tree_result.all_violations)})"
                )
            except FileNotFoundError:
                logger.debug(f"[Agent2] 트리 파일 없음 (스킵): {tree_path}")
            except Exception as e:
                logger.error(f"[Agent2] 트리 실행 오류 ({tree_path.name}): {e}")

        # 임베딩 단계: 의미적 유사 제재사례 검색 (FAISS/numpy)
        similar = self._find_similar_sanctions(text, language)

        # 임베딩 판정 기여: 기존 제재사례와 임계값 이상으로 유사하면
        # embedding WARNING 항목을 추가 → 룰이 놓친 의미적 위반을 보완(Recall↑)
        if similar and similar[0].get("score", 0.0) >= _EMB_RISK_THRESHOLD:
            top = similar[0]
            all_items.append(ViolationItem(
                rule_id="EMB-SIM",
                law=top.get("law", ""),
                result="WARNING",
                reason=(f"기존 제재사례와 의미적으로 유사 "
                        f"(유사도 {top['score']:.2f} · {top.get('violation_type', '')})"),
                citation=top.get("citation", ""),
                action="유사 제재사례를 참고하여 준법관리자 검토 권장",
                confidence=float(top["score"]),
                node_type="embedding",
                matched_text=str(top.get("text", ""))[:60],
            ))

        # 리스크 스코어 계산 (룰 + 임베딩 항목 결합)
        risk_score, grade = RiskScorer.compute(all_items)

        violations = [i for i in all_items if i.result == "VIOLATION"]
        warnings   = [i for i in all_items if i.result == "WARNING"]

        elapsed_ms = (time.perf_counter() - start) * 1000

        result = DetectionResult(
            text=text,
            language=language,
            overall=grade,
            risk_score=risk_score,
            violations=violations,
            warnings=warnings,
            applied_trees=applied,
            similar_sanctions=similar,
            elapsed_ms=elapsed_ms,
        )

        logger.info(
            f"[Agent2] 심의 완료 | {grade} | "
            f"score={risk_score:.3f} | "
            f"위반={len(violations)} 경고={len(warnings)} | "
            f"{elapsed_ms:.0f}ms"
        )
        return result

    # ── 내부 유틸 ─────────────────────────────────────────────

    def _resolve_trees(self, language: str) -> list[Path]:
        """언어의 관할(region)에 해당하는 trees/ 의 모든 트리 경로를 동적 반환.
        파일명 하드코딩 없음 → 새 법령 YAML을 넣으면 자동 편입(코드 수정 불필요)."""
        region = _LANG_REGION.get(language, "KR")
        result = [
            p for p in sorted(self.trees_dir.glob("*.yaml"))
            if _tree_region(p) == region
        ]
        if not result:
            logger.debug(f"[Agent2] 관할 '{region}' 트리 없음 (language={language})")
        return result

    def _extract_items(self, tree_result: TreeResult) -> list[ViolationItem]:
        """TreeResult에서 ViolationItem 목록 추출"""
        items = []
        tree_file = Path(tree_result.source_file).name if tree_result.source_file else ""
        for rr in tree_result.rule_results:
            triggered_nodes = [
                n for n in rr.node_results
                if n.triggered and not n.skipped and n.result in ("VIOLATION", "WARNING")
            ]
            for node in triggered_nodes:
                items.append(ViolationItem(
                    rule_id=rr.rule_id,
                    law=rr.law,
                    result=node.result,
                    reason=node.reason,
                    citation=node.citation,
                    action=node.action,
                    confidence=node.confidence,
                    node_type=node.node_type,
                    matched_text=node.matched_text,
                    node_id=node.node_id,
                    tree_file=tree_file,
                ))
        return items


# ─────────────────────────────────────────────────────────────
# 모듈 수준 편의 함수
# ─────────────────────────────────────────────────────────────

_detectors: dict[tuple[bool, bool], ViolationDetector] = {}


def detect(
    text: str,
    language: str = "ko",
    enable_llm: bool = True,
    enable_embedding: bool = False,
) -> DetectionResult:
    """
    전역 탐지 함수 — 외부 모듈에서 바로 호출 가능.

    from agents.agent2_detector import detect
    result = detect("안정적 수익 보장 상품", language="ko")
    """
    key = (enable_llm, enable_embedding)
    if key not in _detectors:
        _detectors[key] = ViolationDetector(
            enable_llm=enable_llm,
            enable_embedding=enable_embedding,
        )
    return _detectors[key].detect(text, language)


# ─────────────────────────────────────────────────────────────
# 직접 실행 테스트
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    TEST_CASES = [
        # (설명, 텍스트, 언어, LLM 사용 여부)
        ("rule 탐지: 수익 보장",
         "연 8% 수익을 보장합니다. 원금은 절대 잃지 않습니다.",
         "ko", False),

        ("rule 탐지: 업계 최고",
         "업계 최고 금리! No.1 예금 상품에 지금 가입하세요.",
         "ko", False),

        ("rule PASS → LLM 탐지: 암시적 보장",
         "안정적인 수익을 제공하는 검증된 상품입니다.",
         "ko", True),

        ("정상 광고 (PASS 예상)",
         "이 상품은 원금손실이 발생할 수 있습니다. 투자 전 설명서를 반드시 확인하세요.",
         "ko", True),

        ("복합 위반: 보장 + 최고 + 비용 누락",
         "국내 최고 수익률을 보장하는 연 12% 펀드! 지금 바로 투자하세요.",
         "ko", True),
    ]

    print("=" * 65)
    print("Cross-Check AI — Agent 2 위반 탐지 테스트")
    print("=" * 65)

    for label, text, lang, use_llm in TEST_CASES:
        print(f"\n{'─' * 65}")
        print(f"📋 [{label}]  LLM={'ON' if use_llm else 'OFF'}")
        print(f"   입력: {text}")
        result = detect(text, language=lang, enable_llm=use_llm)
        print(result.summary())

    print("\n" + "=" * 65)
    print("테스트 완료")
