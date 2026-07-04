"""
core/rule_store.py
────────────────────────────────────────────────────────────────
규칙 트리(YAML)의 안전한 구조화 읽기/쓰기 레이어 — LexAide

설계 원칙
  · 별도 override 레이어가 아니라 *진짜 트리(YAML)* 를 바꾼다.
  · 원문 텍스트를 직접 치지 않는다 → YAML을 dict로 파싱 → 필드 단위 수정 → 직렬화.
  · 법적 근거 주석(#)을 보존한다 → 라운드트립 파서(ruamel.yaml) 사용.
  · 잘못 저장해도 라이브 트리가 절대 깨지지 않는다 → 3중 안전장치.

3중 안전장치 (safe_write)
  1. 저장 전 검증 — 정규식 컴파일, result enum, confidence 범위
  2. 원본 백업   — 저장 직전 타임스탬프 백업 파일 생성
  3. 원자적 교체 — 임시 파일에 쓰고 재검증 통과 후 os.replace(atomic rename)

캐시 무효화
  엔진은 mtime 캐시라 파일이 바뀌면 다음 심의에 자동 재로드되지만(보너스),
  저장 성공 시 명시적으로도 비워 즉시 라이브 반영을 보장한다.

이 모듈은 "안전한 쓰기" 토대(B)다. 피드백 3종(낮춤/올림/추가, C)은
find_node + safe_write 위에 얹는다. 평가 엔진(tree_engine)은 건드리지 않는다.
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterator

import yaml  # 엔진과 동일한 읽기 경로 — 디스크 산출물이 엔진에서 로드되는지 재확인용
from ruamel.yaml import YAML

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 경로 / 상수
# ─────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent
TREES_DIR = _ROOT / "data" / "trees"
# 백업은 trees/ 밖에 둔다 — load_all 의 glob("*.yaml") 에 잡히지 않도록.
BACKUP_DIR = _ROOT / "data" / "tree_backups"

VALID_RESULTS = {"VIOLATION", "WARNING", "PASS"}


# ─────────────────────────────────────────────────────────────
# ruamel 라운드트립 인스턴스 (주석·따옴표·구조 보존)
# ─────────────────────────────────────────────────────────────

# 파일별 시퀀스 들여쓰기 스타일 — 각 트리의 기존 컨벤션을 보존해 불필요한
# reflow(churn)를 막는다. 한 필드만 고쳐 저장해도 diff에 그 줄만 뜨게 하는 것이 목적.
#   금소법 트리: dash 를 키 아래로 들여씀      → sequence=4, offset=2
#   OJK 트리   : dash 를 부모 키와 같은 열에 둠 → sequence=2, offset=0
_DEFAULT_INDENT = (2, 4, 2)
_FILE_INDENT: dict[str, tuple[int, int, int]] = {
    "OJK_POJK.yaml": (2, 2, 0),
}


def _make_yaml(tree_file: str | None = None) -> YAML:
    y = YAML()
    y.preserve_quotes = True
    name = Path(str(tree_file)).name if tree_file else ""
    m, s, o = _FILE_INDENT.get(name, _DEFAULT_INDENT)
    y.indent(mapping=m, sequence=s, offset=o)
    # 긴 reason/prompt 가 자동 줄바꿈(folding)되지 않도록
    y.width = 4096
    return y


# ─────────────────────────────────────────────────────────────
# 예외
# ─────────────────────────────────────────────────────────────

class RuleStoreError(Exception):
    """규칙 저장소 일반 오류"""


class ValidationError(RuleStoreError):
    """저장 전 검증 실패 — errors 에 사유 목록"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("규칙 트리 검증 실패: " + " / ".join(errors))


# ─────────────────────────────────────────────────────────────
# 경로 해석 (경로 탈출 방지)
# ─────────────────────────────────────────────────────────────

def _resolve_path(tree_file: str, must_exist: bool = True) -> Path:
    """
    트리 파일명을 안전한 절대 경로로 해석한다.
    basename 만 취해 디렉터리 탈출(../)을 차단하고, .yaml 만 허용한다.
    """
    name = Path(str(tree_file)).name          # 경로 성분 제거 → 탈출 차단
    if not name.endswith(".yaml"):
        raise RuleStoreError(f"잘못된 트리 파일명(.yaml 아님): {tree_file!r}")
    path = (TREES_DIR / name).resolve()
    if path.parent != TREES_DIR.resolve():
        raise RuleStoreError(f"트리 디렉터리 밖 접근 거부: {tree_file!r}")
    if must_exist and not path.exists():
        raise RuleStoreError(f"트리 파일 없음: {name}")
    return path


