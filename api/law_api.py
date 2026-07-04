"""
api/law_api.py
────────────────────────────────────────────────────────────────
국가법령정보 공동활용 Open API 클라이언트 (law.go.kr DRF)

용도
  Agent 4 자기검증 — 인용된 법령·조문이 실제로 존재하는지 실시간 확인

핵심
  - type=XML 로 호출 (JSON은 미신청 상태라 에러)
  - 법령 검색(lawSearch) → MST 획득 → 본문(lawService)에서 조문 존재 확인
  - 네트워크 실패/미승인 시 graceful 폴백 (로컬 검증으로 대체)
  - 결과 캐싱 (동일 조회 반복 방지)

OC(기관코드): .env 의 LAW_API_KEY
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
import re
import json
import logging
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

_OC = os.environ.get("LAW_API_KEY", "kangsy25law")
_BASE = "https://www.law.go.kr/DRF"
_TIMEOUT = 4  # 빠른 응답을 위해 4초로 단축 (서버 응답이 안정적)
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/xml, text/xml, */*",
}
_SESSION = requests.Session()
_SESSION.trust_env = False

_cache: dict[str, dict] = {}
_lock = threading.Lock()
_ART_RE = re.compile(r"제\s*(\d+)\s*조")

# ── 영속 캐시 (서버 재시작 후에도 유지) ──────────────────────────
_CACHE_DIR = Path(__file__).parent.parent / "data" / "law_cache"
_CACHE_FILE = _CACHE_DIR / "cache.json"
_disk_dirty = False   # 저장 필요 여부 플래그


def _load_disk_cache() -> None:
    """서버 시작 시 디스크 캐시를 메모리로 읽어옴."""
    global _cache
    if not _CACHE_FILE.exists():
        return
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            loaded = json.load(f)
        with _lock:
            _cache.update(loaded)
        logger.info(f"[law_api] 영속 캐시 로드 — {len(loaded)}건")
    except Exception as e:
        logger.warning(f"[law_api] 영속 캐시 로드 실패 (무시): {e}")


def _save_disk_cache() -> None:
    """메모리 캐시를 디스크에 저장 (lock 보유 상태에서 호출 금지)."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            snapshot = dict(_cache)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[law_api] 영속 캐시 저장 실패 (무시): {e}")


# 모듈 임포트 시 디스크 캐시 자동 로드
_load_disk_cache()


def _get(url: str, params: dict) -> str | None:
    last_err = None
    for attempt in range(2):  # 연결 리셋 대비 1회 재시도
        try:
            r = _SESSION.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            if r.status_code == 200 and r.text.lstrip().startswith("<?xml"):
                return r.text
            return None
        except Exception as e:
            last_err = e
            if attempt == 0:
                import time as _t
                _t.sleep(0.2)  # 재시도 전 짧게 대기 (0.4 → 0.2)
    logger.warning(f"[law_api] 호출 실패(재시도 후): {last_err}")
    return None


def _base_law_name(text: str) -> str:
    """인용문에서 법령명 후보만 추출."""
    base_name = re.split(r"\s*제\d+조|\s*및\s*|\s*\(", text)[0].strip()
    return base_name.replace("동법", "").strip() or text.strip()


def _viewer_link(official_name: str, article_no: str | None = None) -> str | None:
    if not official_name:
        return None
    law_path = quote(official_name.replace(" ", ""), safe="")
    law_root = quote("법령", safe="")
    if article_no:
        article_path = quote(f"제{article_no}조", safe="")
        return f"https://www.law.go.kr/{law_root}/{law_path}/{article_path}"
    return f"https://www.law.go.kr/{law_root}/{law_path}"


def _search_law(law_name: str) -> dict:
    """
    법령명이 국가법령정보에 실제로 존재하는지 확인.

    Returns
    -------
    {"verified": bool, "law_name": str, "mst": str|None,
     "official_name": str|None, "source": "api"|"offline", "link": str|None}
    """
    base_name = _base_law_name(law_name)

    key = f"law::{base_name}"
    with _lock:
        if key in _cache:
            return _cache[key]

    xml = _get(f"{_BASE}/lawSearch.do",
               {"OC": _OC, "target": "law", "type": "XML", "query": base_name})

    if xml is None:
        result = {"verified": False, "law_name": base_name, "mst": None,
                  "official_name": None, "source": "offline", "link": None}
    else:
        try:
            root = ET.fromstring(xml)
            first = root.find(".//law")
            if first is not None:
                official = (first.findtext("법령명한글") or "").strip()
                mst = (first.findtext("법령일련번호") or "").strip()
                link = _viewer_link(official)
                result = {"verified": True, "law_name": base_name, "mst": mst or None,
                          "official_name": official or None, "source": "api", "link": link}
            else:
                result = {"verified": False, "law_name": base_name, "mst": None,
                          "official_name": None, "source": "api", "link": None}
        except ET.ParseError:
            result = {"verified": False, "law_name": base_name, "mst": None,
                      "official_name": None, "source": "api", "link": None}

    # 오프라인(네트워크 실패)은 캐시하지 않음 → 다음 호출에서 재시도
    if result.get("source") != "offline":
        with _lock:
            _cache[key] = result
        _save_disk_cache()   # 영속 캐시 갱신
    return result


