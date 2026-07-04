"""
api/server.py — LexAide FastAPI 서버

엔드포인트:
  GET  /            → index.html
  POST /api/detect  → 한국어/인니어 단일 심의
  POST /api/cross   → 한·인니 교차 심의
  POST /api/classify→ 언어 감지

실행:
  uvicorn api.server:app --port 8000
"""
from __future__ import annotations

import os
# ── OpenMP/torch DLL 충돌 방지 (반드시 torch import 전에 설정) ──
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

import asyncio
import json as _json

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.agent1_classifier  import classify
from agents.agent2_detector    import detect
from agents.agent3_consistency import check_consistency

app = FastAPI(title="LexAide")

# 정적 파일 마운트
_STATIC = _ROOT / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.on_event("startup")
def _warmup():
    """서버 시작 시 메인 스레드에서 임베딩 모델·벡터 인덱스 미리 로드.
    (워커 스레드에서 최초 로드 시 PyTorch OpenMP 세그폴트 방지)"""
    if os.environ.get("PRELOAD_EMBEDDING", "0") != "1":
        print("[startup] 임베딩 pre-warm 생략 (빠른 웹앱 시작 모드)", flush=True)
        return
    try:
        from utils.faiss_store import search
        search("워밍업", k=1)  # 모델+인덱스 로드 트리거
        print("[startup] 임베딩 모델·벡터 인덱스 pre-warm 완료", flush=True)
    except Exception as e:
        print(f"[startup] 임베딩 pre-warm 실패(임베딩 비활성으로 동작): {e}", flush=True)


# ─── 요청 모델 ───────────────────────────────
class DetectReq(BaseModel):
    text: str
    language: str = "ko"
    enable_llm: bool = True
    enable_embedding: bool = False  # sentence-transformers 환경 미비 시 False 유지


class CrossReq(BaseModel):
    ko_text: str
    id_text: str
    enable_llm: bool = True
    enable_embedding: bool = False


class ClassifyReq(BaseModel):
    text: str


