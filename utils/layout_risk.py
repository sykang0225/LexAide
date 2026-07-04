# -*- coding: utf-8 -*-
"""
Layout Risk Analyzer — 부작위/현저성 위반 탐지 (작위는 Rule/LLM, 부작위는 여기서)

텍스트 '내용'이 아니라 텍스트의 '시각적 현저성'(글자 크기·위치·색상·면적)을 분석해
유리한 조건만 크게/위에 강조하고 불리한 조건·필수 고지는 작게/하단/흐리게 표시한
부작위형 오인 위험을 WARNING으로 탐지한다.

근거: 금융감독원 2025.2.3 대출상품 광고 점검 — "최저금리만 비대칭적으로 노출".
원칙: 결과는 VIOLATION 단정이 아니라 WARNING. 최종 판단은 준법관리자(Human-in-the-loop).
      OCR 기반 크기는 보조 신호(낮은 신뢰도), PDF 텍스트레이어 기반이 정확.
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── 키워드 그룹 (금감원 광고 점검 유형 기반) ──
FAVORABLE_TERMS = [
    "최저금리", "최저", "최대한도", "최대", "당일", "즉시", "간편",
    "누구나", "무조건", "승인", "No.1", "1위", "최고 수익", "고수익",
]
ADVERSE_TERMS = [
    "최고금리", "최고", "심사", "개인신용평가", "차등", "조건", "유의",
    "연체", "수수료", "변동", "제한", "불가", "원금손실", "손실", "위험",
]

# ── 임계값 (준법 정책에 따라 env로 튜닝 가능) ──
SIZE_RATIO_TH = float(os.environ.get("LAYOUT_SIZE_RATIO", "2.5"))
AREA_RATIO_TH = float(os.environ.get("LAYOUT_AREA_RATIO", "3.0"))
TOP_FRAC = float(os.environ.get("LAYOUT_TOP_FRAC", "0.5"))      # 상단 50%
BOTTOM_FRAC = float(os.environ.get("LAYOUT_BOTTOM_FRAC", "0.8"))  # 하단 20% (y > 0.8H)
DISCLOSURE_REL = float(os.environ.get("LAYOUT_DISCLOSURE_REL", "0.7"))  # 고지가 본문의 70% 미만이면 주의

# 위험·필수 고지 문구 — 이 문구가 본문 대비 작게 표시되면 부작위(현저성) 위험
DISCLOSURE_TERMS = [
    "원금손실", "원금 손실", "손실이 발생", "투자위험", "투자 위험",
    "원금이 보장되지 않", "보장되지 않", "과거 수익률", "과거의 운용실적",
    "운용실적", "예금자보호", "비보장", "세금", "수수료",
]

_MSG = ("텍스트상 필수 정보는 존재하지만, 유리한 조건이 상대적으로 크게/위에 표시되어 "
        "시각적 현저성 검토가 필요합니다.")
_REC = ("유리한 조건과 불리한 조건(최고금리·심사기준·위험·수수료 등)을 "
        "동등한 크기·위치·명도로 표시했는지 준법관리자가 확인하세요.")
_MSG_MINSIZE = ("필수 고지(위험·비용 등)가 기준 크기보다 작게 표시되어 "
                "현저성(가독성) 검토가 필요합니다.")
_REC_MINSIZE = ("필수 고지는 혜택 표현과 위치·크기·굵기·색상에서 균형 있게 표시했는지 확인하세요. "
                "(근거: 금융소비자보호법 제22조제2항 + 금융광고규제 가이드라인; "
                "예금성 상품은 '예금성 상품 광고 준수사항'(2023.9.14) — 최고금리·기본금리 균형 표기)")
_CITE_MINSIZE = ("금융소비자보호법 제22조제2항 · 금융광고규제 가이드라인 / "
                 "예금성 상품 광고 준수사항(2023.9.14) — 위치·크기·굵기·색상 균형 표기")
_INTENT_MINSIZE = ("금융감독원이 '최고금리만 비대칭적으로 노출'하는 행위를 "
                   "소비자 오인 유발로 직접 적시한 유형입니다.")


def _has(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if t in text]


_BOLD_RE = None  # lazy compile


def _is_bold(fontname) -> bool:
    """폰트명으로 굵은 글꼴 여부 판별 (예: 'MalgunGothic-Bold', 'NotoSansKR-Black')."""
    global _BOLD_RE
    if not fontname:
        return False
    if _BOLD_RE is None:
        import re
        _BOLD_RE = re.compile(r"bold|black|heavy|semibold|demi|extrabold", re.IGNORECASE)
    return bool(_BOLD_RE.search(str(fontname)))


def _lum(color) -> float | None:
    """non_stroking_color → 밝기(0=검정, 1=흰색). 회색/RGB/CMYK 방어적 처리."""
    if color is None:
        return None
    try:
        if isinstance(color, (int, float)):
            vals = [float(color)]
        else:
            vals = [float(v) for v in color]
    except (TypeError, ValueError):
        return None
    if not vals:
        return None
    if max(vals) > 1.0:                       # 0~255 스케일 방어
        vals = [v / 255.0 for v in vals]
    if len(vals) == 1:
        return vals[0]
    if len(vals) == 3:
        r, g, b = vals
        return 0.299 * r + 0.587 * g + 0.114 * b
    if len(vals) == 4:                        # CMYK
        c, m, y, k = vals
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        return 0.299 * r + 0.587 * g + 0.114 * b
    return None


# 고지 문구 밝기가 이 값 이상이면 저대비(흐리게)로 판정 — 검정 0.0, 회색 #999≈0.6
LOW_CONTRAST_LUM = float(os.environ.get("LAYOUT_LOWCONTRAST_LUM", "0.45"))


def _spans_from_pdf(data: bytes) -> list[dict]:
    """pdfplumber로 단어별 텍스트·크기·위치·굵기·색상 추출. (fitz dict 모드는 일부 PDF에서
    글자가 잘려 추출되므로, 본문 추출과 동일한 pdfplumber 경로로 통일한다.)"""
    import io
    import pdfplumber

    spans: list[dict] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pno, page in enumerate(pdf.pages):
            pw, ph = (page.width or 1), (page.height or 1)
            words = page.extract_words(
                extra_attrs=["size", "fontname", "non_stroking_color"]) or []
            for w in words:
                txt = (w.get("text") or "").strip()
                if not txt:
                    continue
                x0, x1, top, bottom = w["x0"], w["x1"], w["top"], w["bottom"]
                spans.append({
                    "text": txt, "size": float(w.get("size") or 0.0),
                    "bold": _is_bold(w.get("fontname")),
                    "lum": _lum(w.get("non_stroking_color")),
                    "x": x0, "w": x1 - x0, "h": bottom - top,
                    "area": (x1 - x0) * (bottom - top),
                    "yc": (top + bottom) / 2, "page": pno, "ph": ph, "pw": pw,
                })
    return spans


def _spans_from_ocr(boxes: list[dict]) -> list[dict]:
    """OCR 박스 → 크기 proxy(글자 높이). 보조 신호."""
    spans: list[dict] = []
    if not boxes:
        return spans
    by_page = defaultdict(list)
    for b in boxes:
        by_page[b.get("page", 0)].append(b)
    for pno, bxs in by_page.items():
        ph = max((b["y"] + b["h"] for b in bxs), default=1) or 1
        pw = max((b["x"] + b["w"] for b in bxs), default=1) or 1
        for b in bxs:
            spans.append({
                "text": (b.get("text") or "").strip(),
                "size": float(b.get("h", 0)),  # 글자 높이 = 크기 proxy
                "w": b["w"], "h": b["h"], "area": b["w"] * b["h"],
                "yc": b["y"] + b["h"] / 2, "page": pno, "ph": ph, "pw": pw,
            })
    return spans


def _line_text(sps: list[dict], target: dict, max_len: int = 120) -> str:
    """target과 같은 줄(페이지·y 근접)의 단어들을 x 순서로 이어 전체 줄 텍스트를 복원.
    (pdfplumber는 단어 단위로 쪼개므로, 표시용으로 줄 전체를 다시 합친다.)"""
    tol = max(target.get("h", 0) * 0.6, 2.0)
    same = [s for s in sps
            if s["page"] == target["page"] and abs(s["yc"] - target["yc"]) <= tol]
    same.sort(key=lambda s: s.get("x", 0.0))
    return " ".join(s["text"] for s in same)[:max_len]


def _page_dominant_size(sps: list[dict]) -> float:
    """페이지에서 쓰인 '고유 글자 크기'의 중앙값 — 상대 현저성 비교 기준.
    단어 수에 휘둘리지 않도록 인스턴스가 아닌 고유 크기 집합의 중앙값을 쓴다."""
    sizes = sorted({round(s["size"], 1) for s in sps if (s.get("size") or 0) > 0})
    return sizes[len(sizes) // 2] if sizes else 0.0


def _check_min_size(sps: list[dict], pno: int, source: str) -> list[dict]:
    """위험·필수 고지가 본문 대비 현저히 작게 표시됐는지 검사(상대 균형). 텍스트레이어 전용.
    절대 pt(9pt 등)는 일반 상품에 명문 근거가 없어 쓰지 않고, 본문 고유크기 대비 비율로 판단한다.
    근거: 금소법 제22조제2항 + 금융광고규제 가이드라인(C01) / 예금성 상품 준수사항(C02)."""
    out: list[dict] = []
    seen: set[str] = set()
    dominant = _page_dominant_size(sps)
    if dominant <= 0:
        return out
    # 페이지에서 가장 강조된(최대 크기) 문구 — 비대칭 대조용
    top = max(sps, key=lambda x: x.get("size", 0.0), default=None)
    benefit_text = _line_text(sps, top, 60) if top else ""
    benefit_pt = round(top.get("size", 0.0), 1) if top else 0.0
    for s in sps:
        size = s.get("size") or 0.0
        if size <= 0 or size >= DISCLOSURE_REL * dominant:   # 본문 대비 충분히 큼 → 정상
            continue
        if not _has(s["text"], DISCLOSURE_TERMS):
            continue
        line = _line_text(sps, s)                            # 단어가 아니라 줄 전체로 복원
        if line in seen:
            continue
        seen.add(line)
        ph = s.get("ph") or 1.0
        at_bottom = s.get("yc", 0.0) > BOTTOM_FRAC * ph      # 하단 배치 여부(위치 축)
        # 굵기 축 — 혜택 문구는 굵은 글꼴인데 고지 문구는 아닐 때(강조 비대칭)
        benefit_bold = bool(top and top.get("bold"))
        axis_bold = benefit_bold and not bool(s.get("bold"))
        # 색상 축 — 고지 문구가 밝은 회색 등 저대비(흐리게)로 표시될 때
        lum = s.get("lum")
        axis_color = lum is not None and lum >= LOW_CONTRAST_LUM
        out.append({
            "risk_type": "min_size",
            "kind": "min_size",
            "disclosure_text": line,
            "measured_pt": round(size, 1),
            "dominant_pt": round(dominant, 1),
            "ratio_pct": round(size / dominant * 100),       # 본문 대비 %
            "benefit_text": benefit_text,                    # 가장 강조된 문구(대조용)
            "benefit_pt": benefit_pt,
            "axis_size": True,                               # 크기 축(항상 발화)
            "axis_position": bool(at_bottom),                # 위치 축(하단 배치 시)
            "axis_bold": axis_bold,                          # 굵기 축(혜택만 굵게)
            "axis_color": axis_color,                        # 색상 축(고지가 저대비)
            "benefit_bold": benefit_bold,
            "disclosure_lum": round(lum, 2) if lum is not None else None,
            "position_reason": f"위험·필수 고지가 본문({dominant:.0f}pt) 대비 작게 표시 — {size:.1f}pt",
            "message": _MSG_MINSIZE,
            "recommendation": _REC_MINSIZE,
            "citation": _CITE_MINSIZE,
            "intent": _INTENT_MINSIZE,
            "page": pno + 1,
            "source": source,
            "confidence": 0.6,
        })
    return out


def _analyze(spans: list[dict], source: str) -> list[dict]:
    warnings: list[dict] = []
    by_page = defaultdict(list)
    for s in spans:
        by_page[s["page"]].append(s)

    for pno, sps in by_page.items():
        # (1) 위험·필수 고지 최소 크기 미달 — 실측 pt가 있는 텍스트레이어만, 독립 검사
        if source == "pdf_text":
            warnings.extend(_check_min_size(sps, pno, source))

        # (2) 유리/불리 비대칭(현저성) — fav·adv 쌍이 있을 때만
        fav_spans = [s for s in sps if _has(s["text"], FAVORABLE_TERMS) and not _has(s["text"], ADVERSE_TERMS)]
        adv_spans = [s for s in sps if _has(s["text"], ADVERSE_TERMS)]
        if not fav_spans or not adv_spans:
            continue

        fav = max(fav_spans, key=lambda s: s["size"])          # 가장 크게 강조된 유리 문구
        adv = min(adv_spans, key=lambda s: s["size"] or 1e9)   # 가장 작게 표시된 불리/조건 문구
        ph = fav["ph"] or 1

        size_ratio = (fav["size"] / adv["size"]) if adv["size"] else 0.0
        area_ratio = (fav["area"] / adv["area"]) if adv["area"] else 0.0

        reasons: list[str] = []
        rtypes: list[str] = []
        if size_ratio >= SIZE_RATIO_TH:
            reasons.append(f"유리 문구 글자 크기가 불리/조건 문구의 {size_ratio:.1f}배")
            rtypes.append("size")
        if area_ratio >= AREA_RATIO_TH:
            reasons.append(f"유리 문구 표시 면적이 {area_ratio:.1f}배")
            rtypes.append("area")
        if fav["yc"] < TOP_FRAC * ph and adv["yc"] > BOTTOM_FRAC * ph:
            reasons.append("유리 문구는 상단, 불리/조건 문구는 하단에 배치")
            rtypes.append("position")
        adv_lum = adv.get("lum")
        if source == "pdf_text" and adv_lum is not None and adv_lum >= LOW_CONTRAST_LUM:
            reasons.append("불리/조건 문구가 회색 계열(저대비)로 약하게 표시")
            rtypes.append("color")

        if reasons:
            warnings.append({
                "risk_type": "+".join(rtypes),
                "favorable_text": _line_text(sps, fav, 70),
                "adverse_text": _line_text(sps, adv, 70),
                "size_ratio": round(size_ratio, 2),
                "area_ratio": round(area_ratio, 2),
                "position_reason": " · ".join(reasons),
                "message": _MSG,
                "recommendation": _REC,
                "page": pno + 1,
                "source": source,
                "confidence": 0.6 if source == "pdf_text" else 0.45,  # OCR 보조는 낮게
            })
    return warnings


def analyze_pdf_layout(data: bytes) -> list[dict]:
    """PDF 텍스트레이어(PyMuPDF) 기반 현저성 분석. 가장 정확."""
    try:
        spans = _spans_from_pdf(data)
    except Exception as exc:
        logger.warning("[layout_risk] PDF 레이아웃 분석 실패: %s", exc)
        return []
    return _analyze(spans, "pdf_text")


def analyze_ocr_layout(boxes: list[dict]) -> list[dict]:
    """OCR 박스 기반 현저성 분석. 보조 신호(크기 proxy, 색상 불가)."""
    try:
        spans = _spans_from_ocr(boxes or [])
    except Exception as exc:
        logger.warning("[layout_risk] OCR 레이아웃 분석 실패: %s", exc)
        return []
    return _analyze(spans, "ocr")
