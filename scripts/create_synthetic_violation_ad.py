# -*- coding: utf-8 -*-
"""Create a synthetic Korean financial ad image for OCR/highlight testing."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "test_ads" / "synthetic_violation_ad.png"
FONT_BOLD = Path(r"C:\Windows\Fonts\malgunbd.ttf")
FONT_REG = Path(r"C:\Windows\Fonts\malgun.ttf")


def font(path: Path, size: int):
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGB", (1200, 1500), "#F3F8FF")
    draw = ImageDraw.Draw(img)

    blue = "#0046AD"
    deep = "#071D49"
    red = "#D9304F"
    gray = "#50627C"

    draw.rounded_rectangle([70, 60, 1130, 1440], radius=36, fill="white", outline="#C9D9F2", width=3)
    draw.text((105, 100), "JB 금융 테스트 광고", fill=blue, font=font(FONT_BOLD, 42))
    draw.text((105, 168), "심의 하이라이트 검증용 가상 이미지", fill=gray, font=font(FONT_REG, 25))

    draw.rounded_rectangle([105, 250, 1095, 520], radius=28, fill="#EAF3FF", outline="#B8D2FF", width=2)
    draw.text((145, 300), "연 10% 수익을 보장하는", fill=red, font=font(FONT_BOLD, 58))
    draw.text((145, 385), "안전한 투자 상품", fill=deep, font=font(FONT_BOLD, 72))

    draw.rounded_rectangle([105, 610, 1095, 890], radius=24, fill="#FFFFFF", outline="#D6E2F5", width=2)
    draw.text((145, 660), "원금 보장, 손실 걱정 없음", fill=red, font=font(FONT_BOLD, 52))
    draw.text((145, 750), "누구나 가입 가능 · 빠른 승인", fill=deep, font=font(FONT_BOLD, 42))
    draw.text((145, 820), "수수료와 위험 고지는 생략된 테스트 문구입니다.", fill=gray, font=font(FONT_REG, 28))

    draw.rounded_rectangle([105, 980, 1095, 1240], radius=24, fill="#003B8F")
    draw.text((145, 1035), "지금 바로 한도 조회하기", fill="white", font=font(FONT_BOLD, 54))
    draw.text((145, 1125), "최고의 수익률, 업계 1위 상품", fill="#FFD6DE", font=font(FONT_BOLD, 40))

    draw.text((105, 1320), "※ 본 이미지는 실제 금융회사의 광고가 아닌 OCR/하이라이트 테스트용 가상 광고입니다.", fill=gray, font=font(FONT_REG, 25))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
