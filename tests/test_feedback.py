"""
tests/test_feedback.py — C 피드백 3종 + D 가드레일·이력 검증.
임시 트리 복사본으로 동작시키고, 엔진 직접 평가로 라이브 반영을 확인.
실제 파일·DB 오염은 종료 시 정리.

실행: C:\\ProgramData\\Anaconda3\\python.exe LexAide_ai\\tests\\test_feedback.py
"""
from __future__ import annotations
import sys, sqlite3
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from core import rule_store as rs
from core.tree_engine import TreeEngine

_SRC = rs.TREES_DIR / "금소법_22조_광고규제.yaml"
_TMP = rs.TREES_DIR / "__cd_test.yaml"
NAME = _TMP.name


def _node(view, nid):
    for r in view["rules"]:
        for n in r["nodes"]:
            if n["node_id"] == nid:
                return n
    raise AssertionError(nid)


def setup():
    _TMP.write_bytes(_SRC.read_bytes())


def teardown():
    if _TMP.exists():
        _TMP.unlink()
    for b in rs.BACKUP_DIR.glob(f"{_TMP.stem}.*.yaml"):
        b.unlink()
    for t in rs.TREES_DIR.glob(f"{NAME}.*.tmp"):
        t.unlink()
    db = _ROOT / "data" / "review_history.db"
    c = sqlite3.connect(str(db))
    c.execute("DELETE FROM rule_changes WHERE tree_file=?", (NAME,))
    c.commit(); c.close()


def test_lower():
    r = rs.adjust_node(NAME, "finsumer_22_1_단정적표현", "rule_22_1_a",
                       result="WARNING", actor="tester", change_reason="과탐 같아 낮춤")
    assert r["action"] == "lower" and ("result", "VIOLATION", "WARNING") in r["changes"]
    assert _node(rs.read_tree(NAME), "rule_22_1_a")["on_match"]["result"] == "WARNING"
    print("  ✓ 낮춤(과탐교정) VIOLATION→WARNING + 이력기록")


def test_two_step_jump_guard():
    blocked = False
    try:
        rs.adjust_node(NAME, "finsumer_22_2_원금보장", "rule_22_2_a", result="PASS")
    except rs.JumpConfirmRequired:
        blocked = True
    assert blocked, "2단계 점프가 막히지 않음"
    r = rs.adjust_node(NAME, "finsumer_22_2_원금보장", "rule_22_2_a",
                       result="PASS", confirm_jump=True, actor="t", change_reason="확인후 강제")
    assert _node(rs.read_tree(NAME), "rule_22_2_a")["on_match"]["result"] == "PASS"
    print("  ✓ 2단계 점프 가드: 미확인 차단 / confirm_jump 통과")


def test_add_and_live():
    # 미탐 보강: '평생 보장' 새 규칙 추가 (citation 명시)
    rs.add_rule_node(NAME, "finsumer_22_2_원금보장", node_id="rule_22_2_평생보장",
                     pattern=r"평생\s*보장", reason="평생 보장 단정 표현은 원금/지급 보장 오인 소지",
                     result="VIOLATION", confidence=0.9,
                     citation="금융소비자보호법 제22조 및 동법 시행령 제19조",
                     actor="tester", change_reason="평생보장 미탐 보강")
    n = _node(rs.read_tree(NAME), "rule_22_2_평생보장")
    assert n["on_match"]["result"] == "VIOLATION" and n["on_match"]["citation"]
    # 라이브: 새 엔진이 파일에서 즉시 새 규칙을 집어 VIOLATION
    res = TreeEngine(llm_client=None).evaluate_file(_TMP, "평생 보장되는 든든한 보험")
    assert res.overall_result == "VIOLATION", res.overall_result
    assert any(v.node_id == "rule_22_2_평생보장" for v in res.all_violations)
    print("  ✓ 추가(미탐보강)→저장→엔진 즉시 VIOLATION (라이브 반영)")


def test_citation_autotag():
    rs.add_rule_node(NAME, "finsumer_22_1_단정적표현", node_id="rule_22_1_notag",
                     pattern=r"무위험\s*고수익", reason="무위험 고수익 표현",
                     result="WARNING", actor="t", change_reason="태그 테스트")
    n = _node(rs.read_tree(NAME), "rule_22_1_notag")
    assert n["on_match"]["source"] == rs._EXPERT_TAG, n["on_match"]
    print("  ✓ citation 비우면 '전문가 추가 규칙' 출처 태그 자동 부착")


def test_change_log():
    from api.history import list_rule_changes
    rows = [r for r in list_rule_changes(100) if r["tree_file"] == NAME]
    actions = {r["action"] for r in rows}
    assert {"lower", "add"} <= actions, actions
    assert any(r["before"] == "VIOLATION" and r["after"] == "WARNING" for r in rows)
    print(f"  ✓ 이력 로깅: {len(rows)}건 (이전값→이후값·누가·왜 기록)")


TESTS = [test_lower, test_two_step_jump_guard, test_add_and_live,
         test_citation_autotag, test_change_log]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("C 피드백 3종 + D 가드레일·이력 테스트")
    print("=" * 60)
    failed = 0
    setup()
    try:
        for t in TESTS:
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
