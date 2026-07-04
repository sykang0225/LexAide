"""
tests/test_rule_store.py
────────────────────────────────────────────────────────────────
규칙 저장소(core/rule_store.py) 안전쓰기 API 최소 테스트.

핵심(일정 make-or-break):
  1. 주석 보존 왕복  — 노드 편집→저장→재로드 시 # 법적근거 주석이 전부 살아있고 편집도 반영
  2. 원자성          — 검증 실패 저장은 라이브 파일을 절대 건드리지 않음(임시파일 잔여 0)
  3. 라이브 리로드   — 저장 후 엔진이 다음 로드에서 새 값을 집어 옴(mtime 자동 재로드)

pytest 없이도 돌도록 plain assert + __main__ 러너. 실제 트리는 임시 복사본으로 대체해
테스트하고 종료 시 정리한다(원본 불변).

실행: C:\\ProgramData\\Anaconda3\\python.exe -m tests.test_rule_store
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import rule_store as rs
from core.tree_engine import TreeEngine

# 실제 트리를 복사해 만든 임시 대상(원본 불변 보장)
_SRC = rs.TREES_DIR / "금소법_22조_광고규제.yaml"
_TMP = rs.TREES_DIR / "__rule_store_test.yaml"
_TMP_NAME = _TMP.name
_TARGET_RULE = "finsumer_22_1_단정적표현"
_TARGET_NODE = "rule_22_1_a"


def _count_comment_lines(path: Path) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            n += 1
    return n


def setup() -> None:
    _TMP.write_bytes(_SRC.read_bytes())


def teardown() -> None:
    if _TMP.exists():
        _TMP.unlink()
    # 이 테스트가 만든 백업 정리
    for b in rs.BACKUP_DIR.glob(f"{_TMP.stem}.*.yaml"):
        b.unlink()
    # 혹시 남은 임시파일 정리
    for t in rs.TREES_DIR.glob(f"{_TMP_NAME}.*.tmp"):
        t.unlink()


# ── 1. 주석 보존 왕복 (최우선) ─────────────────────────────────
def test_comment_roundtrip() -> None:
    before_comments = _count_comment_lines(_TMP)
    assert before_comments >= 40, f"기준 주석 수가 예상보다 적음: {before_comments}"

    data = rs.load_raw(_TMP_NAME)
    rule, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    node["on_match"]["confidence"] = 0.55
    node["on_match"]["reason"] = "왕복 테스트 수정 사유"
    res = rs.safe_write(data, _TMP_NAME, reason="roundtrip test", actor="tester")
    assert res["ok"] and res["bytes"] > 0

    # 주석 보존 확인 — 편집 후에도 주석 수가 줄지 않음
    after_comments = _count_comment_lines(_TMP)
    assert after_comments == before_comments, (
        f"주석이 사라짐: {before_comments} → {after_comments}"
    )
    # 대표 법적근거 주석이 실제로 살아있는지(문자열 단위)
    text = _TMP.read_text(encoding="utf-8")
    assert "법학 전공자 검수" in text, "법적근거 주석 유실"
    assert "금감원 2025.2.10 ETF 광고 점검" in text, "권위근거 주석 유실"

    # 편집이 실제 반영됐는지(구조화 재로드)
    view = rs.read_tree(_TMP_NAME)
    n = _find_node_view(view, _TARGET_NODE)
    assert n["on_match"]["confidence"] == 0.55, n["on_match"]["confidence"]
    assert n["on_match"]["reason"] == "왕복 테스트 수정 사유"

    # 백업이 실제로 생겼는지
    assert Path(res["backup"]).exists(), "백업 파일 미생성"
    print(f"  ✓ 주석 보존 왕복 — 주석 {after_comments}줄 보존 + 편집 반영 + 백업 생성")


# ── 2. 검증 거부 ───────────────────────────────────────────────
def test_validation_rejects() -> None:
    # 잘못된 정규식
    data = rs.load_raw(_TMP_NAME)
    _, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    node["pattern"] = "(미닫힌+괄호"        # 컴파일 실패 패턴
    errs = rs.validate_tree(data)
    assert any("정규식" in e for e in errs), errs

    # 잘못된 result enum
    data = rs.load_raw(_TMP_NAME)
    _, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    node["on_match"]["result"] = "SUPER_VIOLATION"
    errs = rs.validate_tree(data)
    assert any("result" in e for e in errs), errs

    # confidence 범위 초과
    data = rs.load_raw(_TMP_NAME)
    _, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    node["on_match"]["confidence"] = 1.7
    errs = rs.validate_tree(data)
    assert any("confidence" in e for e in errs), errs

    # 정상 데이터는 통과
    assert rs.validate_tree(rs.load_raw(_TMP_NAME)) == []
    print("  ✓ 검증 — 정규식/result/confidence 불량 거부, 정상 통과")


# ── 3. 원자성: 검증 실패 저장은 라이브 파일 불변 ───────────────
def test_atomic_unchanged_on_failure() -> None:
    before = _TMP.read_bytes()
    data = rs.load_raw(_TMP_NAME)
    _, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    node["pattern"] = "((("                  # 깨진 정규식 → 거부돼야 함
    raised = False
    try:
        rs.safe_write(data, _TMP_NAME)
    except rs.ValidationError:
        raised = True
    assert raised, "검증 실패인데 예외가 안 났음"
    assert _TMP.read_bytes() == before, "검증 실패 저장이 라이브 파일을 바꿈"
    leftovers = list(rs.TREES_DIR.glob(f"{_TMP_NAME}.*.tmp"))
    assert not leftovers, f"임시파일 잔여: {leftovers}"
    print("  ✓ 원자성 — 검증 실패 시 라이브 파일 불변 + 임시파일 잔여 0")


# ── 4. 라이브 리로드: 저장 후 엔진이 새 값을 집어옴 ─────────────
def test_live_reload() -> None:
    eng = TreeEngine(llm_client=None)
    d1 = eng.load(_TMP)
    c1 = _engine_confidence(d1, _TARGET_RULE, _TARGET_NODE)

    data = rs.load_raw(_TMP_NAME)
    _, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    node["on_match"]["confidence"] = 0.42
    rs.safe_write(data, _TMP_NAME, reason="reload test")

    d2 = eng.load(_TMP)                       # 같은 엔진이 mtime 변화 감지 → 재로드
    c2 = _engine_confidence(d2, _TARGET_RULE, _TARGET_NODE)
    assert c2 == 0.42, f"엔진이 새 값을 못 읽음: {c1} → {c2}"
    assert d1 is not d2 or c1 != c2, "캐시가 갱신되지 않음"
    print(f"  ✓ 라이브 리로드 — 엔진 캐시 자동 갱신 {c1} → {c2}")


# ── 5. find_node ──────────────────────────────────────────────
def test_find_node() -> None:
    data = rs.load_raw(_TMP_NAME)
    rule, node = rs.find_node(data, _TARGET_RULE, _TARGET_NODE)
    assert node["id"] == _TARGET_NODE
    raised = False
    try:
        rs.find_node(data, _TARGET_RULE, "존재하지않는노드")
    except rs.RuleStoreError:
        raised = True
    assert raised
    print("  ✓ find_node — 정상 탐색 + 미존재 시 오류")


# ── 헬퍼 ──────────────────────────────────────────────────────
def _find_node_view(view: dict, node_id: str) -> dict:
    for rule in view["rules"]:
        for n in rule["nodes"]:
            if n["node_id"] == node_id:
                return n
    raise AssertionError(f"뷰에서 노드 못 찾음: {node_id}")


def _engine_confidence(tree_data: dict, rule_id: str, node_id: str):
    for rule in tree_data.get("rules", []):
        if rule.get("id") == rule_id:
            for n in rule.get("nodes", []):
                if n.get("id") == node_id:
                    return n["on_match"]["confidence"]
    raise AssertionError("엔진 데이터에서 노드 못 찾음")


_TESTS = [
    test_comment_roundtrip,
    test_validation_rejects,
    test_atomic_unchanged_on_failure,
    test_live_reload,
    test_find_node,
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("rule_store 안전쓰기 API 테스트")
    print("=" * 60)
    failed = 0
    setup()
    try:
        for t in _TESTS:
            try:
                t()
            except Exception as e:
                failed += 1
                print(f"  ✗ {t.__name__}: {e}")
    finally:
        teardown()
    print("-" * 60)
    print("결과:", "전체 통과 ✅" if failed == 0 else f"{failed}건 실패 ❌")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
