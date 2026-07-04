"""
utils/image_annotate.py
────────────────────────────────────────────────────────────────
이미지 광고물 OCR — 단어별 좌표(bounding box) 추출

  ocr_with_boxes(data) : OCR + 단어별 좌표를 추출 (file_extract.ocr_data 재사용)
                         boxes = [{"text","x","y","w","h","conf"}, ...]
                         → 부작위/현저성 위험(layout_risk.analyze_ocr_layout)의 입력
────────────────────────────────────────────────────────────────
"""
from __future__ import annotations


def ocr_with_boxes(data: bytes):
    """OCR + 단어별 좌표. Returns (full_text, boxes)."""
    from utils.file_extract import ocr_data
    return ocr_data(data)
