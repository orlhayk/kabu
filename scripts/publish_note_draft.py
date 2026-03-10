"""publish_note_draft.py

note.com の下書きを自動保存するスクリプト。
サムネイル（アイキャッチ）もタイトルから自動生成してアップロードする。

【初回】
  python scripts/publish_note_draft.py --login
  → Chrome が開くのでnote.comにログイン → ログイン後にEnterを押す → セッション保存

【2回目以降】
  python scripts/publish_note_draft.py
  → サムネ自動生成 → note.comに下書き保存 → サムネをアップロード
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("Playwright が未インストールです。実行してください:")
    print("  pip install playwright")
    print("  python -m playwright install chrome")
    sys.exit(1)

ROOT          = Path(__file__).resolve().parents[1]
DRAFT_MD      = ROOT / "docs" / "drafts" / "stock_system_note_draft.md"
PROFILE_DIR   = ROOT / "secrets" / "note-profile"
THUMBNAIL_OUT = ROOT / "reports" / "note_thumbnail.png"

# AI サムネ生成器を同ディレクトリから読み込む（Pillow専用にフォールバック）
sys.path.insert(0, str(ROOT / "scripts"))
try:
    from ai_thumbnail_generator import generate as generate_thumbnail
    HAS_THUMBNAIL = True
except ImportError:
    try:
        from note_thumbnail_generator import generate as generate_thumbnail
        HAS_THUMBNAIL = True
    except ImportError:
        HAS_THUMBNAIL = False


# ---------- Markdown → note投稿用テキスト ----------

def md_to_note_text(md: str) -> tuple[str, str]:
    """Markdownを (タイトル, 本文) に分解してnote向けに整形する"""

    # HTMLコメント（USER_EDIT等）を除去
    md = re.sub(r"<!--.*?-->", "", md, flags=re.DOTALL)

    # frontmatter を除去
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.DOTALL)

    lines = md.splitlines()

    # 先頭のH1をタイトルに
    title = ""
    body_lines: list[str] = []
    found_title = False
    for line in lines:
        if not found_title and line.startswith("# "):
            title = line.lstrip("# ").strip()
            found_title = True
        else:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()

    # Markdown記法を読みやすいプレーンテキストに変換
    # H2 → ■ 見出し
    body = re.sub(r"^## (.+)$", r"■ \1", body, flags=re.MULTILINE)
    # H3 → ▶ 見出し
    body = re.sub(r"^### (.+)$", r"▶ \1", body, flags=re.MULTILINE)
    # 太字 **text** → text（そのまま）
    body = re.sub(r"\*\*(.+?)\*\*", r"\1", body)
    # インラインコード `text` → text
    body = re.sub(r"`(.+?)`", r"\1", body)
    # コードブロック ```...``` を整形
    body = re.sub(r"```\w*\n(.*?)```", r"\1", body, flags=re.DOTALL)
    # テーブル行は | 区切りで残す（note側でそのまま読める）
    # 水平線 --- を空行に
    body = re.sub(r"^\s*---+\s*$", "", body, flags=re.MULTILINE)
    # 連続空行を2行以内に
    body = re.sub(r"\n{3,}", "\n\n", body)

    return title.strip(), body.strip()


# ---------- Playwright 操作 ----------

def login_and_save_session() -> None:
    """初回ログイン用。ログイン後にEnterを押すとセッションを保存する"""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=["--start-maximized"],
        )
        page = ctx.new_page()
        page.goto("https://note.com/login")
        print("\nnote.com のログインページを開きました。")
        print("ブラウザでログインしてください。")
        print("ログインが完了したら、このターミナルで Enter を押してください...")
        input()
        ctx.close()
    print("セッションを保存しました。次回から自動でログイン状態が使われます。")


def _upload_thumbnail(page, thumbnail_path: Path) -> None:
    """note.com のアイキャッチ画像をアップロードする。"""
    # 公開設定パネルを開く（サムネイル設定はここにある）
    panel_opened = False
    for selector in [
        'button:has-text("公開設定")',
        'button:has-text("公開する")',
        '[data-testid="publish-settings-button"]',
        'button[aria-label*="公開"]',
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=3000):
                btn.click()
                page.wait_for_timeout(1500)
                panel_opened = True
                break
        except PWTimeout:
            continue

    if not panel_opened:
        print("  ⚠ 公開設定パネルが開けませんでした。手動でアイキャッチを設定してください。")
        return

    # file input を探してアップロード（note.comは通常 accept="image/*"）
    uploaded = False
    for selector in [
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
    ]:
        try:
            fi = page.locator(selector)
            if fi.count() > 0:
                fi.first.set_input_files(str(thumbnail_path))
                page.wait_for_timeout(3000)
                print("  ✅ アイキャッチアップロード完了")
                uploaded = True
                break
        except Exception as e:
            print(f"  ⚠ アップロード試行失敗 ({e})")

    if not uploaded:
        print("  ⚠ ファイル入力が見つかりませんでした。手動でアイキャッチを設定してください。")

    # パネルを閉じる（Escape or 閉じるボタン）
    for close_sel in [
        'button:has-text("閉じる")',
        'button[aria-label*="閉じ"]',
        '[data-testid="close-button"]',
    ]:
        try:
            btn = page.locator(close_sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_timeout(500)
                break
        except PWTimeout:
            pass
    else:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)


def publish_draft(dry_run: bool = False) -> None:
    if not DRAFT_MD.exists():
        print(f"下書きファイルが見つかりません: {DRAFT_MD}")
        sys.exit(1)

    title, body = md_to_note_text(DRAFT_MD.read_text(encoding="utf-8"))
    print(f"タイトル : {title[:60]}...")
    print(f"本文文字数: {len(body):,} 字")

    if dry_run:
        print("\n--- DRY RUN: 実際には投稿しません ---")
        print(body[:300])
        return

    # ---- サムネイル生成（ブラウザ起動前に済ませる）----
    thumbnail_path: Path | None = None
    if HAS_THUMBNAIL:
        try:
            THUMBNAIL_OUT.parent.mkdir(parents=True, exist_ok=True)
            print("\nAI サムネイルを生成中...")
            generate_thumbnail(title, THUMBNAIL_OUT)
            thumbnail_path = THUMBNAIL_OUT
        except Exception as e:
            print(f"⚠ サムネイル生成失敗 ({e})。スキップします。")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=["--start-maximized"],
            slow_mo=80,
        )
        page = ctx.new_page()

        # 新規記事作成ページへ
        print("\nnote.com を開いています...")
        page.goto("https://note.com/notes/new", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # ---- タイトル入力 ----
        print("タイトルを入力中...")
        try:
            title_sel = 'textarea[placeholder*="タイトル"], input[placeholder*="タイトル"]'
            page.wait_for_selector(title_sel, timeout=10000)
            page.click(title_sel)
            page.fill(title_sel, title)
        except PWTimeout:
            # プレースホルダが異なる場合のフォールバック
            page.keyboard.press("Tab")
            page.keyboard.type(title, delay=20)

        page.keyboard.press("Tab")
        page.wait_for_timeout(500)

        # ---- 本文入力（クリップボード経由でペースト） ----
        print("本文をクリップボード経由で貼り付け中...")
        page.evaluate(
            """(text) => {
                const el = document.querySelector(
                    '[contenteditable="true"]:not([placeholder*="タイトル"]), '
                    + '.DraftEditor-editorContainer, '
                    + '[data-placeholder]'
                );
                if (el) { el.focus(); }
            }""",
            body,
        )
        # クリップボードにセットしてCtrl+V
        page.evaluate(
            """async (text) => {
                await navigator.clipboard.writeText(text);
            }""",
            body,
        )
        page.wait_for_timeout(300)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(1000)

        # ---- 下書き保存 ----
        print("下書き保存中...")
        saved = False
        for selector in [
            'button:has-text("下書き保存")',
            '[data-testid="draft-save-button"]',
            'button[aria-label*="下書き"]',
        ]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    saved = True
                    break
            except PWTimeout:
                continue

        if not saved:
            print("⚠ 下書き保存ボタンが見つかりませんでした。手動で保存してください。")
        else:
            page.wait_for_timeout(2000)
            print(f"\n✅ 下書き保存完了！")
            print(f"URL: {page.url}")

        # ---- アイキャッチ（ヘッダー画像）アップロード ----
        if saved and thumbnail_path and thumbnail_path.exists():
            print("\nアイキャッチ画像をアップロード中...")
            _upload_thumbnail(page, thumbnail_path)

        print("3秒後にブラウザを閉じます...")
        time.sleep(3)
        ctx.close()


# ---------- エントリポイント ----------

def main() -> None:
    parser = argparse.ArgumentParser(description="note.com 下書き自動保存")
    parser.add_argument("--login", action="store_true", help="初回ログインセッションを保存する")
    parser.add_argument("--dry", action="store_true", help="変換結果だけ確認（投稿しない）")
    args = parser.parse_args()

    if args.login:
        login_and_save_session()
    else:
        publish_draft(dry_run=args.dry)


if __name__ == "__main__":
    main()
