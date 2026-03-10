"""ai_thumbnail_generator.py

AI画像生成 + Pillow文字合成でnote.com用サムネ（1280×670）を自動生成する。

【使い方】
  # Pollinations.ai（無料・APIキー不要）
  python scripts/ai_thumbnail_generator.py "記事タイトル" output.png

  # Gemini Imagen（無料枠 / 高品質）
  set GEMINI_API_KEY=your_key_here
  python scripts/ai_thumbnail_generator.py "記事タイトル" output.png

【APIキーの取得】
  Gemini: https://aistudio.google.com/  →「Get API key」（無料）
  Pollinations: 不要（デフォルト）

【仕組み】
  1. 記事タイトルからAIプロンプトを自動生成
  2. AI（Gemini or Pollinations）で背景画像を生成
  3. Pillowで日本語タイトルテキストを合成
  4. PNG保存
"""

from __future__ import annotations

import io
import os
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    print("Pillow が未インストールです: pip install Pillow")
    sys.exit(1)

# ─── 設定 ────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 670
FONT_CANDIDATES = [
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/yugothb.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")


# ─── フォント ─────────────────────────────────────────
def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ─── テキスト折り返し ─────────────────────────────────
def _wrap(text: str, max_chars: int = 16) -> list[str]:
    lines: list[str] = []
    while text:
        if len(text) <= max_chars:
            lines.append(text)
            break
        cut = max_chars
        for sep in ["。", "、", "・", " ", "　", "】", "）", "」"]:
            idx = text[:max_chars + 1].rfind(sep)
            if idx > 0:
                cut = idx + 1
                break
        lines.append(text[:cut])
        text = text[cut:]
    return lines


# ─── プロンプト生成 ───────────────────────────────────
def _build_prompt(title: str, style: str = "finance") -> str:
    """記事タイトルから英語の画像生成プロンプトを作る"""
    keywords = {
        "配当":   "dividend income, stock certificates, growing money tree",
        "株":     "stock market charts, trading dashboard, financial data",
        "投資":   "investment portfolio, wealth growth, financial freedom",
        "自動化": "automation, code on screen, Python programming, digital flow",
        "Python": "Python code, terminal screen, programming environment",
        "ガチホ": "long-term holding, patient investor, stable growth chart",
        "FIRE":   "financial independence, sunrise, freedom lifestyle",
        "資産":   "asset growth, wealth management, financial chart",
        "配当株": "dividend stocks, passive income flow, portfolio chart",
    }
    extra = next(
        (v for k, v in keywords.items() if k in title),
        "Japanese stock market, financial charts, investment data"
    )
    return (
        f"Cinematic dark finance background. {extra}. "
        "Ultra-wide format 1280x670. Dark navy and deep green gradient background. "
        "Abstract glowing chart lines, subtle grid pattern, bokeh lights. "
        "Professional, clean, modern. NO text, NO people, NO logos. "
        "Photorealistic, high detail, dramatic lighting."
    )


# ─── 画像生成: Pollinations.ai（無料・キー不要）────────
def _gen_pollinations(prompt: str) -> Image.Image:
    import urllib.parse
    import urllib.request

    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={WIDTH}&height={HEIGHT}&nologo=1&seed={int(time.time()) % 9999}"
    )
    print(f"  Pollinations.ai にリクエスト中...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return Image.open(io.BytesIO(resp.read())).convert("RGB")


# ─── 画像生成: Gemini Imagen（無料枠あり） ───────────
def _gen_gemini(prompt: str) -> Image.Image:
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai が未インストール: pip install google-generativeai")

    genai.configure(api_key=GEMINI_API_KEY)
    print("  Gemini Imagen にリクエスト中...")

    model = genai.ImageGenerationModel("imagen-3.0-generate-001")
    result = model.generate_images(
        prompt=prompt,
        number_of_images=1,
        aspect_ratio="16:9",
        safety_filter_level="block_only_high",
        person_generation="dont_allow",
    )
    img_bytes = result.images[0]._pil_image if hasattr(result.images[0], "_pil_image") \
                else Image.open(io.BytesIO(result.images[0].image.image_bytes))
    return img_bytes.resize((WIDTH, HEIGHT)).convert("RGB")


# ─── 背景画像を取得（Gemini → Pollinations → Pillowフォールバック）──
def _gen_pillow_bg() -> Image.Image:
    """AI生成が使えない場合のPillowグラデーション背景"""
    import struct
    bg = Image.new("RGB", (WIDTH, HEIGHT))
    pixels = []
    for y in range(HEIGHT):
        for x in range(WIDTH):
            r = int(8  + 4  * x / WIDTH)
            g = int(20 + 12 * (1 - y / HEIGHT))
            b = int(35 + 20 * (1 - x / WIDTH))
            pixels.append((r, g, b))
    bg.putdata(pixels)
    return bg


def _get_background(prompt: str) -> Image.Image:
    if GEMINI_API_KEY:
        try:
            return _gen_gemini(prompt)
        except Exception as e:
            print(f"  Gemini失敗 ({e})、Pollinations.aiにフォールバック...")
    try:
        return _gen_pollinations(prompt)
    except Exception as e:
        print(f"  Pollinations.ai失敗 ({e})、Pillowグラデーションにフォールバック...")
        return _gen_pillow_bg()


# ─── テキスト合成 ─────────────────────────────────────
def _overlay_text(
    bg: Image.Image,
    title: str,
    category: str = "投資・Python",
    series: str = "",
) -> Image.Image:
    img = bg.resize((WIDTH, HEIGHT)).convert("RGBA")

    # 下半分に暗いオーバーレイ（テキスト読みやすくする）
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for y in range(HEIGHT // 3, HEIGHT):
        alpha = int(180 * (y - HEIGHT // 3) / (HEIGHT * 2 // 3))
        odraw.line([(0, y), (WIDTH, y)], fill=(0, 0, 0, alpha))
    # 左側にグラデーションオーバーレイ
    for x in range(WIDTH // 2):
        alpha = int(140 * (1 - x / (WIDTH // 2)))
        odraw.line([(x, 0), (x, HEIGHT)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # 上部アクセントライン
    draw.rectangle([(0, 0), (WIDTH, 6)], fill=(0, 210, 140, 255))

    # カテゴリバッジ
    if category:
        cat_font = _font(26)
        bbox = draw.textbbox((0, 0), category, font=cat_font)
        bw, bh = bbox[2] - bbox[0] + 28, bbox[3] - bbox[1] + 12
        draw.rounded_rectangle([(52, 28), (52 + bw, 28 + bh)], radius=6,
                                fill=(0, 210, 140, 230))
        draw.text((66, 34), category, fill=(10, 20, 10), font=cat_font)

    # メインタイトル
    char_count = len(title)
    if char_count <= 12:   font_size, max_chars = 86, 12
    elif char_count <= 20: font_size, max_chars = 70, 14
    elif char_count <= 30: font_size, max_chars = 60, 16
    else:                  font_size, max_chars = 52, 18

    title_font = _font(font_size)
    lines = _wrap(title, max_chars)
    line_h = int(font_size * 1.38)
    total_h = len(lines) * line_h
    y_start = (HEIGHT - total_h) // 2 - 20

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        tw = bbox[2] - bbox[0]
        x = max(56, (WIDTH - tw) // 2 - 80)
        y = y_start + i * line_h
        # シャドウ（くっきり）
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, 3)]:
            draw.text((x + dx, y + dy), line, fill=(0, 0, 0, 200), font=title_font)
        draw.text((x, y), line, fill=(240, 248, 255), font=title_font)

    # シリーズ（右下）
    if series:
        ser_font = _font(24)
        bbox = draw.textbbox((0, 0), series, font=ser_font)
        sw = bbox[2] - bbox[0]
        draw.text((WIDTH - sw - 48, HEIGHT - 52), series,
                  fill=(255, 200, 60, 220), font=ser_font)

    # ドメイン（左下）
    draw.text((56, HEIGHT - 46), "note.com", fill=(140, 180, 160, 180), font=_font(20))

    return img.convert("RGB")


# ─── メイン ───────────────────────────────────────────
def generate(
    title: str,
    output_path: str | Path,
    category: str = "投資・Python",
    series: str = "",
    style: str = "finance",
) -> Path:
    """
    AIサムネイルを生成して保存する。

    Args:
        title:       記事タイトル
        output_path: 保存先
        category:    カテゴリバッジ（例: "高配当株"）
        series:      シリーズ名（例: "一生ガチホ計画 #1"）

    Returns: 保存先 Path
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 【下書き】などのプレフィックスをサムネタイトルから除去
    title = re.sub(r"^【.{2,6}】\s*", "", title).strip()

    prompt = _build_prompt(title, style)
    print(f"[thumbnail] タイトル: {title}")
    print(f"[thumbnail] プロンプト: {prompt[:80]}...")

    bg = _get_background(prompt)
    img = _overlay_text(bg, title, category=category, series=series)
    img.save(str(output_path), quality=95)
    print(f"[thumbnail] 保存: {output_path}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ai_thumbnail_generator.py <title> [output.png] [category]")
        print()
        print("Gemini使用（高品質）:")
        print("  set GEMINI_API_KEY=your_key_here")
        print("  python scripts/ai_thumbnail_generator.py \"タイトル\" out.png")
        print()
        print("APIキー不要（Pollinations.ai）:")
        print("  python scripts/ai_thumbnail_generator.py \"タイトル\" out.png")
        sys.exit(1)

    _title    = sys.argv[1]
    _out      = sys.argv[2] if len(sys.argv) > 2 else "ai_thumbnail_test.png"
    _category = sys.argv[3] if len(sys.argv) > 3 else "投資・Python"
    generate(_title, _out, category=_category)