def _article_exists(mst: str, article_no: str) -> bool:
    """lawService 본문 XML에서 조문번호 존재 여부 확인."""
    if not mst or not article_no:
        return False
    key = f"article::{mst}::{article_no}"
    with _lock:
        if key in _cache:
            return bool(_cache[key].get("verified"))

    xml = _get(f"{_BASE}/lawService.do",
               {"OC": _OC, "target": "law", "type": "XML", "MST": mst})
    verified = False
    if xml:
        try:
            root = ET.fromstring(xml)
            for node in root.findall(".//조문단위"):
                if (node.findtext("조문여부") or "").strip() != "조문":
                    continue
                if (node.findtext("조문번호") or "").strip() == str(article_no):
                    verified = True
                    break
        except ET.ParseError:
            verified = False

    with _lock:
        _cache[key] = {"verified": verified}
    _save_disk_cache()   # 영속 캐시 갱신
    return verified


def _split_citation_refs(citation: str) -> list[dict]:
    """복합 인용을 개별 법령/조문 단위로 분해."""
    first_law = _base_law_name(citation)
    refs: list[dict] = []
    for raw in re.split(r"\s*및\s*|[,;]\s*", citation):
        part = raw.strip()
        if not part:
            continue

        article_match = _ART_RE.search(part)
        article_no = article_match.group(1) if article_match else None
        law_part = _base_law_name(part)

        if part.startswith("동법 시행령"):
            law_part = f"{first_law} 시행령"
        elif part.startswith("동법"):
            law_part = first_law
        elif "시행령" in part and "법" not in law_part:
            law_part = f"{first_law} 시행령"

        refs.append({"law_name": law_part, "article_no": article_no})
    return refs or [{"law_name": first_law, "article_no": None}]


def verify_citation(citation: str) -> dict:
    """
    복합 인용을 법령·조문 단위로 검증.

    Returns
    -------
    {
      "verified": bool,
      "source": "api"|"offline",
      "official_name": str,
      "link": str|None,
      "refs": [
        {"law_name", "official_name", "article_no", "law_verified",
         "article_verified", "link", "source"}
      ]
    }
    """
    refs = []
    for ref in _split_citation_refs(citation):
        law_info = _search_law(ref["law_name"])
        law_verified = bool(law_info.get("verified"))
        article_no = ref.get("article_no")
        article_verified = True
        if article_no:
            article_verified = bool(law_info.get("mst")) and _article_exists(law_info["mst"], article_no)

        official = law_info.get("official_name") or ""
        refs.append({
            "law_name": ref["law_name"],
            "official_name": official,
            "article_no": article_no,
            "law_verified": law_verified,
            "article_verified": article_verified if article_no else None,
            "source": law_info.get("source", "offline"),
            "link": _viewer_link(official, article_no) or law_info.get("link"),
        })

    verified = bool(refs) and all(
        r["law_verified"] and (r["article_verified"] is not False) for r in refs
    )
    source = "api" if any(r["source"] == "api" for r in refs) else "offline"
    official_name = " / ".join(
        dict.fromkeys(r["official_name"] for r in refs if r["official_name"])
    )
    link = next((r["link"] for r in refs if r.get("link")), None)
    return {
        "verified": verified,
        "source": source,
        "official_name": official_name,
        "link": link,
        "refs": refs,
    }


def law_exists(law_name: str) -> dict:
    """하위 호환용: 단일 법령명 존재 확인."""
    return _search_law(law_name)


def is_korean_law(citation: str) -> bool:
    """한국 법령 인용인지 (OJK 등 해외 법령 제외)"""
    return bool(re.search(r"(법|시행령|감독규정)", citation)) and "POJK" not in citation


