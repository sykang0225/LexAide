"""
utils/claude_client.py
────────────────────────────────────────────────────────────────
Anthropic Claude 클라이언트 — 본선 한정 용도.

용도 (제품 런타임 아님)
  - OCR/비전: 재무광고의 작은 고지문까지 정확히 읽기 (vision_client 위임)
  - 성능 평가: 소형 로컬/Groq 모델의 baseline 비교군 (evaluate_compare)

설계 원칙
  - 판정 본체는 여전히 Groq Llama(소형). Claude는 위 두 경로에서만 사용 —
    provider를 코드에 박지 않고 env 토글로 전환.
  - Opus 4.8은 temperature/top_p/budget_tokens를 거부(400)하므로 전송하지 않음.
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
VISION_MODEL = os.environ.get("ANTHROPIC_VISION_MODEL", "claude-opus-4-8")

_client = None


def _get_client():
    """싱글턴 Anthropic 클라이언트 반환"""
    global _client
    if _client is None:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다. .env를 확인하세요."
            )
        _client = anthropic.Anthropic(api_key=api_key)
        logger.info("[ClaudeClient] Anthropic 클라이언트 초기화 완료")
    return _client


def call_claude(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
) -> str:
    """
    단일 프롬프트 호출 — 문자열 응답 반환.
    (temperature 미전송 — Opus 4.8은 sampling 파라미터를 거부한다)
    """
    resp = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or None,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


_VISION_PROMPT = (
    "이 금융 광고 이미지에 보이는 모든 텍스트를 위에서 아래, 왼쪽에서 오른쪽 읽기 순서로 "
    "그대로 추출하세요. 작은 글씨(하단 고지·주석·약관 안내 포함)도 빠짐없이 포함하세요. "
    "설명이나 해석은 하지 말고, 추출한 텍스트만 출력하세요."
)


def vision_extract_text(data: bytes, model: str = VISION_MODEL) -> str:
    """이미지 바이트 → Claude 비전이 읽은 텍스트(읽기순서). 실패 시 예외 발생."""
    b64 = base64.b64encode(data).decode("ascii")
    resp = _get_client().messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": _mime(data), "data": b64}},
                {"type": "text", "text": _VISION_PROMPT},
            ],
        }],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()
