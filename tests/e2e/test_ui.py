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


class TestConfigEndpoints:
    """設定APIエンドポイントのE2E検証。"""

    def test_APIカウンタにサーバー上限値が反映される(self, page):
        """loadRateLimits() によりAPIカウンタの上限表示がサーバー値に更新されること。"""
        counter = page.locator("#api-counter")
        # loadRateLimits() の非同期完了を待つ（上限値が "--" から数値に変わる）
        page.wait_for_function(
            "() => !document.getElementById('api-counter').textContent.includes('--')",
            timeout=5000,
        )
        text = counter.text_content()
        # "API: 0/100" のような形式を検証（数値は環境依存だが必ず数字/数字）
        assert "API:" in text
        assert "/" in text
        parts = text.split("/")
        assert parts[-1].strip().isdigit()

    def test_Proxyバッジに設定状態が表示される(self, page):
        """Proxy設定バッジが 'Proxy設定: ON' または 'Proxy設定: OFF' を表示すること。"""
        badge = page.locator("#btn-proxy")
        # loadProxyConfig() の非同期完了を待つ（"--" から ON/OFF に変わる）
        page.wait_for_function(
            "() => !document.getElementById('btn-proxy').textContent.includes('--')",
            timeout=5000,
        )
        text = badge.text_content()
        assert "Proxy設定:" in text
        assert ("ON" in text or "OFF" in text)


class TestHelpUI:
    """ヘルプポップアップの開閉・表示の回帰テスト。"""

    def test_ヘルプボタンでポップアップが開閉する(self, page):
        """?ボタンクリックでポップアップの表示/非表示が切り替わること。"""
        btn_help = page.locator("#btn-help")
        popup = page.locator("#help-popup")

        # 初期状態: 非表示（hiddenクラス付き）
        assert popup.get_attribute("class") is not None
        assert "hidden" in popup.get_attribute("class")

        # クリックで開く
        btn_help.click()
        assert "hidden" not in (popup.get_attribute("class") or "")

        # もう一度クリックで閉じる
        btn_help.click()
        page.wait_for_timeout(200)
        assert "hidden" in (popup.get_attribute("class") or "")

    def test_閉じるボタンでポップアップが閉じる(self, page):
        """ポップアップ内の×ボタンでポップアップが閉じること。"""
        btn_help = page.locator("#btn-help")
        popup = page.locator("#help-popup")
        btn_close = page.locator("#btn-help-close")

        # ポップアップを開く
        btn_help.click()
        assert "hidden" not in (popup.get_attribute("class") or "")

        # ×ボタンで閉じる
        btn_close.click()
        page.wait_for_timeout(200)
        assert "hidden" in (popup.get_attribute("class") or "")

    def test_ポップアップ外クリックで閉じる(self, page):
        """ポップアップ外の領域をクリックするとポップアップが閉じること。"""
        btn_help = page.locator("#btn-help")
        popup = page.locator("#help-popup")

        # ポップアップを開く
        btn_help.click()
        assert "hidden" not in (popup.get_attribute("class") or "")

        # ポップアップ外（ページ本体）をクリック
        page.locator("h1").click()
        page.wait_for_timeout(200)
        assert "hidden" in (popup.get_attribute("class") or "")


class TestDuplicateSkipSetting:
    """重複スキップ回数スライダーの回帰テスト。"""

    def test_スライダーが初期値2で表示される(self, page):
        """ヘルプポップアップ内のスライダーが初期値2を持つこと。"""
        # ポップアップを開く
        page.locator("#btn-help").click()

        slider = page.locator("#duplicate-skip-count")
        value_label = page.locator("#duplicate-skip-value")

        assert slider.is_visible()
        assert slider.input_value() == "2"
        assert "2回" in value_label.text_content()

    def test_スライダー値変更で表示が更新される(self, page):
        """スライダーを動かすと横の表示テキストが即座に更新されること。"""
        page.locator("#btn-help").click()

        slider = page.locator("#duplicate-skip-count")
        value_label = page.locator("#duplicate-skip-value")

        # スライダーを4に変更（fill + inputイベント発火）
        slider.fill("4")
        slider.dispatch_event("input")

        assert "4回" in value_label.text_content()

    def test_スライダー値がlocalStorageに保存される(self, page):
        """スライダーの変更値がlocalStorageに保存されること。"""
        page.locator("#btn-help").click()

        slider = page.locator("#duplicate-skip-count")
        slider.fill("3")
        slider.dispatch_event("input")

        # localStorageから保存値を取得
        stored = page.evaluate("() => localStorage.getItem('duplicateSkipCount')")
        assert stored == "3"

    def test_ページ再読込後にスライダー値が復元される(self, page, live_server):
        """localStorageに保存された値がページ再読込後にスライダーに反映されること。"""
        # まずスライダーを5に変更して保存
        page.locator("#btn-help").click()
        slider = page.locator("#duplicate-skip-count")
        slider.fill("5")
        slider.dispatch_event("input")

        # ページを再読込
        page.goto(live_server)
        page.wait_for_load_state("domcontentloaded")

        # ポップアップを開いてスライダーを確認
        page.locator("#btn-help").click()
        restored_slider = page.locator("#duplicate-skip-count")
        restored_label = page.locator("#duplicate-skip-value")

        assert restored_slider.input_value() == "5"
        assert "5回" in restored_label.text_content()

        # テスト後にlocalStorageをクリーンアップ
        page.evaluate("() => localStorage.removeItem('duplicateSkipCount')")