# ─────────────────────────────────────────────────────────────
# 읽기 — 평문 dict (엔진과 동일 로더, JSON 직렬화 안전)
# ─────────────────────────────────────────────────────────────

def _region_of(file: str, meta: dict) -> tuple[str, str]:
    """트리의 관할 판별(한국/인니) — 관리 화면 분리용. (region 코드, 표시명)"""
    j = str(meta.get("jurisdiction") or "")
    law = str(meta.get("law") or "")
    if "OJK" in file or "POJK" in law or "인도네시아" in j or "OJK" in j:
        return "ID", (j or "인도네시아 (OJK)")
    return "KR", "한국 (금융소비자보호법)"


def list_trees() -> list[dict]:
    """trees/ 의 모든 YAML 트리 요약 목록 — 트리 선택/관리 UI용."""
    out: list[dict] = []
    for p in sorted(TREES_DIR.glob("*.yaml")):
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"[rule_store] 트리 요약 로드 실패 {p.name}: {e}")
            continue
        meta = data.get("meta", {}) or {}
        rules = _rules_of(data)
        region, juris = _region_of(p.name, meta)
        out.append({
            "file": p.name,
            "law": meta.get("law", ""),
            "name": meta.get("name", ""),
            "article": meta.get("article", ""),
            "region": region,
            "jurisdiction": juris,
            "n_rules": len(rules),
            "n_nodes": sum(len(r.get("nodes", []) or []) for r in rules),
        })
    return out


def read_tree(tree_file: str) -> dict:
    """
    트리 1개를 구조화 뷰(JSON 직렬화 안전)로 반환 — 결과 카드/트리뷰 UI용.
    편집/쓰기에는 load_raw 를 쓴다(주석 보존). 여기선 보기 전용이라 평문 로더.
    """
    path = _resolve_path(tree_file)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    meta = data.get("meta", {}) or {}
    rules_view = []
    for rule in _rules_of(data):
        nodes_view = []
        for node in rule.get("nodes", []) or []:
            om = node.get("on_match", {}) or {}
            nodes_view.append({
                "node_id": node.get("id", ""),
                "type": node.get("type", ""),
                "check": node.get("check", ""),
                "pattern": node.get("pattern", ""),
                "negate": bool(node.get("negate", False)),
                "flags": node.get("flags", ""),
                "origin": node.get("origin", ""),
                "enabled": bool(node.get("enabled", True)),
                "internal": bool(om.get("_internal", False)),
                "on_match": {
                    "result": om.get("result", ""),
                    "confidence": om.get("confidence", None),
                    "reason": om.get("reason", ""),
                    "citation": om.get("citation", ""),
                    "action": om.get("action", ""),
                    "source": om.get("source", ""),
                },
            })
        rules_view.append({
            "rule_id": rule.get("id", ""),
            "name": rule.get("name", ""),
            "law": rule.get("law", ""),
            "description": rule.get("description", ""),
            "nodes": nodes_view,
        })
    return {
        "file": path.name,
        "meta": {
            "law": meta.get("law", ""),
            "name": meta.get("name", ""),
            "article": meta.get("article", ""),
            "version": meta.get("version", ""),
        },
        "rules": rules_view,
    }


# ─────────────────────────────────────────────────────────────
# 편집용 라운드트립 로드 (주석 보존)
# ─────────────────────────────────────────────────────────────

def load_raw(tree_file: str):
    """
    ruamel 라운드트립으로 로드 → CommentedMap 반환(주석·구조 보존).
    피드백 동작(C)은 이걸 받아 필드 단위로 고친 뒤 safe_write 에 넘긴다.
    """
    path = _resolve_path(tree_file)
    y = _make_yaml(tree_file)
    with open(path, encoding="utf-8") as f:
        return y.load(f)


def dump_raw(data, tree_file: str | None = None) -> str:
    """CommentedMap → YAML 문자열(주석 보존). 미리보기/디버그용."""
    y = _make_yaml(tree_file)
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────
# 노드 탐색 — (rule_id, node_id) 로 편집 대상 특정 (A 역추적과 짝)
# ─────────────────────────────────────────────────────────────

