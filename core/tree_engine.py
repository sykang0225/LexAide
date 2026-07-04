"""
core/tree_engine.py
────────────────────────────────────────────────────────────────
YAML 의사결정 트리 DSL 실행 엔진 — Cross-Check AI

지원 노드 타입
  rule      : 정규식 패턴 매칭 (즉시 판단, 비용 0)
  llm       : Groq API Llama 3.3 70B 추론 (애매한 케이스만)
  embedding : FAISS 유사도 검색 (플레이스홀더 — 추후 구현)

실행 전략 (Recall 우선)
  1. rule 노드를 먼저 평가한다.
  2. VIOLATION 이 하나라도 나오면 → llm 노드 스킵 (이미 확정)
  3. 모두 PASS 이면 → llm 노드 실행 (미탐지 케이스 캐치)
  4. negate=true 인 rule 은 패턴이 없을 때 위반 (손실미고지·비용누락 등)

반환 타입
  NodeResult  : 단일 노드 평가 결과
  RuleResult  : 한 규칙(rule block) 내 전체 노드 결과 집계
  TreeResult  : 파일 내 모든 규칙 결과 집계 + 최종 판정
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 결과 데이터 클래스
# ─────────────────────────────────────────────────────────────

RESULT_RANK = {"VIOLATION": 3, "WARNING": 2, "PASS": 1}


@dataclass
class NodeResult:
    """단일 노드 평가 결과"""
    node_id: str
    node_type: str                  # rule / llm / embedding
    triggered: bool                 # 해당 노드가 위반·경고 판정 발동했는지
    result: str                     # VIOLATION / WARNING / PASS
    reason: str
    confidence: float               # 0.0 ~ 1.0
    citation: str = ""              # 인용 조문
    action: str = ""                # 권고 조치
    matched_text: str = ""          # 매칭된 텍스트 (rule 노드)
    raw_llm_response: str = ""      # LLM 원문 응답 (디버깅용)
    skipped: bool = False           # 스킵 여부 (조건 미충족)
    skip_reason: str = ""


@dataclass
class RuleResult:
    """하나의 rule 블록 전체 평가 결과"""
    rule_id: str
    law: str
    name: str
    node_results: list[NodeResult] = field(default_factory=list)

    @property
    def final_result(self) -> str:
        """노드 결과 중 가장 높은 심각도 반환"""
        active = [n for n in self.node_results if not n.skipped and not getattr(n, "_internal", False)]
        if not active:
            return "PASS"
        return max(active, key=lambda n: RESULT_RANK.get(n.result, 0)).result

    @property
    def max_confidence(self) -> float:
        active = [n for n in self.node_results if not n.skipped and n.triggered]
        return max((n.confidence for n in active), default=0.0)

    @property
    def violations(self) -> list[NodeResult]:
        return [n for n in self.node_results if n.result == "VIOLATION" and not n.skipped]

    @property
    def warnings(self) -> list[NodeResult]:
        return [n for n in self.node_results if n.result == "WARNING" and not n.skipped]


@dataclass
class TreeResult:
    """파일 전체 평가 결과 (여러 rule 블록 합산)"""
    source_file: str
    law: str
    rule_results: list[RuleResult] = field(default_factory=list)

    @property
    def all_violations(self) -> list[NodeResult]:
        out = []
        for rr in self.rule_results:
            out.extend(rr.violations)
        return out

    @property
    def all_warnings(self) -> list[NodeResult]:
        out = []
        for rr in self.rule_results:
            out.extend(rr.warnings)
        return out

    @property
    def overall_result(self) -> str:
        if self.all_violations:
            return "VIOLATION"
        if self.all_warnings:
            return "WARNING"
        return "PASS"

    @property
    def overall_confidence(self) -> float:
        nodes = self.all_violations or self.all_warnings
        return max((n.confidence for n in nodes), default=0.0)

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "law": self.law,
            "overall_result": self.overall_result,
            "overall_confidence": round(self.overall_confidence, 3),
            "violations": [
                {
                    "node_id": n.node_id,
                    "reason": n.reason,
                    "citation": n.citation,
                    "action": n.action,
                    "confidence": round(n.confidence, 3),
                    "matched_text": n.matched_text,
                }
                for n in self.all_violations
            ],
            "warnings": [
                {
                    "node_id": n.node_id,
                    "reason": n.reason,
                    "citation": n.citation,
                    "confidence": round(n.confidence, 3),
                }
                for n in self.all_warnings
            ],
        }


# ─────────────────────────────────────────────────────────────
# 엔진 본체
# ─────────────────────────────────────────────────────────────

class TreeEngine:
    """
    YAML DSL 파일을 로드하고 입력 텍스트를 평가하는 실행 엔진.

    사용 예시
    ---------
    engine = TreeEngine()
    tree = engine.load("data/trees/금소법_22조_광고규제.yaml")
    result = engine.evaluate(tree, "안정적인 수익을 보장합니다")
    print(result.overall_result)   # VIOLATION
    """

    def __init__(self, llm_client=None):
        """
        Parameters
        ----------
        llm_client : callable | None
            call_llm(prompt, system) 형태의 함수.
            None이면 LLM 노드를 스킵하고 WARNING 처리.
        """
        self._llm_client = llm_client
        self._cache: dict[str, tuple[float, dict]] = {}   # 파일 경로 → (수정시각, 파싱된 YAML)
        self._max_llm_nodes_per_tree = int(os.environ.get("MAX_LLM_NODES_PER_TREE", "1"))
        self._llm_calls_remaining = self._max_llm_nodes_per_tree

    # ── 로드 ──────────────────────────────────────────────────

    def load(self, yaml_path: str | Path) -> dict:
        """
        YAML 트리 파일을 로드하고 파싱 결과를 반환한다.
        같은 경로는 메모리 캐시로 재사용.
        """
        path = str(yaml_path)
        mtime = Path(path).stat().st_mtime
        cached = self._cache.get(path)
        if cached is None or cached[0] != mtime:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._cache[path] = (mtime, data)
            logger.info(f"[TreeEngine] 로드 완료: {path}")
        return self._cache[path][1]

    def load_all(self, trees_dir: str | Path) -> list[tuple[str, dict]]:
        """디렉터리 내 모든 .yaml 파일을 로드해서 (경로, 파싱결과) 리스트 반환"""
        trees_dir = Path(trees_dir)
        results = []
        for yaml_file in sorted(trees_dir.glob("*.yaml")):
            results.append((str(yaml_file), self.load(yaml_file)))
        return results

    def invalidate(self, path: str | Path | None = None) -> None:
        """
        트리 캐시를 비운다. 규칙 편집 저장 후 즉시 라이브 반영을 보장한다.
        path=None 이면 전체, 아니면 해당 파일(경로 또는 basename) 엔트리만.
        (mtime 비교로 자동 재로드되지만, 저장 직후 명시적 무효화로 확실히 한다.)
        """
        if path is None:
            self._cache.clear()
            return
        name = Path(str(path)).name
        for key in [k for k in self._cache if Path(k).name == name or k == str(path)]:
            self._cache.pop(key, None)

    # ── 평가 진입점 ───────────────────────────────────────────

    def evaluate(self, tree_data: dict, text: str, source_file: str = "") -> TreeResult:
        """
        단일 YAML 트리 데이터로 텍스트를 평가한다.

        Parameters
        ----------
        tree_data   : load()가 반환한 파싱된 YAML dict
        text        : 심의 대상 광고 문구
        source_file : 원본 파일 경로 (결과 추적용)
        """
        meta = tree_data.get("meta", {})
        law = meta.get("law", "")
        rules_raw = tree_data.get("rules", [])

        # 단일 rule 구조 지원 (legacy)
        if "rule" in tree_data:
            rules_raw = [tree_data["rule"]]

        # 글로벌 면책·부정문 패턴 (오탐 방지) — meta.exclude_patterns
        global_excludes = meta.get("exclude_patterns", []) or []

        tree_result = TreeResult(source_file=source_file, law=law)
        self._llm_calls_remaining = self._max_llm_nodes_per_tree

        for rule_def in rules_raw:
            rule_result = self._evaluate_rule(rule_def, text, global_excludes)
            tree_result.rule_results.append(rule_result)

        log_level = logging.WARNING if tree_result.overall_result != "PASS" else logging.DEBUG
        logger.log(
            log_level,
            f"[TreeEngine] {source_file or law} → {tree_result.overall_result} "
            f"(violations={len(tree_result.all_violations)}, "
            f"warnings={len(tree_result.all_warnings)})",
        )
        return tree_result

    def evaluate_file(self, yaml_path: str | Path, text: str) -> TreeResult:
        """파일 경로를 받아 로드 → 평가를 한 번에 수행하는 편의 메서드"""
        path = str(yaml_path)
        tree_data = self.load(path)
        return self.evaluate(tree_data, text, source_file=path)

    # ── rule 블록 평가 ─────────────────────────────────────────

    def _evaluate_rule(
        self, rule_def: dict, text: str, global_excludes: list[str] | None = None
    ) -> RuleResult:
        rule_id = rule_def.get("id", "unknown")
        law = rule_def.get("law", "")
        name = rule_def.get("name", "")
        nodes = rule_def.get("nodes", [])

        # rule 블록 단위 exclude_pattern + 글로벌 exclude 병합
        block_excludes = rule_def.get("exclude_pattern", []) or []
        merged_excludes = list(global_excludes or []) + list(block_excludes)

        rule_result = RuleResult(rule_id=rule_id, law=law, name=name)

        # ① rule 노드 먼저 평가
        rule_nodes_done: list[NodeResult] = []
        for node in nodes:
            if node.get("enabled") is False:      # 준법관리자가 비활성화한 노드 — 평가 제외
                continue
            if node.get("type") != "rule":
                continue
            nr = self._evaluate_rule_node(node, text, rule_nodes_done, merged_excludes)
            rule_nodes_done.append(nr)
            rule_result.node_results.append(nr)

        # ② rule 노드 중 VIOLATION 이 나왔으면 llm 노드 스킵 (이미 확정)
        has_violation = any(
            n.result == "VIOLATION" and not n.skipped
            for n in rule_result.node_results
        )

        # ③ llm / embedding 노드 평가
        for node in nodes:
            if node.get("enabled") is False:      # 비활성화된 llm/embedding 노드 제외
                continue
            ntype = node.get("type", "")
            if ntype == "rule":
                continue

            trigger_when = node.get("trigger_when", "rule_nodes_pass")

            # 스킵 조건 판단
            if trigger_when == "rule_nodes_pass" and has_violation:
                nr = NodeResult(
                    node_id=node.get("id", ""),
                    node_type=ntype,
                    triggered=False,
                    result="PASS",
                    reason="rule 노드 VIOLATION 확정으로 스킵",
                    confidence=0.0,
                    skipped=True,
                    skip_reason="rule_violation_confirmed",
                )
                rule_result.node_results.append(nr)
                continue

            # prerequisite 확인
            prereq = node.get("prerequisite")
            if prereq:
                prereq_result = next(
                    (n for n in rule_result.node_results if n.node_id == prereq), None
                )
                if prereq_result is None or prereq_result.result == "PASS" and not prereq_result.triggered:
                    nr = NodeResult(
                        node_id=node.get("id", ""),
                        node_type=ntype,
                        triggered=False,
                        result="PASS",
                        reason=f"prerequisite '{prereq}' 미충족으로 스킵",
                        confidence=0.0,
                        skipped=True,
                        skip_reason=f"prerequisite_not_met:{prereq}",
                    )
                    rule_result.node_results.append(nr)
                    continue

            if ntype == "llm":
                if self._llm_calls_remaining <= 0:
                    nr = NodeResult(
                        node_id=node.get("id", ""),
                        node_type=ntype,
                        triggered=False,
                        result="PASS",
                        reason="LLM 호출 예산 초과로 스킵",
                        confidence=0.0,
                        skipped=True,
                        skip_reason="llm_budget_exceeded",
                    )
                    rule_result.node_results.append(nr)
                    continue
                self._llm_calls_remaining -= 1
                nr = self._evaluate_llm_node(node, text)
            elif ntype == "embedding":
                nr = self._evaluate_embedding_node(node, text)
            else:
                logger.warning(f"[TreeEngine] 알 수 없는 노드 타입: {ntype}")
                continue

            rule_result.node_results.append(nr)

        return rule_result

    # ── rule 노드 (정규식) ─────────────────────────────────────

    def _evaluate_rule_node(
        self, node: dict, text: str, prev_results: list[NodeResult],
        merged_excludes: list[str] | None = None,
    ) -> NodeResult:
        node_id = node.get("id", "")
        pattern = node.get("pattern", "")
        negate = node.get("negate", False)          # True이면 '패턴 없음'이 위반
        flags_str = node.get("flags", "")
        on_match: dict = node.get("on_match", {})
        is_internal = on_match.get("_internal", False)

        # 노드별 exclude_pattern + 상위(블록·글로벌) exclude 병합
        node_excludes = node.get("exclude_pattern", []) or []
        excludes = list(merged_excludes or []) + list(node_excludes)

        # prerequisite 확인
        prereq = node.get("prerequisite")
        if prereq:
            prereq_result = next(
                (n for n in prev_results if n.node_id == prereq), None
            )
            if prereq_result is None:
                return NodeResult(
                    node_id=node_id, node_type="rule",
                    triggered=False, result="PASS",
                    reason=f"prerequisite '{prereq}' 미발견, 스킵",
                    confidence=0.0, skipped=True,
                    skip_reason=f"prerequisite_missing:{prereq}",
                )
            # 선행 노드가 내부 라우팅 노드이고 매치했어야(triggered) 실행
            if is_internal is False and not prereq_result.triggered:
                return NodeResult(
                    node_id=node_id, node_type="rule",
                    triggered=False, result="PASS",
                    reason=f"prerequisite '{prereq}' 미트리거, 스킵",
                    confidence=0.0, skipped=True,
                    skip_reason=f"prerequisite_not_triggered:{prereq}",
                )

        # 정규식 플래그
        re_flags = 0
        if "IGNORECASE" in flags_str or "I" in flags_str:
            re_flags |= re.IGNORECASE

        try:
            match = re.search(pattern, text, re_flags)
        except re.error as e:
            logger.error(f"[TreeEngine] 정규식 오류 ({node_id}): {e}")
            return NodeResult(
                node_id=node_id, node_type="rule",
                triggered=False, result="PASS",
                reason=f"정규식 오류: {e}", confidence=0.0,
            )

        # negate=True : 패턴이 '없을 때' 위반
        matched = bool(match)
        triggered = (not matched) if negate else matched

        # ── 면책·부정문 오탐 방지 (positive match에만 적용) ──
        # 예: "원금 보장하지 않습니다", "손실 가능성 존재" 같은 면책 문구가
        #     있으면 위반으로 잡지 않는다 (False Positive 완화).
        #     negate 노드(미고지 탐지)는 면책문구 자체가 정상 고지이므로 제외.
        if triggered and not negate and excludes:
            re_flags_ex = re.IGNORECASE if re_flags & re.IGNORECASE else 0
            for ex in excludes:
                try:
                    if re.search(ex, text, re_flags_ex):
                        return NodeResult(
                            node_id=node_id, node_type="rule",
                            triggered=False, result="PASS",
                            reason=f"면책·부정문 표현 탐지로 오탐 제외 (exclude: '{ex}')",
                            confidence=0.0,
                            skip_reason=f"excluded_by_pattern:{ex}",
                        )
                except re.error:
                    continue

        if triggered:
            return NodeResult(
                node_id=node_id,
                node_type="rule",
                triggered=True,
                result=on_match.get("result", "VIOLATION"),
                reason=on_match.get("reason", ""),
                confidence=on_match.get("confidence", 0.9),
                citation=on_match.get("citation", ""),
                action=on_match.get("action", ""),
                matched_text=match.group(0) if match else "",
            )
        else:
            return NodeResult(
                node_id=node_id, node_type="rule",
                triggered=False, result="PASS",
                reason="패턴 미탐지 — PASS",
                confidence=0.0,
            )

    # ── llm 노드 (Groq Llama 3.3 70B) ─────────────────────────

    def _evaluate_llm_node(self, node: dict, text: str) -> NodeResult:
        node_id = node.get("id", "")
        on_match: dict = node.get("on_match", {})

        if self._llm_client is None:
            logger.warning(f"[TreeEngine] LLM 클라이언트 미설정 — {node_id} 스킵")
            return NodeResult(
                node_id=node_id, node_type="llm",
                triggered=False, result="PASS",
                reason="LLM 클라이언트 미설정 (초기화 시 llm_client 인자 필요)",
                confidence=0.0, skipped=True,
                skip_reason="no_llm_client",
            )

        system_prompt = node.get("system_prompt", "당신은 금융 준법 심사 전문가입니다.")
        prompt_template = node.get("prompt", "{text}")
        prompt = prompt_template.format(text=text)

        try:
            raw_response = self._llm_client(prompt=prompt, system=system_prompt)
            parsed = self._parse_llm_response(raw_response)
        except Exception as e:
            logger.error(f"[TreeEngine] LLM 호출 오류 ({node_id}): {e}")
            return NodeResult(
                node_id=node_id, node_type="llm",
                triggered=False, result="PASS",
                reason=f"LLM 호출 오류: {e}",
                confidence=0.0, raw_llm_response=str(e),
            )

        triggered = parsed.get("triggered", False)
        confidence = float(parsed.get("confidence", 0.0))
        reason_llm = parsed.get("reason", "")

        # confidence 임계값: 0.5 이상일 때만 triggered 로 처리 (Recall 우선)
        if triggered and confidence >= 0.5:
            return NodeResult(
                node_id=node_id,
                node_type="llm",
                triggered=True,
                result=on_match.get("result", "WARNING"),
                reason=f"{on_match.get('reason', '')} | LLM: {reason_llm}",
                confidence=min(confidence, on_match.get("confidence", 0.75)),
                citation=on_match.get("citation", ""),
                action=on_match.get("action", ""),
                raw_llm_response=raw_response,
            )
        else:
            return NodeResult(
                node_id=node_id, node_type="llm",
                triggered=False, result="PASS",
                reason=f"LLM 위반 미탐지 (confidence={confidence:.2f}): {reason_llm}",
                confidence=0.0, raw_llm_response=raw_response,
            )

    def _parse_llm_response(self, raw: str) -> dict:
        """
        LLM 응답에서 JSON 블록을 추출한다.
        {"triggered": true/false, "reason": "...", "confidence": 0.0~1.0}
        """
        # JSON 블록 추출 시도
        json_match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        # 폴백: 텍스트에서 추론
        raw_lower = raw.lower()
        triggered = any(kw in raw_lower for kw in ["위반", "true", "예", "yes", "해당"])
        return {
            "triggered": triggered,
            "reason": raw[:200],
            "confidence": 0.65 if triggered else 0.3,
        }

    # ── embedding 노드 (플레이스홀더) ─────────────────────────

    def _evaluate_embedding_node(self, node: dict, text: str) -> NodeResult:
        """
        FAISS 유사도 검색 노드 — 3주차 구현 예정.
        현재는 항상 PASS 반환 (플레이스홀더).
        """
        node_id = node.get("id", "")
        logger.debug(f"[TreeEngine] embedding 노드 {node_id} — 플레이스홀더, PASS")
        return NodeResult(
            node_id=node_id, node_type="embedding",
            triggered=False, result="PASS",
            reason="embedding 노드 미구현 (플레이스홀더)",
            confidence=0.0, skipped=True,
            skip_reason="not_implemented",
        )


# ─────────────────────────────────────────────────────────────
# 편의 함수 — 외부에서 바로 호출
# ─────────────────────────────────────────────────────────────

_default_engine: TreeEngine | None = None


def get_engine(llm_client=None) -> TreeEngine:
    """모듈 수준 싱글턴 엔진 반환 (테스트·스크립트용)"""
    global _default_engine
    if _default_engine is None:
        _default_engine = TreeEngine(llm_client=llm_client)
    elif llm_client is not None:
        _default_engine._llm_client = llm_client
    return _default_engine


def run_tree(yaml_path: str | Path, text: str, llm_client=None) -> TreeResult:
    """단일 YAML 트리 파일 평가 원스텝 함수"""
    engine = get_engine(llm_client)
    return engine.evaluate_file(yaml_path, text)


# ─────────────────────────────────────────────────────────────
# 직접 실행 시 동작 테스트 (python core/tree_engine.py)
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    # 테스트 케이스
    TEST_CASES = [
        ("VIOLATION 예상",  "이 상품은 연 8% 수익을 보장합니다. 원금은 절대 잃지 않습니다."),
        ("WARNING 예상",    "시장 평균보다 높은 수익을 추구하는 상품입니다."),
        ("PASS 예상",       "이 상품은 원금손실이 발생할 수 있으며, 투자 전 설명서를 확인하세요."),
        ("비용누락 예상",    "연 5.2% 금리 상품! 지금 바로 가입하세요."),
        ("비교 위반 예상",   "업계 최고 금리를 자랑하는 No.1 예금 상품"),
    ]

    yaml_path = Path(__file__).parent.parent / "data" / "trees" / "금소법_22조_광고규제.yaml"
    engine = TreeEngine(llm_client=None)  # LLM 없이 rule 노드만 테스트

    print("=" * 60)
    print("Cross-Check AI — TreeEngine 동작 테스트 (rule 노드만)")
    print("=" * 60)

    for label, text in TEST_CASES:
        result = engine.evaluate_file(yaml_path, text)
        symbol = {"VIOLATION": "🔴", "WARNING": "🟡", "PASS": "🟢"}.get(result.overall_result, "⚪")
        print(f"\n{symbol} [{label}]")
        print(f"   입력: {text[:60]}")
        print(f"   판정: {result.overall_result}  (confidence={result.overall_confidence:.2f})")
        for v in result.all_violations:
            print(f"   위반: {v.reason}")
            if v.action:
                print(f"   조치: {v.action}")
        for w in result.all_warnings:
            print(f"   경고: {w.reason}")

    print("\n" + "=" * 60)
    print("테스트 완료")
