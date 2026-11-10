"""ブラウザE2E（Playwright）。iPhone実機ではなくエミュレーションであり、実機テストの代替ではない。"""
import hashlib
import os
import time
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

from test_files import SAMPLES  # noqa: E402

SCREENS = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

CASES = [
    ("chromium-desktop", "chromium", None),
    ("chromium-iphone15-emulation", "chromium", "iPhone 15"),
    ("firefox-desktop", "firefox", None),
]


def wait_js(page, expr, timeout=15):
    """CSPがeval系を禁止するためevaluateでポーリングする。"""
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(expr):
            return
        time.sleep(0.1)
    raise AssertionError(f"timeout: {expr}")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture(scope="module")
def playwright_ctx():
    with pw.sync_playwright() as p:
        yield p


@pytest.mark.parametrize("label,engine,device", CASES, ids=[c[0] for c in CASES])
def test_browser_flow(live_server, playwright_ctx, tmp_path, label, engine, device):
    proc, port, shared = live_server
    p = playwright_ctx
    try:
        browser = getattr(p, engine).launch()
    except Exception as e:  # ブラウザ未導入
        pytest.skip(f"{engine} を起動できません: {str(e)[:80]}")
    opts = dict(p.devices[device]) if device else {"viewport": {"width": 1200, "height": 800}}
    if engine == "firefox":
        opts.pop("is_mobile", None)
        opts.pop("has_touch", None)
    ctx = browser.new_context(accept_downloads=True, **opts)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    mobile = bool(device)
    SCREENS.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{port}/"
    page.goto(base)
    assert "シェアファイル" in page.title()
    assert page.locator("h1").inner_text() == "シェアファイル"
    page.wait_for_selector("#list .empty")

    # フォルダ作成
    page.click("#btn-mkdir")
    page.fill("#pr-input", "写真")
    page.press("#pr-input", "Enter")
    page.wait_for_selector(".row .name:text-is('写真')")
    assert (shared / "写真").is_dir()

    # 複数ファイルをフォルダへアップロード（アップロード先選択）
    files = []
    for name in ("photo.jpg", "image.png", "doc.pdf", "movie.mp4", "note.txt", "archive.zip", "synthetic.heic"):
        f = tmp_path / name
        f.write_bytes(SAMPLES[name])
        files.append(str(f))
    page.click("#btn-upload")
    page.wait_for_selector("#dlg-upload[open]")
    page.select_option("#up-dest", "写真")
    page.set_input_files("#up-files", files)
    page.click("#up-start")
    page.wait_for_selector("#uploads .up-item.done >> nth=6", timeout=20000)
    assert page.locator("#uploads .up-item.err").count() == 0
    for name in SAMPLES:
        assert sha((shared / "写真" / name).read_bytes()) == sha(SAMPLES[name]), name
    assert not list((shared / "写真").glob(".sharefile-*"))
    page.click("#uploads button:has-text('閉じる')")

    # フォルダ移動と上位へ戻る
    page.click(".row .name:text-is('写真')")
    page.wait_for_selector(".row .name:text-is('photo.jpg')")
    assert page.locator("#crumbs .cur").inner_text() == "写真"
    page.screenshot(path=str(SCREENS / f"{label}-list.png"))
    if mobile:
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "横スクロールが発生"
        box = page.locator(".row .main").first.bounding_box()
        assert box["height"] >= 44
    page.click("#crumbs button:has-text('上へ')")
    page.wait_for_selector(".row .name:text-is('写真')")

    # 重複アップロード: 上書き確認ダイアログ
    page.click(".row .name:text-is('写真')")
    page.wait_for_selector(".row .name:text-is('note.txt')")
    dup = tmp_path / "note.txt"
    dup.write_text("NEW CONTENT")
    page.click("#btn-upload")
    page.wait_for_selector("#dlg-upload[open]")
    page.set_input_files("#up-files", str(dup))
    page.click("#up-start")
    page.wait_for_selector("#dlg-confirm[open]")
    assert (shared / "写真" / "note.txt").read_bytes() == SAMPLES["note.txt"]  # 確認前は上書きされない
    page.click("#cf-actions button:has-text('別名で保存')")
    page.wait_for_selector("#uploads .up-item.done >> nth=0")
    assert (shared / "写真" / "note (1).txt").read_text() == "NEW CONTENT"
    page.click("#uploads button:has-text('閉じる')")

    # Ubuntu側で直接配置 → 画面に反映（再取得）
    (shared / "写真" / "from_ubuntu.png").write_bytes(SAMPLES["image.png"])
    page.click("#btn-refresh")
    page.wait_for_selector(".row .name:text-is('from_ubuntu.png')")

    # 検索・並び替え
    page.fill("#search", "ubuntu")
    wait_js(page, "document.querySelectorAll('#list .row').length === 1")
    page.fill("#search", "")
    wait_js(page, "document.querySelectorAll('#list .row').length > 3")
    page.select_option("#sort", "size")
    page.click("#order")
    wait_js(page, "document.querySelector('#order').textContent.includes('降順')")
    wait_js(page, "document.querySelector('#list .row .name').textContent === 'movie.mp4'")  # サイズ降順で最大
    page.select_option("#sort", "name")
    page.click("#order")
    wait_js(page, "document.querySelector('#order').textContent.includes('昇順')")

    # ダウンロード（原本一致）
    page.click(".row .name:text-is('from_ubuntu.png')")
    page.wait_for_selector("#dlg-preview[open] img")
    wait_js(page, "document.querySelector('#pv-body img').naturalWidth > 0")  # 画像プレビュー
    page.screenshot(path=str(SCREENS / f"{label}-preview.png"))
    with page.expect_download() as dl:
        page.click("#pv-download")
    out = tmp_path / "dl.png"
    dl.value.save_as(out)
    assert dl.value.suggested_filename == "from_ubuntu.png"
    assert sha(out.read_bytes()) == sha(SAMPLES["image.png"])
    page.click("#pv-close")

    # テキスト/PDF/動画のプレビュー
    page.click(".row .name:text-is('note.txt')")
    wait_js(page, "document.querySelector('#pv-body pre') && document.querySelector('#pv-body pre').textContent.includes('日本語')")
    page.click("#pv-close")
    page.click(".row .name:text-is('doc.pdf')")
    page.wait_for_selector("#pv-body iframe")
    page.click("#pv-close")
    page.click(".row .name:text-is('movie.mp4')")
    page.wait_for_selector("#pv-body video")
    page.click("#pv-close")
    page.click(".row .name:text-is('archive.zip')")
    assert "プレビューできません" in page.locator("#pv-body").inner_text()
    assert page.locator("#pv-download").is_visible()  # 非対応形式でもダウンロード導線あり
    page.click("#pv-close")

    # SHA-256ボタンは廃止、保存ボタンは共有対応ブラウザのみ
    page.click(".row .name:text-is('photo.jpg')")
    assert page.locator("#pv-hash").count() == 0
    assert page.evaluate("!!(navigator.canShare && navigator.share)") == page.locator("#pv-save").is_visible()

    # 名前変更
    page.click("#pv-rename")
    page.fill("#pr-input", "renamed.jpg")
    page.press("#pr-input", "Enter")
    page.wait_for_selector(".row .name:text-is('renamed.jpg')")
    assert (shared / "写真" / "renamed.jpg").exists() and not (shared / "写真" / "photo.jpg").exists()

    # 移動
    page.click(".row .name:text-is('renamed.jpg')")
    page.click("#pv-move")
    page.select_option("#mv-dest", "")
    page.click("#dlg-move button:has-text('移動')")
    wait_js(page, "!document.querySelector('.row .name') || ![...document.querySelectorAll('.row .name')].some(e => e.textContent === 'renamed.jpg')")
    assert sha((shared / "renamed.jpg").read_bytes()) == sha(SAMPLES["photo.jpg"])

    # 削除: 確認でキャンセルすると残り、削除で消える
    page.click(".row .name:text-is('note.txt')")
    page.click("#pv-delete")
    page.wait_for_selector("#dlg-confirm[open]")
    page.click("#cf-actions button:has-text('キャンセル')")
    assert (shared / "写真" / "note.txt").exists()
    page.click("#pv-delete")
    page.click("#cf-actions button:has-text('削除する')")
    wait_js(page, "![...document.querySelectorAll('.row .name')].some(e => e.textContent === 'note.txt')")
    assert not (shared / "写真" / "note.txt").exists()

    # フォルダ削除: 内部も消えることを明示
    page.click("#crumbs button:has-text('共有フォルダ')")
    page.wait_for_selector(".row .name:text-is('写真')")
    page.locator(".row", has_text="写真").locator(".act.ovf").click() if mobile else page.locator(".row", has_text="写真").locator(".act.del").click()
    if mobile:
        page.click("#pv-delete")
    page.wait_for_selector("#dlg-confirm[open]")
    assert "すべて削除" in page.locator("#cf-msg").inner_text()
    page.click("#cf-actions button:has-text('削除する')")
    wait_js(page, "document.querySelector('#list .empty') === null || true")
    time.sleep(0.5)
    assert not (shared / "写真").exists()

    assert errors == [], errors
    ctx.close()
    browser.close()