def _rules_of(data) -> list:
    """rules: 리스트 반환. 단일 rule: 구조(legacy)도 지원."""
    if data is None:
        return []
    rules = data.get("rules")
    if rules:
        return list(rules)
    if "rule" in data:                       # legacy 단일 구조
        return [data["rule"]]
    return []


def iter_nodes(data) -> Iterator[tuple]:
    """(rule_block, node) 를 순회."""
    for rule in _rules_of(data):
        for node in rule.get("nodes", []) or []:
            yield rule, node


def find_node(data, rule_id: str, node_id: str):
    """
    (rule_id, node_id) 로 (rule_block, node) 를 찾아 반환.
    못 찾으면 RuleStoreError. node_id 단독으로도 매칭(rule_id 누락 대비).
    """
    # 1순위: rule_id + node_id 모두 일치
    for rule, node in iter_nodes(data):
        if rule.get("id") == rule_id and node.get("id") == node_id:
            return rule, node
    # 2순위: node_id 만 일치 (rule_id 가 비었거나 어긋난 경우)
    for rule, node in iter_nodes(data):
        if node.get("id") == node_id:
            return rule, node
    raise RuleStoreError(f"노드를 찾지 못함: rule_id={rule_id!r}, node_id={node_id!r}")


# ─────────────────────────────────────────────────────────────
# ① 저장 전 검증
# ─────────────────────────────────────────────────────────────

def validate_tree(data) -> list[str]:
    """
    트리 dict 를 검증하고 오류 목록을 반환한다(빈 리스트 = 통과).
    검사: 구조 존재 / 정규식 컴파일 / result enum / confidence 범위.
    """
    errors: list[str] = []

    rules = _rules_of(data)
    if not rules:
        errors.append("rules(또는 rule) 가 비어 있습니다.")
        return errors

    seen_node_ids: set[str] = set()
    for ri, rule in enumerate(rules):
        rid = rule.get("id", f"#{ri}")
        nodes = rule.get("nodes", []) or []
        for node in nodes:
            nid = node.get("id", "")
            tag = f"[{rid}/{nid or '?'}]"
            if not nid:
                errors.append(f"{tag} 노드 id 가 없습니다.")
            elif nid in seen_node_ids:
                errors.append(f"{tag} 노드 id 가 중복됩니다: {nid}")
            else:
                seen_node_ids.add(nid)

            ntype = node.get("type", "")

            # 정규식 컴파일 — rule 노드는 pattern 필수, 컴파일 실패 시 거부
            if ntype == "rule":
                pattern = node.get("pattern", "")
                if not pattern:
                    errors.append(f"{tag} rule 노드에 pattern 이 없습니다.")
                else:
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        errors.append(f"{tag} 정규식 컴파일 실패: {e}")

            # on_match 검증 (result enum / confidence 범위)
            om = node.get("on_match", {}) or {}
            result = om.get("result")
            if result is not None and result not in VALID_RESULTS:
                errors.append(
                    f"{tag} on_match.result 가 허용값 아님: {result!r} "
                    f"(허용: {sorted(VALID_RESULTS)})"
                )
            conf = om.get("confidence")
            if conf is not None:
                try:
                    cf = float(conf)
                except (TypeError, ValueError):
                    errors.append(f"{tag} confidence 가 숫자가 아닙니다: {conf!r}")
                else:
                    if not (0.0 <= cf <= 1.0):
                        errors.append(f"{tag} confidence 범위 벗어남(0.0~1.0): {cf}")

    return errors


# ─────────────────────────────────────────────────────────────
# ② 백업
# ─────────────────────────────────────────────────────────────

