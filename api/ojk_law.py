"""
Local OJK citation verifier.

OJK does not currently have a law.go.kr-like article API in this project.
For the MVP, citations are verified against a local article map built from the
official OJK POJK No. 22 Tahun 2023 PDF.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_DATA_PATH = Path(__file__).parent.parent / "data" / "laws" / "ojk_pojk_22_2023_articles.json"
_PASAL_RE = re.compile(r"Pasal\s*(\d+)", re.IGNORECASE)

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _cache


def verify_ojk_citation(citation: str) -> dict:
    data = _load()
    article_nos = _PASAL_RE.findall(citation or "")
    refs = []
    for no in article_nos:
        article = data.get("articles", {}).get(str(no))
        # 조문 시작 페이지(공식 PDF 실측값)가 있으면 #page=N 으로 바로 이동
        link = data.get("source_url", "")
        if article and article.get("page"):
            link = f"{link}#page={article['page']}"
        refs.append({
            "law_name": data.get("law_id", "POJK"),
            "official_name": data.get("official_name", ""),
            "article_no": str(no),
            "law_verified": True,
            "article_verified": bool(article),
            "source": "local_ojk",
            "link": link,
            "title": article.get("title", "") if article else "",
            "summary_ko": article.get("summary_ko", "") if article else "",
            "recommended_use": article.get("recommended_use", "") if article else "",
        })

    verified = bool(refs) and all(r["article_verified"] for r in refs)
    return {
        "verified": verified,
        "source": "local_ojk",
        "official_name": data.get("official_name", "POJK"),
        "link": data.get("source_url", ""),
        "refs": refs,
    }