# ─────────────────────────────────────────────────────────────
# 조문 실측 조회 — 전문가가 인용을 입력할 때 '진짜 조문'을 보여준다.
#   존재/삭제/제목/본문/항 개수를 국가법령정보 API에서 가져옴 (클로드 미사용).
#   삭제된 조문(예: 보험업법 제95조의4)은 내용에 '삭제'가 들어오므로 즉시 감지.
# ─────────────────────────────────────────────────────────────
_ART_FULL_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?")


def fetch_article(citation: str) -> dict:
    """
    인용 문자열의 첫 조문을 국가법령정보에서 조회해 실제 조문을 반환.

    Returns
    -------
    {"ok": bool, "reachable": bool, "found": bool, "deleted": bool,
     "law_name", "official_name", "article_label", "title", "content",
     "n_hang": int, "hang_ref": int|None, "hang_ok": bool|None, "link": str|None,
     "message": str}
    """
    out = {"ok": False, "reachable": False, "found": False, "deleted": False,
           "law_name": "", "official_name": "", "article_label": "", "title": "",
           "content": "", "n_hang": 0, "hang_ref": None, "hang_ok": None,
           "link": None, "message": ""}
    if not is_korean_law(citation):
        out["message"] = "국내 법령이 아니어서 실측 조회 대상이 아닙니다(형식 검증만)."
        return out

    ref = _split_citation_refs(citation)[0]
    law_name = ref.get("law_name") or _base_law_name(citation)
    out["law_name"] = law_name
    m = _ART_FULL_RE.search(citation)
    if not m:
        out["message"] = "인용에서 '제○조'를 찾지 못했습니다."
        return out
    art_no, sub_no, hang_no = m.group(1), m.group(2), m.group(3)
    out["hang_ref"] = int(hang_no) if hang_no else None
    out["article_label"] = f"제{art_no}조" + (f"의{sub_no}" if sub_no else "") + (f" 제{hang_no}항" if hang_no else "")

    law_info = _search_law(law_name)
    if not law_info.get("verified") or not law_info.get("mst"):
        out["message"] = f"'{law_name}' 법령을 국가법령정보에서 찾지 못했습니다." if law_info.get("source") == "api" \
            else "국가법령정보 연결 실패(오프라인) — 실측 확인을 건너뜁니다."
        out["reachable"] = law_info.get("source") == "api"
        return out
    out["reachable"] = True
    out["official_name"] = law_info.get("official_name") or law_name
    out["link"] = _viewer_link(out["official_name"], art_no) or law_info.get("link")

    xml = _get(f"{_BASE}/lawService.do",
               {"OC": _OC, "target": "law", "type": "XML", "MST": law_info["mst"]})
    if not xml:
        out["message"] = "조문 본문 조회 실패(네트워크)."
        return out
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        out["message"] = "조문 본문 파싱 실패."
        return out

    for node in root.findall(".//조문단위"):
        if (node.findtext("조문여부") or "").strip() != "조문":
            continue
        if (node.findtext("조문번호") or "").strip() != str(art_no):
            continue
        node_sub = (node.findtext("조문가지번호") or "").strip()
        if (sub_no or "") != node_sub:     # 제95조의4 ↔ 가지번호 '4' 정확 매칭
            continue
        out["found"] = True
        content = (node.findtext("조문내용") or "").strip()
        title = (node.findtext("조문제목") or "").strip()
        hangs = node.findall("항")
        out["n_hang"] = len([h for h in hangs if (h.findtext("항내용") or h.findtext("항번호"))]) or len(hangs)
        out["title"] = title
        out["content"] = content
        # 삭제 감지 — 국가법령정보는 삭제 조문을 "제N조 삭제 <YYYY.M.D>"로 반환
        if "삭제" in content and len(content) < 60:
            out["deleted"] = True
            out["message"] = f"⚠️ 삭제된 조문입니다 — {content}"
        else:
            out["ok"] = True
            if out["hang_ref"] is not None:
                out["hang_ok"] = out["hang_ref"] <= max(out["n_hang"], 0) if out["n_hang"] else None
                if out["hang_ok"] is False:
                    out["message"] = f"조문은 실존하나 제{out['hang_ref']}항이 확인되지 않습니다(항 {out['n_hang']}개)."
                else:
                    out["message"] = "실측 확인됨 — 현행 유효 조문."
            else:
                out["message"] = "실측 확인됨 — 현행 유효 조문."
        return out

    out["message"] = f"{out['official_name']}에서 {out['article_label']}을(를) 찾지 못했습니다(존재하지 않거나 삭제)."
    return out


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    for name in ["금융소비자보호법 제22조 및 동법 시행령 제19조",
                 "자본시장법 제55조",
                 "존재하지않는법 제999조"]:
        r = law_exists(name)
        print(f"[{name}]\n  → {r}")
