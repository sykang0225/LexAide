"""
OCR post-processing for financial ad text.

The goal is conservative cleanup: fix repeated OCR artifacts that are common in
Korean financial ads without inventing missing legal meaning.
"""
from __future__ import annotations

import re


_SPACELESS_TERMS = [
    "신용점수",
    "공동인증서",
    "비대면",
    "한도조회",
    "상품문의",
    "대출금리",
    "대출기간",
    "상환방법",
    "중도상환해약금",
    "연체이자율",
    "약정이율",
    "개인신용평가",
    "개인신용평정",
    "신용등급",
    "대출금액",
    "상품설명서",
    "금융소비자",
    "금소법",
    "인지세",
    "원리금균등분할상환",
    "이자부과시기",
    "한도조회",
]

_COMMON_REPLACEMENTS = [
    (r"공\s*동\s*인\s*[종증]\s*서", "공동인증서"),
    (r"시\s*용\s*점수", "신용점수"),
    (r"N\s*I\s*C\s*E", "NICE"),
    (r"나이스", "NICE"),
    (r"S\s*[A4]\s*[YW]\s*제\s*19\s*조", "금소법 제19조"),
    (r"금\s*융\s*소\s*비\s*자\s*보\s*호\s*법", "금융소비자보호법"),
    (r"상\s*품\s*설\s*명\s*서", "상품설명서"),
    (r"약\s*관", "약관"),
    (r"악\s*관", "약관"),
    (r"비\s*대\s*면", "비대면"),
    (r"QRS\s*스\s*캔", "QR 스캔"),
    (r"약정이율\s*396", "약정이율 + 3%"),
]


def _collapse_term_spaces(text: str, term: str) -> str:
    pattern = r"\s*".join(map(re.escape, term))
    return re.sub(pattern, term, text)


def _normalize_rate_ranges(text: str) -> str:
    # "3 45%" / "3 . 45 %" -> "3.45%"
    text = re.sub(r"(\d{1,2})\s*[.·]?\s*(\d{2})\s*%", r"\1.\2%", text)
    # "연 3 .45 %" -> "연 3.45%"
    text = re.sub(r"연\s+(\d{1,2})\s*\.\s*(\d{2})\s*%", r"연 \1.\2%", text)
    # "~ 최고 연" OCR spacing cleanup
    text = re.sub(r"~\s*최\s*고\s*연", "~ 최고 연", text)
    text = re.sub(r"최\s*저\s*연", "최저 연", text)
    text = re.sub(r"최\s*고\s*연", "최고 연", text)
    return text


def _normalize_nice_score(text: str) -> str:
    text = re.sub(r"NICE\s*(\d{3,4})\s*(?:점|8)?\s*이상", lambda m: _nice_score(m.group(1)), text)
    text = re.sub(r"신용\s*점수\s*NICE\s*(\d{3,4})\s*(?:점|8)?\s*이상",
                  lambda m: f"신용점수 NICE {_digits_to_score(m.group(1))}점 이상", text)
    return text


def _digits_to_score(raw: str) -> str:
    # OCR often reads "600점" as "6008". Keep plausible Korean credit-score ranges.
    if len(raw) == 4 and raw.endswith("8") and 300 <= int(raw[:3]) <= 1000:
        return raw[:3]
    return raw


def _nice_score(raw: str) -> str:
    return f"NICE {_digits_to_score(raw)}점 이상"


def normalize_ocr_text(text: str) -> str:
    """Apply conservative OCR cleanup rules."""
    if not text:
        return ""

    out = text.replace("\u00a0", " ")
    out = re.sub(r"[ \t]+", " ", out)

    for pattern, repl in _COMMON_REPLACEMENTS:
        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    for term in _SPACELESS_TERMS:
        out = _collapse_term_spaces(out, term)

    out = re.sub(r"약정이율\s*396", "약정이율 + 3%", out)
    out = _normalize_rate_ranges(out)
    out = _normalize_nice_score(out)

    # Common Korean financial text spacing.
    out = re.sub(r"최\s*대\s*(\d+)\s*억\s*원", r"최대 \1억원", out)
    out = re.sub(r"최\s*장\s*(\d+)\s*년", r"최장 \1년", out)
    out = re.sub(r"(\d+)\s*개\s*월", r"\1개월", out)
    out = re.sub(r"(\d+)\s*천\s*만\s*원", r"\1천만원", out)
    out = re.sub(r"각\s*50\s*%\s*부담", "각 50% 부담", out)
    out = re.sub(r"평일\s*(\d{2})\s*:\s*(\d{2})\s*~\s*(\d{2})\s*:\s*(\d{2})",
                 r"평일 \1:\2 ~ \3:\4", out)

    return re.sub(r"[ \t]{2,}", " ", out).strip()
