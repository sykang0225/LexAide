"""
utils/embedder.py
────────────────────────────────────────────────────────────────
다국어 문장 임베딩 래퍼 (한국어 + 인도네시아어 동시 지원)

모델: paraphrase-multilingual-MiniLM-L12-v2
  - 50+ 언어 지원 (ko, id 포함)
  - 384차원, 경량(~470MB) — XLM-RoBERTa 대비 빠름
  - GTX 4050(CUDA) 자동 사용, 없으면 CPU 폴백

용도
  제재사례 텍스트 ↔ 입력 광고 문구의 의미적 유사도 계산
  (Agent 2 의 임베딩 단계 · "유사 제재사례" 탐지)
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import threading
from typing import Iterable

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_DIM = 384

_model = None
_lock = threading.Lock()


def _get_model():
    """SentenceTransformer 싱글턴 로드 (최초 1회, thread-safe)"""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
                logger.info(f"[embedder] 모델 로드 ({_MODEL_NAME}, device={device})")
                _model = SentenceTransformer(_MODEL_NAME, device=device)
    return _model


def embed(texts: str | Iterable[str], normalize: bool = True) -> np.ndarray:
    """
    텍스트(들)를 임베딩 벡터로 변환.

    Parameters
    ----------
    texts     : 단일 문자열 또는 문자열 리스트
    normalize : True면 L2 정규화 (코사인 유사도 = 내적)

    Returns
    -------
    np.ndarray  shape (N, 384), dtype float32
    """
    single = isinstance(texts, str)
    items = [texts] if single else list(texts)
    if not items:
        return np.zeros((0, _DIM), dtype="float32")

    model = _get_model()
    vecs = model.encode(
        items,
        normalize_embeddings=normalize,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype("float32")
    return vecs


def embed_dim() -> int:
    return _DIM


def model_name() -> str:
    return _MODEL_NAME


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)

    a = embed("원금을 보장하는 안전한 상품")
    b = embed(["원금 100% 보장 무위험 투자", "이 상품은 원금손실이 발생할 수 있습니다"])
    print("shape:", a.shape, b.shape)
    sim = (a @ b.T)[0]
    print(f"유사도(원금보장 위반): {sim[0]:.3f}  (높아야 정상)")
    print(f"유사도(정상 고지문)  : {sim[1]:.3f}  (낮아야 정상)")