def _backup(path: Path) -> Path:
    """현재 파일을 타임스탬프 백업으로 복사 후 백업 경로 반환."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dst = BACKUP_DIR / f"{path.stem}.{ts}{path.suffix}"
    dst.write_bytes(path.read_bytes())
    return dst


# ─────────────────────────────────────────────────────────────
# ③ 원자적 교체 + safe_write 진입점
# ─────────────────────────────────────────────────────────────

def safe_write(data, tree_file: str, *, reason: str = "", actor: str = "") -> dict:
    """
    편집된 트리(data, ruamel CommentedMap 권장)를 안전하게 디스크에 반영한다.

    순서: 검증(메모리) → 임시파일 직렬화 → 재로드+재검증(디스크 산출물) →
          원본 백업 → os.replace(원자적) → 캐시 무효화.
    어느 단계가 실패해도 라이브 파일은 교체 직전까지 그대로다.

    Returns
    -------
    {"ok": True, "file": <name>, "backup": <path>, "bytes": <int>,
     "caches_cleared": <int>}
    """
    target = _resolve_path(tree_file, must_exist=True)

    # ① 메모리 검증 (빠른 실패)
    errs = validate_tree(data)
    if errs:
        raise ValidationError(errs)

    y = _make_yaml(tree_file)
    tmp_path: str | None = None
    try:
        # 임시 파일에 직렬화 (같은 디렉터리 → 동일 볼륨, os.replace 원자성 보장)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(target.parent), prefix=target.name + ".", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            y.dump(data, f)

        # ③-검증: 디스크 산출물을 엔진과 동일한 로더로 재로드 → 재검증
        with open(tmp_path, encoding="utf-8") as rf:
            reloaded = yaml.safe_load(rf)
        re_errs = validate_tree(reloaded)
        if re_errs:
            raise ValidationError(["(직렬화 후) " + e for e in re_errs])

        size = os.path.getsize(tmp_path)

        # ② 원본 백업 (교체 직전)
        backup = _backup(target)

        # ③ 원자적 교체
        os.replace(tmp_path, target)
        tmp_path = None  # 교체 성공 — finally 에서 지우지 않음
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # 캐시 무효화 (즉시 라이브 반영)
    cleared = invalidate_caches(target.name)

    logger.info(
        f"[rule_store] 저장 완료: {target.name} "
        f"(backup={backup.name}, caches_cleared={cleared}, actor={actor or '-'})"
    )
    return {
        "ok": True,
        "file": target.name,
        "backup": str(backup),
        "bytes": size,
        "caches_cleared": cleared,
    }


# ─────────────────────────────────────────────────────────────
# 캐시 무효화 — 탐지기 레지스트리 + 기본 엔진
# ─────────────────────────────────────────────────────────────

def invalidate_caches(tree_file: str | None = None) -> int:
    """
    저장된 트리에 대한 엔진 캐시를 비운다. (mtime 자동 재로드의 안전장치)
    tree_file=None 이면 전체. 실패해도 저장 자체는 성공으로 본다(방어적).
    반환: 비운 엔진 수.
    """
    cleared = 0
    # 탐지기 인스턴스들의 엔진 캐시
    try:
        from agents import agent2_detector as a2
        for det in list(getattr(a2, "_detectors", {}).values()):
            eng = getattr(det, "_engine", None)
            if eng is not None and hasattr(eng, "invalidate"):
                eng.invalidate(None)
                cleared += 1
    except Exception as e:                       # pragma: no cover - 방어적
        logger.warning(f"[rule_store] 탐지기 캐시 무효화 스킵: {e}")
    # 모듈 싱글턴 엔진
    try:
        from core import tree_engine as te
        if getattr(te, "_default_engine", None) is not None:
            te._default_engine.invalidate(None)
            cleared += 1
    except Exception as e:                        # pragma: no cover - 방어적
        logger.warning(f"[rule_store] 기본 엔진 캐시 무효화 스킵: {e}")
    return cleared


# ─────────────────────────────────────────────────────────────
# C. 피드백 동작 3종 (낮춤/올림/추가) + D. 가드레일·이력
#   모두 find_node + safe_write 공용. 진입점만 다르다.
# ─────────────────────────────────────────────────────────────

_RANK = {"PASS": 1, "WARNING": 2, "VIOLATION": 3}
_EXPERT_TAG = "전문가 추가 규칙 (citation 미지정)"


class JumpConfirmRequired(RuleStoreError):
    """VIOLATION→PASS 처럼 2단계 점프 시 재확인 요구 (실수로 진짜 위반 깔아뭉갬 방지)."""

    def __init__(self, frm: str, to: str):
        self.frm, self.to = frm, to
        super().__init__(
            f"2단계 점프({frm}→{to})는 재확인이 필요합니다. confirm_jump=True 로 다시 호출하세요."
        )


def _log_change(actor, action, tree_file, rule_id, node_id, field, before, after, reason, backup):
    """rule_changes 이력 기록 — 실패해도 저장 자체는 성공(방어적)."""
    try:
        from api.history import add_rule_change
        add_rule_change({
            "actor": actor, "action": action, "tree_file": tree_file,
            "rule_id": rule_id, "node_id": node_id, "field": field,
            "before": before, "after": after, "reason": reason, "backup": backup,
        })
    except Exception as e:                         # pragma: no cover - 방어적
        logger.warning(f"[rule_store] 이력 로깅 스킵: {e}")


def adjust_node(tree_file: str, rule_id: str, node_id: str, *,
                result: str | None = None, confidence: float | None = None,
                actor: str = "", change_reason: str = "",
                confirm_jump: bool = False) -> dict:
    """
    낮춤(과탐 교정)/올림(미탐 보강) 공용 — 특정 판정을 낸 규칙 노드의
    on_match.result(레벨) 또는 confidence 를 조정한다.
    · 2단계 점프(VIOLATION↔PASS)는 confirm_jump 없으면 JumpConfirmRequired.
    · 위험도 상향 시 citation 비면 'transparent' 출처 태그 자동 부착(D).
    """
    if result is None and confidence is None:
        raise RuleStoreError("변경할 값(result 또는 confidence)이 없습니다.")

    data = load_raw(tree_file)
    rule, node = find_node(data, rule_id, node_id)
    om = node.get("on_match")
    if om is None:
        raise RuleStoreError(f"노드 {node_id} 에 on_match 가 없어 조정 불가합니다.")

    before_r = om.get("result")
    before_c = om.get("confidence")
    changes: list[tuple] = []

    if result is not None:
        if result not in VALID_RESULTS:
            raise ValidationError([f"result 허용값 아님: {result!r}"])
        old_rank, new_rank = _RANK.get(before_r, 0), _RANK.get(result, 0)
        if old_rank and new_rank and abs(new_rank - old_rank) >= 2 and not confirm_jump:
            raise JumpConfirmRequired(before_r, result)
        if result != before_r:
            om["result"] = result
            changes.append(("result", before_r, result))

    if confidence is not None:
        cf = float(confidence)
        if not (0.0 <= cf <= 1.0):
            raise ValidationError([f"confidence 범위 0~1 벗어남: {cf}"])
        if before_c is None or float(before_c) != cf:
            om["confidence"] = cf
            changes.append(("confidence", before_c, cf))

    if not changes:
        return {"ok": True, "changes": [], "noop": True, "file": Path(tree_file).name}

    # 상향 여부 판정 (레벨↑ 또는 confidence↑)
    raising = (result is not None and _RANK.get(result, 0) > _RANK.get(before_r, 0)) or (
        confidence is not None and before_c is not None and float(confidence) > float(before_c)
    )
    if raising and not om.get("citation"):
        om["source"] = om.get("source") or _EXPERT_TAG

    res = safe_write(data, tree_file, reason=change_reason, actor=actor)

    action = "raise" if raising else "lower"
    for field, b, a in changes:
        _log_change(actor, action, res["file"], rule.get("id"), node_id,
                    field, b, a, change_reason, res["backup"])
    return {"ok": True, "action": action, "changes": changes, **res}


def add_rule_node(tree_file: str, rule_id: str, *, node_id: str, pattern: str,
                  reason: str, result: str = "WARNING", confidence: float = 0.85,
                  citation: str = "", action: str = "", flags: str = "IGNORECASE",
                  negate: bool = False, actor: str = "", change_reason: str = "") -> dict:
    """
    미탐 보강 — 기존 rule 블록(rule_id)에 새 rule 노드(키워드/패턴)를 삽입한다.
    citation 비면 '전문가 추가 규칙' 출처 태그 자동 부착(D, 추적성 유지).
    """
    from ruamel.yaml.comments import CommentedMap

    data = load_raw(tree_file)
    rules = data.get("rules")
    if not rules:
        raise RuleStoreError("rules 구조 트리에만 노드 추가가 가능합니다.")
    block = next((r for r in rules if r.get("id") == rule_id), None)
    if block is None:
        raise RuleStoreError(f"규칙 블록을 찾지 못함: {rule_id!r}")
    if any(n.get("id") == node_id for _, n in iter_nodes(data)):
        raise RuleStoreError(f"이미 존재하는 node_id: {node_id!r}")

    om = CommentedMap()
    om["result"] = result
    om["confidence"] = float(confidence)
    om["reason"] = reason
    if citation:
        om["citation"] = citation
    else:
        om["source"] = _EXPERT_TAG
    if action:
        om["action"] = action

    new_node = CommentedMap()
    new_node["id"] = node_id
    new_node["type"] = "rule"
    new_node["check"] = change_reason or "전문가 추가 규칙"
    new_node["pattern"] = pattern
    new_node["flags"] = flags
    if negate:
        new_node["negate"] = True
    new_node["origin"] = "expert"           # 전문가 추가 룰 — 삭제 허용 판별용(원본 보호)
    new_node["on_match"] = om

    nodes = block.setdefault("nodes", [])
    # rule 노드 그룹 끝(첫 비-rule 노드 앞)에 삽입 → 평가 순서 자연스럽게
    insert_at = len(nodes)
    for i, n in enumerate(nodes):
        if n.get("type") != "rule":
            insert_at = i
            break
    nodes.insert(insert_at, new_node)

    res = safe_write(data, tree_file, reason=change_reason, actor=actor)
    _log_change(actor, "add", res["file"], rule_id, node_id, "node",
                "", f"{result} (conf={confidence}) pattern={pattern}",
                change_reason, res["backup"])
    return {"ok": True, "action": "add", "node_id": node_id, **res}


def add_rule_block(tree_file: str, *, name: str, block_id: str = "",
                   law: str = "", actor: str = "", change_reason: str = "") -> dict:
    """
    위반 유형(규칙 블록)을 트리에 추가한다 — 한 법령 안에서 조문·유형별로
    규칙을 묶기 위한 상위 그룹. 이후 add_rule_node 로 이 블록에 규칙을 채운다.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not (name or "").strip():
        raise RuleStoreError("위반 유형(블록) 이름은 필수입니다.")
    data = load_raw(tree_file)
    rules = data.get("rules")
    if rules is None:
        raise RuleStoreError("rules 구조 트리에만 블록 추가가 가능합니다.")

    # 블록 id 자동 채번 (충돌 방지)
    existing = {r.get("id") for r in rules}
    bid = (block_id or "").strip()
    if not bid or bid in existing:
        n = len(rules) + 1
        while f"rule_block_{n}" in existing:
            n += 1
        bid = f"rule_block_{n}"

    block = CommentedMap()
    block["id"] = bid
    block["law"] = law or (data.get("meta", {}) or {}).get("law", "")
    block["name"] = name
    block["nodes"] = CommentedSeq()
    rules.append(block)

    res = safe_write(data, tree_file, reason=change_reason, actor=actor)
    _log_change(actor, "add_block", res["file"], bid, "", "block",
                "", f"위반유형 신설: {name}", change_reason, res["backup"])
    return {"ok": True, "action": "add_block", "rule_id": bid, "name": name, **res}