# ─── 루트 → index.html ────────────────────────
@app.get("/")
async def index():
    # no-cache: 데모 중 UI 변경이 새로고침에 바로 반영되도록 (HTML 캐시 방지)
    return FileResponse(str(_STATIC / "index.html"),
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# ─── 언어 감지 ────────────────────────────────
@app.post("/api/classify")
async def api_classify(req: ClassifyReq):
    r = classify(req.text)
    return r.to_dict()


# ─── 단일 심의 (+ Agent 4 인용 검증) ──────────
@app.post("/api/detect")
def api_detect(req: DetectReq):
    r = detect(
        req.text,
        language=req.language,
        enable_llm=req.enable_llm,
        enable_embedding=req.enable_embedding,
    )
    out = r.to_dict()
    try:
        from agents.agent4_verifier import verify
        out["verification"] = verify(r).to_dict()
    except Exception as e:
        out["verification"] = {"summary": f"검증 생략: {e}", "checks": []}
    return out


# ─── 교차 심의 SSE 스트림 — Agent 1~4 실시간 진행 ─
@app.post("/api/cross/stream")
async def api_cross_stream(req: CrossReq):
    """교차 심의 SSE: {'step': N} → {'done': True, 'result': {...}}"""
    async def generate():
        try:
            # Agent 1: 언어 감지
            yield f"data: {_json.dumps({'step': 1})}\n\n"
            await asyncio.to_thread(classify, req.ko_text)
            await asyncio.to_thread(classify, req.id_text)

            # Agent 2 + 3: 규칙 탐지 & 교차검증 (check_consistency 내부)
            yield f"data: {_json.dumps({'step': 2})}\n\n"
            cons = await asyncio.to_thread(
                check_consistency, req.ko_text, req.id_text, req.enable_llm
            )
            yield f"data: {_json.dumps({'step': 3})}\n\n"
            await asyncio.sleep(0.35)   # Agent 3 화면 표시용 최소 pause

            # Agent 4: 인용 검증
            yield f"data: {_json.dumps({'step': 4})}\n\n"
            out = cons.to_dict()
            try:
                from agents.agent4_verifier import verify
                if cons.ko_result and out.get("ko_result"):
                    v = await asyncio.to_thread(verify, cons.ko_result)
                    out["ko_result"]["verification"] = v.to_dict()
                if cons.id_result and out.get("id_result"):
                    v = await asyncio.to_thread(verify, cons.id_result)
                    out["id_result"]["verification"] = v.to_dict()
            except Exception:
                pass

            yield f"data: {_json.dumps({'done': True, 'result': out})}\n\n"

        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── 교차 심의 (+ Agent 4 인용 검증) ──────────
@app.post("/api/cross")
def api_cross(req: CrossReq):
    cons = check_consistency(req.ko_text, req.id_text, enable_llm=req.enable_llm)
    out = cons.to_dict()
    try:
        from agents.agent4_verifier import verify
        if cons.ko_result and out.get("ko_result"):
            out["ko_result"]["verification"] = verify(cons.ko_result).to_dict()
        if cons.id_result and out.get("id_result"):
            out["id_result"]["verification"] = verify(cons.id_result).to_dict()
    except Exception as e:
        pass
    return out


# ─── 이미지 업로드 → OCR 좌표 + 심의 + 위반 위치 하이라이트 ──
@app.post("/api/detect_image")
async def api_detect_image(file: UploadFile = File(...),
                           language: str = Form("ko"),
                           enable_llm: bool = Form(True)):
    data = await file.read()
    text, boxes, source = "", [], "tesseract"
    # 1) Groq 비전으로 텍스트 인식 (env 토글, 실패 시 Tesseract 폴백)
    if os.environ.get("USE_VISION_OCR", "1") == "1":
        try:
            from utils.vision_client import vision_extract_text
            text = vision_extract_text(data)
            source = "groq_vision"
        except Exception as e:
            print(f"[detect_image] 비전 인식 실패 → Tesseract 폴백: {e}", flush=True)
    # 2) 폴백/기본: Tesseract OCR (+ 박스 → 현저성 보조신호)
    if not text.strip():
        try:
            from utils.image_annotate import ocr_with_boxes
            text, boxes = ocr_with_boxes(data)
            source = "tesseract"
        except Exception as e:
            return {"error": f"이미지 텍스트 인식 실패: {e}", "text": ""}

    if not text.strip():
        return {"error": "이미지에서 글자를 인식하지 못했습니다.", "text": ""}

    ocr_quality = None
    if boxes:  # Tesseract 경로만 OCR 품질 평가 (비전 경로는 박스 없음)
        try:
            from utils.file_extract import assess_ocr_quality
            ocr_quality = assess_ocr_quality(data, text, boxes)
        except Exception:
            ocr_quality = None

    r = detect(text, language=language, enable_llm=enable_llm)
    out = r.to_dict()
    out["text"] = text
    out["ocr_quality"] = ocr_quality
    out["text_source"] = source
    try:
        from agents.agent4_verifier import verify
        out["verification"] = verify(r).to_dict()
    except Exception:
        out["verification"] = {"summary": "", "checks": []}
    # 부작위/현저성 위험 (Tesseract 박스 있을 때만 — 비전 경로는 좌표 없음)
    try:
        from utils.layout_risk import analyze_ocr_layout
        out["layout_warnings"] = analyze_ocr_layout(boxes) if boxes else []
    except Exception:
        out["layout_warnings"] = []
    return out


# ─── PDF 텍스트레이어 → 심의 + 위반 위치 하이라이트 ──
@app.post("/api/detect_pdf")
async def api_detect_pdf(file: UploadFile = File(...),
                         language: str = Form("ko"),
                         enable_llm: bool = Form(True)):
    """텍스트레이어 PDF: 추출 + 심의 (부작위·현저성은 /api/extract의 layout_warnings로 제공)"""
    data = await file.read()
    from utils.file_extract import extract_text
    res = extract_text(data, file.filename or "upload.pdf")
    text = res.text
    if not text.strip():
        return {"error": "PDF에서 텍스트를 추출하지 못했습니다.", "text": ""}
    r = detect(text, language=language, enable_llm=enable_llm)
    out = r.to_dict()
    out["text"] = text
    out["source_type"] = res.source_type
    out["ocr_used"] = False
    try:
        from agents.agent4_verifier import verify
        out["verification"] = verify(r).to_dict()
    except Exception:
        out["verification"] = {"summary": "검증 생략", "checks": []}
    return out


# ─── 파일 업로드 → 텍스트 추출 (광고물 인식) ──────
@app.post("/api/extract")
async def api_extract(file: UploadFile = File(...)):
    from utils.file_extract import extract_text
    data = await file.read()
    max_mb = int(os.environ.get("MAX_UPLOAD_MB", "50"))  # 고해상도 광고물 대응 (env로 조정)
    if len(data) > max_mb * 1024 * 1024:
        return {"text": "", "source_type": "error", "ocr_used": False,
                "note": f"파일이 너무 큽니다 (최대 {max_mb}MB)."}
    fname = (file.filename or "upload").lower()
    is_image = fname.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
    # 이미지 업로드: Groq 비전 우선 인식 (실패 시 Tesseract 폴백). PDF/문서는 기존 경로.
    if is_image and os.environ.get("USE_VISION_OCR", "1") == "1":
        try:
            from utils.vision_client import vision_extract_text
            vtext = vision_extract_text(data)
            if vtext.strip():
                out = {"text": vtext, "source_type": "image", "ocr_used": True,
                       "text_source": "groq_vision"}
                try:
                    out["detected_lang"] = classify(vtext).language
                except Exception:
                    out["detected_lang"] = "unknown"
                return out
        except Exception as e:
            print(f"[extract] 비전 인식 실패 → Tesseract 폴백: {e}", flush=True)
    res = extract_text(data, file.filename or "upload")
    out = res.to_dict()
    # 언어 자동 감지 (텍스트가 있으면)
    if out["text"]:
        try:
            out["detected_lang"] = classify(out["text"]).language
        except Exception:
            out["detected_lang"] = "unknown"
    # 부작위/현저성 위험 (PDF 텍스트레이어 기반)
    if fname.endswith(".pdf"):
        try:
            from utils.layout_risk import analyze_pdf_layout
            out["layout_warnings"] = analyze_pdf_layout(data)
        except Exception:
            out["layout_warnings"] = []
    return out


# ─── 심의 이력·승인 로그 (SQLite) ──────────────
@app.post("/api/decision")
def api_decision(req: dict):
    """준법관리자 승인/수정요청/반려 결정을 저장."""
    from api.history import add_review
    return {"ok": True, "id": add_review(req)}


@app.get("/api/history")
def api_history(limit: int = 50):
    """최근 심의 이력 조회."""
    from api.history import list_reviews
    return {"items": list_reviews(limit)}


# ─── 규칙 트리 조회 (Rule Editor — 읽기) ────────
@app.get("/api/trees")
def api_trees():
    """편집 가능한 규칙 트리 목록(법령·규칙 수)."""
    from core.rule_store import list_trees
    return {"trees": list_trees()}


@app.get("/api/tree")
def api_tree(file: str):
    """트리 1개의 구조화 뷰(규칙·노드·on_match). 결과 카드/트리뷰용."""
    from fastapi import HTTPException
    from core.rule_store import read_tree, RuleStoreError
    try:
        return read_tree(file)
    except RuleStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── 규칙 피드백 (Rule Editor — 쓰기) ───────────
class RuleAdjustReq(BaseModel):
    tree_file: str
    node_id: str
    rule_id: str = ""
    result: str | None = None        # 낮춤/올림: 목표 레벨
    confidence: float | None = None  # 또는 confidence 조정
    reason: str = ""
    reviewer: str = "준법관리자"
    confirm_jump: bool = False        # 2단계 점프(VIOLATION↔PASS) 재확인


class RuleAddReq(BaseModel):
    tree_file: str
    rule_id: str
    node_id: str
    pattern: str
    reason: str
    result: str = "WARNING"
    confidence: float = 0.85
    citation: str = ""
    action: str = ""
    negate: bool = False
    reviewer: str = "준법관리자"


@app.post("/api/rule/adjust")
def api_rule_adjust(req: RuleAdjustReq):
    """과탐 교정(낮춤)·미탐 보강(올림): 판정 낸 규칙의 레벨/confidence 조정."""
    from fastapi import HTTPException
    from core.rule_store import adjust_node, RuleStoreError, ValidationError, JumpConfirmRequired
    try:
        return adjust_node(
            req.tree_file, req.rule_id, req.node_id,
            result=req.result, confidence=req.confidence,
            actor=req.reviewer, change_reason=req.reason, confirm_jump=req.confirm_jump,
        )
    except JumpConfirmRequired as e:
        raise HTTPException(status_code=409, detail={
            "needs_confirm": True, "from": e.frm, "to": e.to, "message": str(e)})
    except (ValidationError, RuleStoreError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rule/add")
def api_rule_add(req: RuleAddReq):
    """미탐 보강: 기존 규칙 블록에 새 키워드/패턴 노드 추가(레벨·사유·인용 포함)."""
    from fastapi import HTTPException
    from core.rule_store import add_rule_node, RuleStoreError, ValidationError
    try:
        return add_rule_node(
            req.tree_file, req.rule_id, node_id=req.node_id, pattern=req.pattern,
            reason=req.reason, result=req.result, confidence=req.confidence,
            citation=req.citation, action=req.action, negate=req.negate,
            actor=req.reviewer, change_reason=req.reason,
        )
    except (ValidationError, RuleStoreError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class RuleBlockReq(BaseModel):
    tree_file: str
    name: str
    law: str = ""
    reviewer: str = "준법관리자"


@app.post("/api/rule/block")
def api_rule_block(req: RuleBlockReq):
    """위반 유형(규칙 블록) 추가 — 새 법령도 조문·유형별로 규칙을 묶을 수 있게."""
    from fastapi import HTTPException
    from core.rule_store import add_rule_block, RuleStoreError, ValidationError
    try:
        return add_rule_block(req.tree_file, name=req.name, law=req.law,
                              actor=req.reviewer, change_reason=f"위반 유형 신설: {req.name}")
    except (ValidationError, RuleStoreError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/law/article")
def api_law_article(citation: str):
    """인용 조문을 국가법령정보에서 실측 조회 — 존재/삭제/제목/본문 반환(전문가 확인용)."""
    from api.law_api import fetch_article
    try:
        return fetch_article(citation)
    except Exception as e:
        return {"ok": False, "reachable": False, "found": False, "deleted": False,
                "message": f"조회 오류: {e}"}


class RuleDeleteReq(BaseModel):
    tree_file: str
    rule_id: str
    node_id: str
    reason: str = ""
    reviewer: str = "준법관리자"


class RuleEnableReq(BaseModel):
    tree_file: str
    rule_id: str
    node_id: str
    enabled: bool
    reason: str = ""
    reviewer: str = "준법관리자"


@app.post("/api/rule/delete")
def api_rule_delete(req: RuleDeleteReq):
    """전문가 추가 룰 삭제(원본 법령 룰은 거부 → 비활성화/낮춤 안내)."""
    from fastapi import HTTPException
    from core.rule_store import delete_node, RuleStoreError, ValidationError
    try:
        return delete_node(req.tree_file, req.rule_id, req.node_id,
                           actor=req.reviewer, change_reason=req.reason)
    except (ValidationError, RuleStoreError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rule/enable")
def api_rule_enable(req: RuleEnableReq):
    """노드 켜기/끄기(비활성화) — 원본 룰을 흔적 없이 잃지 않는 가역적 차단."""
    from fastapi import HTTPException
    from core.rule_store import set_enabled, RuleStoreError, ValidationError
    try:
        return set_enabled(req.tree_file, req.rule_id, req.node_id, req.enabled,
                          actor=req.reviewer, change_reason=req.reason)
    except (ValidationError, RuleStoreError) as e:
        raise HTTPException(status_code=400, detail=str(e))


class TreeCreateReq(BaseModel):
    file: str
    law: str
    name: str = ""
    jurisdiction: str = ""
    article: str = ""
    first_block_id: str = ""
    first_block_name: str = ""
    reviewer: str = "준법관리자"


@app.post("/api/tree/create")
def api_tree_create(req: TreeCreateReq):
    """새 법령 트리 생성 — 코드 수정 없이 신규 관할/법령을 라이브로 추가."""
    from fastapi import HTTPException
    from core.rule_store import create_tree, RuleStoreError, ValidationError
    try:
        return create_tree(
            req.file, law=req.law, name=req.name, jurisdiction=req.jurisdiction,
            article=req.article, first_block_id=req.first_block_id,
            first_block_name=req.first_block_name, actor=req.reviewer,
            change_reason="새 법령 트리 생성",
        )
    except (ValidationError, RuleStoreError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/rule_changes")
def api_rule_changes(limit: int = 50):
    """규칙 피드백 변경 이력(누가·언제·무엇을·왜·이전→이후)."""
    from api.history import list_rule_changes
    return {"items": list_rule_changes(limit)}


# ─── 규제 변경 모니터링 ─────────────────────────
@app.get("/api/law_watch")
def api_law_watch(refresh: bool = False):
    """감시 법령(트리 근거 법령+시행령)의 공포·시행일자 변경 감지."""
    from api.law_monitor import check_updates
    return check_updates(refresh=refresh)


class LawAckReq(BaseModel):
    law: str


@app.post("/api/law_watch/ack")
def api_law_watch_ack(req: LawAckReq):
    """개정 확인 처리 — 트리 대응 완료 후 현재 상태를 새 기준으로 저장."""
    from api.law_monitor import acknowledge
    return acknowledge(req.law)


# 직접 실행용
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=False)
