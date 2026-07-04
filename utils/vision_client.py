"""
utils/vision_client.py
────────────────────────────────────────────────────────────────
Groq 비전 모델로 이미지 광고물의 텍스트를 인식 (Tesseract OCR 대체).

- 같은 Groq API 키 사용. 모델은 GROQ_VISION_MODEL(env)로 교체 가능
  (추후 로컬 소형 VLM 온프렘 교체에 대비해 provider를 코드에 박지 않음).
- 호출 실패 시 호출측(server)에서 Tesseract OCR로 폴백한다.
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).parent.parent / ".env")
logger = logging.getLogger(__name__)

VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
VISION_TIMEOUT_SEC = float(os.environ.get("VISION_TIMEOUT_SEC", "30"))

_PROMPT = (
    "이 금융 광고 이미지에 보이는 모든 텍스트를 위에서 아래, 왼쪽에서 오른쪽 읽기 순서로 "
    "그대로 추출하세요. 작은 글씨(하단 고지·주석·약관 안내 포함)도 빠짐없이 포함하세요. "
    "설명이나 해석은 하지 말고, 추출한 텍스트만 출력하세요."
)

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY 환경변수가 설정되지 않았습니다.")
        _client = Groq(api_key=api_key, timeout=VISION_TIMEOUT_SEC, max_retries=0)
    return _client


def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def vision_extract_text(data: bytes) -> str:
    """이미지 바이트 → 비전 모델이 읽은 텍스트(읽기순서). 실패 시 예외 발생.

    VISION_PROVIDER=anthropic(기본): Claude 비전으로 OCR (본선 교체분).
    VISION_PROVIDER=groq: 기존 Groq 비전 경로. 어느 쪽이든 실패 시 server가 Tesseract로 폴백.
    """
    if os.environ.get("VISION_PROVIDER", "anthropic").lower() == "anthropic":
        from utils.claude_client import vision_extract_text as _claude_vision
        return _claude_vision(data)

    b64 = base64.b64encode(data).decode("ascii")
    url = f"data:{_mime(data)};base64,{b64}"
    resp = _get_client().chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }],
        temperature=0.0,
        max_tokens=1024,
    )
    return (resp.choices[0].message.content or "").strip()