# ── 삭제 / 비활성화 (원본 보호: 삭제는 전문가 추가 룰만, 원본은 비활성화) ──

def _is_expert(node, node_id: str = "") -> bool:
    """전문가가 추가한 노드인지 — origin 마커 우선, 과거 노드는 휴리스틱 폴백."""
    if (node or {}).get("origin") == "expert":
        return True
    nid = node_id or (node or {}).get("id", "")
    if str(nid).startswith("rule_expert_"):
        return True
    return ((node or {}).get("on_match") or {}).get("source") == _EXPERT_TAG


def _node_brief(node) -> str:
    om = node.get("on_match", {}) or {}
    return (f"id={node.get('id')} type={node.get('type')} "
            f"result={om.get('result')} pattern={node.get('pattern', '')}")


def delete_node(tree_file: str, rule_id: str, node_id: str, *,
                actor: str = "", change_reason: str = "") -> dict:
    """
    노드 삭제 — 전문가 추가 룰(origin=expert)만 허용. 원본 법령 룰은 거부하고
    비활성화/낮춤을 안내한다(법적 커버리지를 흔적 없이 잃지 않도록).
    safe_write 가 삭제 직전 백업을 남기고, rule_changes 에 before=노드 요약을 기록한다.
    """
    data = load_raw(tree_file)
    rule, node = find_node(data, rule_id, node_id)
    if not _is_expert(node, node_id):
        raise RuleStoreError(
            "원본 법령 룰은 삭제할 수 없습니다. '비활성화(끄기)' 또는 '낮춤'을 사용하세요."
        )
    before = _node_brief(node)
    nodes = rule.get("nodes", []) or []
    idx = next((i for i, n in enumerate(nodes) if n.get("id") == node_id), None)
    if idx is None:
        raise RuleStoreError(f"노드를 찾지 못함: {node_id!r}")
    nodes.pop(idx)
    res = safe_write(data, tree_file, reason=change_reason, actor=actor)
    _log_change(actor, "delete", res["file"], rule.get("id"), node_id,
                "node", before, "(삭제됨)", change_reason, res["backup"])
    return {"ok": True, "action": "delete", "node_id": node_id, **res}


