"""
api/law_monitor.py — 규제 변경 모니터링 (본선 로드맵 마지막 항목)

원리
  · 감시 대상은 하드코딩이 아니라 **트리에서 자동 도출** — KR 트리의 근거 법령(+시행령).
    → 전문가가 새 법령 트리를 만들면 그 법령도 자동으로 감시망에 편입된다.
  · 국가법령정보 Open API(lawSearch)의 공포일자·시행일자·제개정구분을
    기준 스냅샷(data/law_watch.json)과 비교해 개정을 감지한다.
  · 감지는 자동, 해석·대응은 전문가(HITL) — 자동 규칙 수정은 하지 않는다.
    대응 수단은 이미 있는 편집기: 기준 조정 / 적용 중지 / 신설(구 규칙 중지 + 신 규칙 신설).
  · OJK(인니)는 공식 API가 없어 감시 제외(정직한 한계, 장기 과제).
"""
from __future__ import annotations

import json
import logging
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path

from api.law_api import _get, _BASE, _OC, _base_law_name, _viewer_link

logger = logging.getLogger(__name__)

_STATE_PATH = Path(__file__).parent.parent / "data" / "law_watch.json"
_lock = threading.Lock()
_FRESH_HOURS = 12          # 이 시간 내 점검 결과는 재사용(자동 열람 시 API 스팸 방지)


# ── 감시 대상: KR 트리의 근거 법령 + 시행령 (트리 추가 시 자동 편입) ──

def _watched_laws() -> list[str]:
    from core.rule_store import list_trees
    laws: list[str] = []
    for t in list_trees():
        if t.get("region") != "KR":
            continue                     # OJK는 API 부재로 감시 제외(정직한 한계)
        base = _base_law_name(t.get("law", ""))
        if not base:
            continue
        for name in (base, f"{base} 시행령"):
            if name not in laws:
                laws.append(name)
    return laws


# ── 법령 메타(공포·시행일자) 조회 ──

def _fetch_law_meta(law_name: str) -> dict | None:
    """lawSearch에서 첫 결과의 공포일자·시행일자·제개정구분을 추출."""
    xml = _get(f"{_BASE}/lawSearch.do",
               {"OC": _OC, "target": "law", "type": "XML", "query": law_name})
    if xml is None:
        return None
    try:
        root = ET.fromstring(xml)
        first = root.find(".//law")
        if first is None:
            return None
        official = (first.findtext("법령명한글") or "").strip()
        return {
            "official_name": official,
            "공포일자": (first.findtext("공포일자") or "").strip(),
            "시행일자": (first.findtext("시행일자") or "").strip(),
            "제개정구분": (first.findtext("제개정구분명") or "").strip(),
            "link": _viewer_link(official),
        }
    except ET.ParseError:
        return None


# ── 상태 파일 ──

def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"baseline": {}, "last": {}, "checked_at": ""}


def _save_state(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def _is_fresh(checked_at: str) -> bool:
    try:
        dt = datetime.fromisoformat(checked_at)
    except Exception:
        return False
    return (datetime.now() - dt).total_seconds() < _FRESH_HOURS * 3600


def _upcoming_days(효력일: str) -> int | None:
    """시행일자가 미래면 D-n 반환 (YYYYMMDD)."""
    try:
        d = datetime.strptime(효력일, "%Y%m%d").date()
    except Exception:
        return None
    delta = (d - date.today()).days
    return delta if delta > 0 else None


# ── 진입점 ──

def check_updates(refresh: bool = False) -> dict:
    """
    감시 법령 점검. refresh=False면 12시간 내 결과 재사용.
    첫 점검 법령은 현재 상태를 기준(baseline)으로 저장한다.
    """
    with _lock:
        state = _load_state()
        watched = _watched_laws()

        if refresh or not _is_fresh(state.get("checked_at", "")) \
                or any(w not in state.get("last", {}) for w in watched):
            for name in watched:
                meta = _fetch_law_meta(name)
                if meta is None:
                    continue                     # 네트워크 실패 → 기존 값 유지
                state.setdefault("last", {})[name] = meta
                if name not in state.setdefault("baseline", {}):
                    state["baseline"][name] = dict(meta)   # 최초 점검 = 기준 저장
            state["checked_at"] = datetime.now().isoformat(timespec="seconds")
            _save_state(state)

        items = []
        for name in watched:
            cur = state.get("last", {}).get(name)
            base = state.get("baseline", {}).get(name)
            if not cur:
                items.append({"law": name, "status": "unreachable"})
                continue
            changed = bool(base) and (
                cur.get("공포일자") != base.get("공포일자")
                or cur.get("시행일자") != base.get("시행일자")
            )
            items.append({
                "law": name,
                "official_name": cur.get("official_name", name),
                "status": "updated" if changed else "ok",
                "baseline": base,
                "current": cur,
                "upcoming_days": _upcoming_days(cur.get("시행일자", "")),
                "link": cur.get("link"),
            })
        return {"checked_at": state.get("checked_at", ""), "items": items}


def acknowledge(law_name: str) -> dict:
    """개정 확인 처리 — 현재 상태를 새 기준으로 저장(트리 대응 완료 후 호출)."""
    with _lock:
        state = _load_state()
        cur = state.get("last", {}).get(law_name)
        if not cur:
            return {"ok": False, "error": f"점검 이력이 없는 법령: {law_name}"}
        state.setdefault("baseline", {})[law_name] = dict(cur)
        _save_state(state)
        return {"ok": True, "law": law_name}
