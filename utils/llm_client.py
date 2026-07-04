"""
utils/llm_client.py
────────────────────────────────────────────────────────────────
Groq API 클라이언트 — Llama 3.3 70B

주요 기능
  - call_llm()       : 단일 프롬프트 호출 (tree_engine 연동용)
  - call_llm_json()  : JSON 응답 강제 파싱 (구조화 판정용)
  - test_connection() : API 키 유효성 확인

설계 원칙
  - temperature=0.0  : 준법 판단은 결정론적이어야 함
  - 재시도 로직      : 네트워크 오류 시 최대 2회 재시도
  - 비용 절감        : tree_engine에서 rule 노드 통과 시만 호출
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq, APIError, APIConnectionError, RateLimitError

# .env 로드 (프로젝트 루트 기준)
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 클라이언트 초기화
# ─────────────────────────────────────────────────────────────

_client: Groq | None = None


def _get_client() -> Groq:
    """싱글턴 Groq 클라이언트 반환"""
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError(
                "GROQ_API_KEY 환경변수가 설정되지 않았습니다. "
                ".env 파일을 확인하세요."
            )
        _client = Groq(api_key=api_key, timeout=LLM_TIMEOUT_SEC, max_retries=0)
        logger.info("[LLMClient] Groq 클라이언트 초기화 완료")
    return _client


DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
LLM_TIMEOUT_SEC = float(os.environ.get("LLM_TIMEOUT_SEC", "5"))

# ─────────────────────────────────────────────────────────────
# 핵심 호출 함수
# ─────────────────────────────────────────────────────────────

def call_llm(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 512,
    max_retries: int = 0,
) -> str:
    """
    Groq API 단일 호출 — 문자열 응답 반환.

    Parameters
    ----------
    prompt      : 사용자 메시지
    system      : 시스템 프롬프트 (역할 부여)
    model       : 사용할 모델명 (기본: llama-3.3-70b-versatile)
    temperature : 0.0 = 결정론적 (준법 판단 권장값)
    max_tokens  : 최대 출력 토큰 수
    max_retries : 네트워크 오류 시 재시도 횟수

    Returns
    -------
    str : LLM 응답 텍스트
    """
    # 성능 평가용 baseline — LLM_PROVIDER=anthropic이면 Claude로 위임.
    # 제품 기본값은 Groq(소형 모델)이므로 미설정 시 아래 Groq 경로 그대로.
    if os.environ.get("LLM_PROVIDER", "groq").lower() == "anthropic":
        from utils.claude_client import call_claude
        return call_claude(prompt, system=system, max_tokens=max_tokens)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(max_retries + 1):
        try:
            response = _get_client().chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            logger.debug(
                f"[LLMClient] 호출 완료 | "
                f"입력={response.usage.prompt_tokens}tok "
                f"출력={response.usage.completion_tokens}tok"
            )
            return content

        except RateLimitError:
            if attempt >= max_retries:
                raise
            wait = min(2 ** attempt, 3)
            logger.warning(f"[LLMClient] Rate limit — {wait}초 대기 후 재시도")
            time.sleep(wait)

        except APIConnectionError as e:
            if attempt < max_retries:
                logger.warning(f"[LLMClient] 연결 오류 (재시도 {attempt+1}/{max_retries}): {e}")
                time.sleep(1)
            else:
                raise

        except APIError as e:
            logger.error(f"[LLMClient] API 오류: {e}")
            raise

        except Exception as e:
            logger.error(f"[LLMClient] 호출 오류/timeout: {e}")
            raise

    raise RuntimeError("Groq API 호출 최대 재시도 초과")


def call_llm_json(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
) -> dict:
    """
    Groq API 호출 후 JSON 파싱까지 수행.

    tree_engine의 LLM 노드는 이 함수를 사용.
    응답에서 JSON 블록을 추출하고, 실패 시 폴백 dict 반환.

    Returns
    -------
    dict : {"triggered": bool, "reason": str, "confidence": float}
    """
    # JSON 응답 유도를 위해 시스템 프롬프트에 명시
    json_system = (system + "\n" if system else "") + (
        "반드시 JSON 형식으로만 응답하세요: "
        '{"triggered": true/false, "reason": "근거", "confidence": 0.0~1.0}'
    )

    raw = call_llm(
        prompt=prompt,
        system=json_system,
        model=model,
        temperature=temperature,
        max_tokens=512,
    )

    return _parse_json_response(raw)


def _parse_json_response(raw: str) -> dict:
    """LLM 응답에서 JSON 추출 (폴백 포함)"""
    # 1순위: 코드 블록 안 JSON
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass

    # 2순위: 첫 번째 {...} 블록
    json_match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    # 3순위: 텍스트 기반 폴백
    raw_lower = raw.lower()
    triggered = any(kw in raw_lower for kw in ["위반", "true", "yes", "해당", "있습니다"])
    return {
        "triggered": triggered,
        "reason": raw[:200].strip(),
        "confidence": 0.65 if triggered else 0.25,
    }


# ─────────────────────────────────────────────────────────────
# 연결 테스트
# ─────────────────────────────────────────────────────────────

def test_connection() -> bool:
    """
    API 키 유효성 및 모델 응답 확인.
    성공 시 True, 실패 시 False 반환.
    """
    try:
        result = call_llm(
            prompt="'연결 성공'이라고만 답하세요.",
            system="당신은 테스트 어시스턴트입니다.",
            max_tokens=20,
        )
        logger.info(f"[LLMClient] 연결 테스트 성공: {result.strip()}")
        return True
    except Exception as e:
        logger.error(f"[LLMClient] 연결 테스트 실패: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# 직접 실행 테스트
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    print("=" * 50)
    print("Groq API 연결 테스트")
    print("=" * 50)

    ok = test_connection()
    if not ok:
        print("❌ 연결 실패 — .env 파일의 GROQ_API_KEY를 확인하세요.")
        sys.exit(1)

    print("\n[JSON 응답 테스트]")
    result = call_llm_json(
        prompt=(
            '다음 광고 문구를 분석하세요.\n\n'
            '[광고 문구]\n"연 10% 수익을 보장하는 안전한 펀드"\n\n'
            '금융소비자보호법 위반(단정적 수익 보장 표현) 여부를 판단하세요.'
        ),
        system="당신은 금융 준법 심사 전문가입니다.",
    )
    print(f"triggered  : {result.get('triggered')}")
    print(f"confidence : {result.get('confidence')}")
    print(f"reason     : {result.get('reason')}")
    print("\n✅ 테스트 완료")