def set_enabled(tree_file: str, rule_id: str, node_id: str, enabled: bool, *,
                actor: str = "", change_reason: str = "") -> dict:
    """
    노드 켜기/끄기 — 원본·추가 공통. enabled=False 면 엔진이 평가에서 건너뛴다.
    원래 result/confidence 는 보존되어 재활성 시 그대로 복원된다(가역적·이력 남김).
    """
    data = load_raw(tree_file)
    rule, node = find_node(data, rule_id, node_id)
    cur = bool(node.get("enabled", True))
    if cur == bool(enabled):
        return {"ok": True, "noop": True, "file": Path(tree_file).name}
    if enabled:
        node.pop("enabled", None)           # 기본값(켜짐)으로 — YAML 깔끔하게
    else:
        node["enabled"] = False
    res = safe_write(data, tree_file, reason=change_reason, actor=actor)
    _log_change(actor, "enable" if enabled else "disable", res["file"],
                rule.get("id"), node_id, "enabled",
                "켜짐" if cur else "꺼짐", "켜짐" if enabled else "꺼짐",
                change_reason, res["backup"])
    return {"ok": True, "action": "enable" if enabled else "disable", **res}


# ── 새 법령 트리 생성 (코드 수정 없이 신규 관할/법령 라이브 추가) ──

