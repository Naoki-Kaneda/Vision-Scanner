"""
E2Eテスト用フィクスチャ。
Flaskアプリをバックグラウンドスレッドで起動し、Playwrightで接続する。
"""

import threading

import pytest
from werkzeug.serving import make_server

# Playwright未インストール時はE2Eテストを自動スキップ
pytest.importorskip("playwright")

from app import app  # noqa: E402


@pytest.fixture(scope="session")
def live_server():
    """Flaskアプリを空いているポートで起動するフィクスチャ。"""
    # ポート0を渡すとOSが空いているポートを選ぶ。2つの作業フォルダで同時に走らせても衝突しない。
    # make_server は待ち受けを始めてから戻るので、起動待ちは要らない
    server = make_server("127.0.0.1", 0, app)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def page(live_server):
    """Playwright ページフィクスチャ。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 画面はブラウザの言語で日英が切り替わる。テストは日本語表示を前提にするので固定する
        context = browser.new_context(locale="ja-JP")
        pg = context.new_page()
        pg.goto(live_server)
        yield pg
        browser.close()
