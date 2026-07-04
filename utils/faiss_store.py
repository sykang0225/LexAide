"""
utils/faiss_store.py
────────────────────────────────────────────────────────────────
제재사례 벡터 스토어 — 의미적 유사 사례 검색

백엔드: numpy 정밀 검색 (brute-force cosine)
  - MVP 규모(<100건)에서는 numpy 내적이 FAISS보다 빠르고 메모리 효율적
  - Windows의 FAISS+PyTorch OpenMP DLL 충돌(access violation) 회피
  - 향후 사례 수천 건 이상 확장 시 FAISS HNSW 인덱스로 교체 가능 (인터페이스 동일)

기능
  build_index()   : sanctions.json → 임베딩 → 벡터 행렬 저장(.npy)
  search(text, k) : 입력 문구와 가장 유사한 제재사례 k건 반환 (코사인 유사도)
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np

from utils.embedder import embed

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_SANCTIONS = _ROOT / "data" / "sanctions" / "sanctions.json"
_INDEX_DIR = _ROOT / "data" / "faiss_index"
_VEC_PATH = _INDEX_DIR / "sanctions_vectors.npy"
_META_PATH = _INDEX_DIR / "sanctions_meta.json"

_vectors: np.ndarray | None = None
_meta: list[dict] = []
_lock = threading.Lock()


# ── 인덱스 빌드 ────────────────────────────────────────────────
def build_index() -> int:
    """sanctions.json 로드 → 임베딩 → 벡터 행렬(.npy) 저장. 사례 수 반환."""
    with open(_SANCTIONS, encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases", [])
    if not cases:
        raise ValueError("sanctions.json 에 cases 없음")

    texts = [c["text"] for c in cases]
    vecs = embed(texts, normalize=True).astype("float32")  # (N, 384) 정규화

    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(_VEC_PATH, vecs)
    with open(_META_PATH, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)

    logger.info(f"[vstore] 인덱스 생성 완료 — {len(cases)}건 → {_VEC_PATH}")
    return len(cases)


# ── 인덱스 로드 ────────────────────────────────────────────────
def _ensure_loaded():
    global _vectors, _meta
    if _vectors is not None:
        return
    with _lock:
        if _vectors is not None:
            return
        if not _VEC_PATH.exists():
            logger.info("[vstore] 인덱스 없음 → 빌드 시작")
            build_index()
        _vectors = np.load(_VEC_PATH)
        with open(_META_PATH, encoding="utf-8") as f:
            _meta = json.load(f)
        logger.info(f"[vstore] 인덱스 로드 — {len(_meta)}건")


# ── 검색 ───────────────────────────────────────────────────────
def search(text: str, k: int = 3, lang: str | None = None,
           min_score: float = 0.0) -> list[dict]:
    """
    입력 문구와 의미적으로 유사한 제재사례 k건 반환 (코사인 유사도 내림차순).

    Returns
    -------
    list[dict] — 각 항목: {score, id, lang, violation_type, text, law, citation, sanction, year}
    """
    if not text or not text.strip():
        return []
    _ensure_loaded()
    if _vectors is None or len(_meta) == 0:
        return []

    qv = embed(text, normalize=True)[0]            # (384,) 정규화
    sims = _vectors @ qv                            # (N,) 코사인 유사도
    order = np.argsort(-sims)                       # 내림차순 인덱스

    out = []
    for idx in order:
        case = _meta[int(idx)]
        score = float(sims[int(idx)])
        if lang and case.get("lang") != lang:
            continue
        if score < min_score:
            continue
        out.append({**case, "score": round(score, 4)})
        if len(out) >= k:
            break
    return out


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)

    n = build_index()
    print(f"\n인덱스 빌드: {n}건\n" + "=" * 55)
    TESTS = [
        ("연 9% 수익을 보장하는 안전한 펀드입니다", "ko"),
        ("Investasi aman dengan keuntungan dijamin", "id"),
        ("이 상품은 원금손실이 발생할 수 있습니다", "ko"),
    ]
    for text, lang in TESTS:
        print(f"\n[질의] ({lang}) {text}")
        for r in search(text, k=2, lang=lang):
            print(f"  {r['score']:.3f} | {r['id']} {r['violation_type']} | {r['text'][:45]}")
