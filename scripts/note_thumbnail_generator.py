"""note_thumbnail_generator.py

note.com のアイキャッチ画像（1280×670）を記事タイトルから自動生成する。
デザイン: 金融・投資テーマ（ダーク系グラデーション + チャート装飾）

単独使用:
  python scripts/note_thumbnail_generator.py "記事タイトル" output.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow が未インストールです: pip install Pillow")
    sys.exit(1)

# ── サイズ ───────────────────────────────────────────
WIDTH  = 1280
HEIGHT = 670

# ── カラーパレット（ダーク金融テーマ） ─────────────
BG_TOP       = (12, 20, 35)      # 濃紺
BG_BOTTOM    = (8, 32, 28)       # 深緑
ACCENT       = (0, 210, 140)     # エメラルドグリーン（投資・成長感）
ACCENT2      = (255, 200, 60)    # ゴールド（配当・資産感）
TEXT_MAIN    = (240, 248, 255)   # ほぼ白
TEXT_SUB     = (140, 180, 160)   # くすみグリーン
GRID_COLOR   = (255, 255, 255, 18)  # 薄いグリッド線

# ── フォント候補 ──────────────────────────────────
FONT_CANDIDATES = [
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/yugothb.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_title(text: str, max_chars: int = 16) -> list[str]:
    """タイトルを適切な行数に折り返す"""
    lines: list[str] = []
    while text:
        if len(text) <= max_chars:
            lines.append(text)
            break
        # 句読点・スペースで切る
        cut = max_chars
        for sep in ["。", "、", "・", " ", "　", "】", "）"]:
            idx = text[:max_chars + 1].rfind(sep)
            if idx > 0:
                cut = idx + 1
                break
        lines.append(text[:cut])
        text = text[cut:]
    return lines


def generate(
    title: str,
    output_path: str | Path,
    category: str = "投資・Python",
    series: str = "",
) -> Path:
    """
    サムネイル画像を生成して保存する。

    Args:
        title:       記事タイトル
        output_path: 出力先パス
        category:    左上のカテゴリバッジ（例: "高配当株"）
        series:      右下のシリーズ名（例: "一生ガチホ計画 #1"）

    Returns: 保存先 Path
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── ベース背景（グラデーション） ──────────────
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(img)

    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * ratio)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * ratio)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # ── グリッド装飾（薄い罫線） ──────────────────
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for x in range(0, WIDTH, 80):
        odraw.line([(x, 0), (x, HEIGHT)], fill=GRID_COLOR, width=1)
    for y in range(0, HEIGHT, 80):
        odraw.line([(0, y), (WIDTH, y)], fill=GRID_COLOR, width=1)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── チャート風の折れ線装飾（右下） ──────────
    chart_points_raw = [0.55, 0.45, 0.60, 0.40, 0.50, 0.35, 0.45, 0.25, 0.38, 0.20, 0.30, 0.10]
    chart_x_start = WIDTH // 2
    chart_y_base  = HEIGHT - 40
    chart_height  = HEIGHT // 3
    chart_width   = WIDTH // 2 - 40
    step = chart_width // (len(chart_points_raw) - 1)
    pts = [
        (chart_x_start + i * step, int(chart_y_base - v * chart_height))
        for i, v in enumerate(chart_points_raw)
    ]
    # 塗り面（半透明）
    fill_pts = pts + [(pts[-1][0], chart_y_base), (pts[0][0], chart_y_base)]
    overlay2 = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw2 = ImageDraw.Draw(overlay2)
    odraw2.polygon(fill_pts, fill=(*ACCENT, 28))
    for i in range(len(pts) - 1):
        odraw2.line([pts[i], pts[i + 1]], fill=(*ACCENT, 140), width=3)
    # 最終値ドット
    lx, ly = pts[-1]
    odraw2.ellipse([(lx - 6, ly - 6), (lx + 6, ly + 6)], fill=(*ACCENT2, 220))
    img = Image.alpha_composite(img.convert("RGBA"), overlay2).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── 上部アクセントライン ─────────────────────
    draw.rectangle([(0, 0), (WIDTH, 5)], fill=ACCENT)

    # ── 左アクセントバー ─────────────────────────
    draw.rectangle([(48, 80), (56, HEIGHT - 80)], fill=(*ACCENT, 100))

    # ── カテゴリバッジ（左上） ───────────────────
    if category:
        cat_font = _get_font(26)
        bbox = draw.textbbox((0, 0), category, font=cat_font)
        bw = bbox[2] - bbox[0] + 28
        bh = bbox[3] - bbox[1] + 12
        draw.rounded_rectangle([(68, 30), (68 + bw, 30 + bh)], radius=6, fill=ACCENT)
        draw.text((82, 36), category, fill=(10, 10, 10), font=cat_font)

    # ── メインタイトル ───────────────────────────
    # 文字数に応じてフォントサイズを自動調整
    char_count = len(title)
    if char_count <= 12:
        font_size, max_chars = 82, 12
    elif char_count <= 20:
        font_size, max_chars = 68, 14
    elif char_count <= 30:
        font_size, max_chars = 58, 16
    else:
        font_size, max_chars = 50, 18

    title_font = _get_font(font_size)
    lines = _wrap_title(title, max_chars)
    line_h = int(font_size * 1.35)
    total_h = len(lines) * line_h
    y_start = (HEIGHT - total_h) // 2 - 10

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        tw = bbox[2] - bbox[0]
        x = max(72, (WIDTH - tw) // 2 - 60)   # チャートを避けて少し左寄せ
        y = y_start + i * line_h
        # シャドウ
        draw.text((x + 2, y + 2), line, fill=(0, 0, 0), font=title_font)
        draw.text((x, y), line, fill=TEXT_MAIN, font=title_font)

    # ── シリーズ名（右下） ───────────────────────
    if series:
        ser_font = _get_font(24)
        bbox = draw.textbbox((0, 0), series, font=ser_font)
        sw = bbox[2] - bbox[0]
        draw.text((WIDTH - sw - 48, HEIGHT - 52), series, fill=ACCENT2, font=ser_font)

    # ── ドメイン表記（左下） ─────────────────────
    domain_font = _get_font(20)
    draw.text((72, HEIGHT - 48), "note.com", fill=TEXT_SUB, font=domain_font)

    img.save(str(output_path), quality=95)
    print(f"[thumbnail] 生成: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python note_thumbnail_generator.py <title> [output.png] [category]")
        sys.exit(1)

    _title    = sys.argv[1]
    _out      = sys.argv[2] if len(sys.argv) > 2 else "note_thumbnail_test.png"
    _category = sys.argv[3] if len(sys.argv) > 3 else "投資・Python"
    generate(_title, _out, category=_category)
