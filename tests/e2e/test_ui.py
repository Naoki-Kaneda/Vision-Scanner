"""
E2Eテスト: Playwrightを使用したUI動作検証。
カメラ機能はCI環境で利用不可のため、DOM構造・モード切替・エラー表示を検証する。
"""

import pytest

# Playwright未インストール時はE2Eテストを自動スキップ
pytest.importorskip("playwright")


class TestPageLoad:
    """ページ読み込みと初期状態の検証。"""

    def test_ページが正常に読み込まれる(self, page):
        """メインページが200で返り、タイトルが正しいこと。"""
        assert "Vision AI Scanner" in page.title()

    def test_全UIコントロールが存在する(self, page):
        """必要なUI要素がすべてDOM上に存在すること。"""
        assert page.locator("#btn-scan").is_visible()
        assert page.locator("#btn-camera").is_visible()
        assert page.locator("#btn-file").is_visible()
        assert page.locator("#mode-text").is_visible()
        assert page.locator("#mode-object").is_visible()
        assert page.locator("#result-list").is_visible()
        assert page.locator("#api-counter").is_visible()

    def test_CSPヘッダーにunsafe_inlineが含まれない(self, page):
        """ページのCSPに unsafe-inline が使われていないこと。"""
        # Playwrightのpage.contextからレスポンスヘッダーを直接取得できないため
        # APIレスポンスで検証
        response = page.request.get(page.url)
        csp = response.headers.get("content-security-policy", "")
        assert "'unsafe-inline'" not in csp


class TestModeSwitch:
    """モード切替のUI動作検証。"""

    def test_テキストモードがデフォルトでアクティブ(self, page):
        """初期状態でテキストモードボタンがactive。"""
        text_btn = page.locator("#mode-text")
        assert "active" in text_btn.get_attribute("class")

    def test_物体モードに切り替えできる(self, page):
        """物体モードボタンクリックでクラスが切り替わること。"""
        page.locator("#mode-object").click()
        obj_btn = page.locator("#mode-object")
        text_btn = page.locator("#mode-text")
        assert "active" in obj_btn.get_attribute("class")
        assert "active" not in text_btn.get_attribute("class")

    def test_モード切替で結果リストがリセットされる(self, page):
        """モード切替時にプレースホルダーテキストに戻ること。"""
        page.locator("#mode-object").click()
        placeholder = page.locator(".placeholder-text")
        assert placeholder.is_visible()
        assert "スキャン" in placeholder.text_content()


class TestErrorDisplay:
    """エラー時のUI表示検証。"""

    def test_APIエラーレスポンスをJSONで受け取れる(self, page, live_server):
        """不正なリクエストに対してJSONエラーが返ること。"""
        response = page.request.post(
            f"{live_server}/api/analyze",
            data='{"mode": "text"}',
            headers={"Content-Type": "application/json"},
        )
        data = response.json()
        assert data["ok"] is False
        assert data["error_code"] == "MISSING_IMAGE"

    def test_不正フォーマットにJSONエラーが返る(self, page, live_server):
        """非JSONリクエストに対してもJSONエラーが返ること。"""
        response = page.request.post(
            f"{live_server}/api/analyze",
            data="not json",
            headers={"Content-Type": "text/plain"},
        )
        data = response.json()
        assert data["ok"] is False
        assert data["error_code"] == "INVALID_FORMAT"