def create_tree(file: str, *, law: str, name: str = "", jurisdiction: str = "",
                article: str = "", first_block_id: str = "", first_block_name: str = "",
                actor: str = "", change_reason: str = "") -> dict:
    """
    새 법령 트리(YAML)를 생성한다. meta + 빈 규칙 블록 1개를 스캐폴딩 →
    이후 add_rule_node 로 규칙을 채운다. 라우팅은 meta.jurisdiction 으로 자동 판별(KR/ID).
    검증→임시파일→재검증→원자적 생성(os.replace)→캐시 무효화.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if not (law or "").strip():
        raise RuleStoreError("law(법령명)은 필수입니다.")
    name_f = Path(str(file)).name
    if not name_f.endswith(".yaml"):
        name_f += ".yaml"
    path = (TREES_DIR / name_f).resolve()
    if path.parent != TREES_DIR.resolve():
        raise RuleStoreError(f"트리 디렉터리 밖 접근 거부: {file!r}")
    if path.exists():
        raise RuleStoreError(f"이미 존재하는 트리 파일입니다: {name_f}")

    meta = CommentedMap()
    meta["law"] = law
    if article:
        meta["article"] = article
    meta["name"] = name or law
    if jurisdiction:
        meta["jurisdiction"] = jurisdiction
    meta["version"] = "1.0"
    sev = CommentedMap()
    sev["VIOLATION"] = 1.0
    sev["WARNING"] = 0.6
    sev["PASS"] = 0.0
    meta["severity_weights"] = sev

    block = CommentedMap()
    block["id"] = first_block_id or "rule_block_1"
    block["law"] = law
    block["name"] = first_block_name or (name or law)
    block["nodes"] = CommentedSeq()

    data = CommentedMap()
    data["meta"] = meta
    data["rules"] = CommentedSeq([block])

    errs = validate_tree(data)
    if errs:
        raise ValidationError(errs)

    y = _make_yaml(name_f)
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(TREES_DIR), prefix=name_f + ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            y.dump(data, f)
        with open(tmp_path, encoding="utf-8") as rf:
            reloaded = yaml.safe_load(rf)
        re_errs = validate_tree(reloaded)
        if re_errs:
            raise ValidationError(["(직렬화 후) " + e for e in re_errs])
        os.replace(tmp_path, path)        # 신규 파일 원자적 생성
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    cleared = invalidate_caches(name_f)
    _log_change(actor, "create_tree", name_f, block["id"], "", "tree",
                "", f"law={law} / jurisdiction={jurisdiction or 'KR(기본)'}",
                change_reason, "")
    logger.info(f"[rule_store] 새 트리 생성: {name_f} (law={law}, caches_cleared={cleared})")
    return {"ok": True, "action": "create_tree", "file": name_f, "rule_id": block["id"]}
