"""
agents/agent4_verifier.py
────────────────────────────────────────────────────────────────
Agent 4 — 자기 검증 (Citation Hallucination Check)

목적
  AI 판정의 신뢰성 확보. 두 가지를 검증한다.
  1. [실존 검증] 인용된 법령이 국가법령정보에 실제로 존재하는가? (법령 API)
  2. [환각 탐지] LLM이 reason 텍스트에서 언급한 조문(제N조 제N항 제N호)이
     권위 인용(YAML 트리의 citation)과 일치하는가?
     → LLM이 멋대로 항·호를 지어내면 (예: "제22조 제1항 제2호") 플래그

흐름
  Agent 2 (위반 탐지) → Agent 4 (인용 검증) → 신뢰도 보강된 결과

한국 법령만 API 검증. OJK 등 해외 법령은 패턴(존재형식) 검증만.
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_ART_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*제\s*(\d+)\s*항)?(?:\s*제\s*(\d+)\s*호)?")
_PASAL_RE = re.compile(r"Pasal\s*(\d+)", re.IGNORECASE)


@dataclass
class CitationCheck:
    rule_id: str
    node_type: str               # rule / llm
    citation: str                # 권위 인용 (YAML)
    law_verified: bool           # 법령 실존 (API)
    official_name: str = ""      # 정식 법령명
    link: str = ""               # 법령 원문 링크
    source: str = "offline"      # api / offline
    article_refs: list[dict] = field(default_factory=list)
    llm_flags: list[str] = field(default_factory=list)  # LLM reason 환각 의심

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "node_type": self.node_type,
            "citation": self.citation,
            "law_verified": self.law_verified,
            "official_name": self.official_name,
            "link": self.link,
            "source": self.source,
            "article_refs": self.article_refs,
            "llm_flags": self.llm_flags,
        }


@dataclass
class VerificationResult:
    checks: list[CitationCheck] = field(default_factory=list)
    verified_count: int = 0
    total_count: int = 0
    hallucination_flags: int = 0

    def to_dict(self) -> dict:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "verified_count": self.verified_count,
            "total_count": self.total_count,
            "hallucination_flags": self.hallucination_flags,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if self.total_count == 0:
            return "검증할 인용 없음"
        parts = [f"인용 조문 {self.verified_count}/{self.total_count}건 실존 확인"]
        if self.hallucination_flags:
            parts.append(f"⚠️ LLM 인용 환각 의심 {self.hallucination_flags}건")
        else:
            parts.append("LLM 인용 환각 없음")
        return " · ".join(parts)


def _extract_articles(text: str) -> set[tuple]:
    """텍스트에서 (조, 항, 호) 튜플 집합 추출"""
    out = set()
    for m in _ART_RE.finditer(text or ""):
        out.add((m.group(1), m.group(2), m.group(3)))
    return out


def _verify_one(rule_id: str, node_type: str, citation: str, reason: str) -> CitationCheck:
    from api.law_api import verify_citation, is_korean_law

    chk = CitationCheck(rule_id=rule_id, node_type=node_type, citation=citation,
                        law_verified=False)

    # 1) 법령 실존 검증
    if is_korean_law(citation):
        info = verify_citation(citation)
        chk.law_verified = info["verified"]
        chk.official_name = info.get("official_name") or ""
        chk.link = info.get("link") or ""
        chk.source = info.get("source", "offline")
        chk.article_refs = info.get("refs") or []
    elif "POJK" in citation:
        from api.ojk_law import verify_ojk_citation
        info = verify_ojk_citation(citation)
        chk.law_verified = info["verified"]
        chk.official_name = info.get("official_name") or "POJK (인도네시아 OJK 규정)"
        chk.link = info.get("link") or ""
        chk.source = info.get("source", "local_ojk")
        chk.article_refs = info.get("refs") or []
    else:
        chk.law_verified = bool(citation.strip())
        chk.source = "format"

    # 2) LLM reason 환각 탐지 (llm 노드만)
    if node_type == "llm" and reason:
        cite_arts = _extract_articles(citation)   # 권위 인용의 조
        cite_jo = {a[0] for a in cite_arts}
        reason_arts = _extract_articles(reason)    # LLM이 reason에 쓴 조
        for (jo, hang, ho) in reason_arts:
            # LLM이 권위 인용에 없는 '조'를 언급
            if jo not in cite_jo and cite_jo:
                chk.llm_flags.append(
                    f"LLM이 reason에서 '제{jo}조'를 언급했으나 권위 인용({citation})과 불일치")
            # LLM이 권위 인용엔 없는 세부 항·호를 특정 (예: 제1항 제2호)
            elif (hang or ho):
                detail = "".join(filter(None, [f"제{hang}항" if hang else "", f"제{ho}호" if ho else ""]))
                if detail:
                    chk.llm_flags.append(
                        f"LLM이 '제{jo}조 {detail}'로 세부 항·호를 특정 — 권위 인용은 조 단위, 세부 인용 신뢰 주의")
    return chk


def verify(detection_result, timeout_sec: float = 12.0) -> VerificationResult:
    """
    DetectionResult 의 모든 위반·주의 항목의 인용을 검증.
    병렬 실행(ThreadPoolExecutor)으로 레이턴시 최소화.
    timeout_sec: 전체 검증 작업 제한 시간 (기본 12초)
    """
    import concurrent.futures

    vr = VerificationResult()
    items = list(getattr(detection_result, "violations", [])) + \
            list(getattr(detection_result, "warnings", []))

    # 중복 제거
    seen: set = set()
    tasks: list[dict] = []
    for it in items:
        citation = getattr(it, "citation", "") or ""
        if not citation:
            continue
        key = (getattr(it, "rule_id", ""), citation, getattr(it, "node_type", ""))
        if key in seen:
            continue
        seen.add(key)
        tasks.append({
            "rule_id":   getattr(it, "rule_id", ""),
            "node_type": getattr(it, "node_type", ""),
            "citation":  citation,
            "reason":    getattr(it, "reason", ""),
        })

    if not tasks:
        logger.info("[Agent4] 검증할 인용 없음")
        return vr

    # 병렬 실행
    def _run(t: dict) -> "CitationCheck":
        return _verify_one(**t)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tasks), 6)) as ex:
            futures = {ex.submit(_run, t): t for t in tasks}
            done, pending = concurrent.futures.wait(
                futures, timeout=timeout_sec
            )
            # 타임아웃된 작업은 건너뜀
            for f in pending:
                f.cancel()
                logger.warning("[Agent4] 검증 타임아웃 — 일부 인용 건너뜀")

            for f in done:
                try:
                    chk = f.result()
                    vr.checks.append(chk)
                    vr.total_count += 1
                    if chk.law_verified:
                        vr.verified_count += 1
                    vr.hallucination_flags += len(chk.llm_flags)
                except Exception as e:
                    logger.warning(f"[Agent4] 검증 오류 (건너뜀): {e}")
    except Exception as e:
        logger.error(f"[Agent4] 병렬 검증 실패: {e}")

    logger.info(f"[Agent4] 검증 완료 — {vr.summary()}")
    return vr


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    from agents.agent2_detector import detect

    r = detect("연 8% 수익을 보장합니다. 원금은 절대 잃지 않습니다.", language="ko", enable_llm=False)
    vr = verify(r)
    print("\n", vr.summary())
    for c in vr.checks:
        flag = f" ⚠️{c.llm_flags}" if c.llm_flags else ""
        print(f"  [{c.rule_id}] {c.citation}")
        print(f"     실존={c.law_verified}({c.source}) 정식명={c.official_name}{flag}")
