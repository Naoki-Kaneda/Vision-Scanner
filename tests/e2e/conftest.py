"""
E2Eテスト用フィクスチャ。
Flaskアプリをバックグラウンドスレッドで起動し、Playwrightで接続する。
"""

import threading
import time

import pytest

# Playwright未インストール時はE2Eテストを自動スキップ
pytest.importorskip("playwright")

from app import app  # noqa: E402


@pytest.fixture(scope="session")
def live_server():
    """Flaskアプリをテスト用ポートで起動するフィクスチャ。"""
    port = 5099
    server_thread = threading.Thread(
        target=lambda: app.run(port=port, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    # サーバー起動待ち
    time.sleep(1.0)
    yield f"http://127.0.0.1:{port}"


@pytest.fixture
def page(live_server):
    """Playwright ページフィクスチャ。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        pg = context.new_page()
        pg.goto(live_server)
        yield pg
        browser.close()
