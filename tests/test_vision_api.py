"""
vision_api.py の単体テスト。
部分エラー・タイムアウト・接続失敗・モード不正・パーサー境界ケースをカバー。
"""

import pytest
from unittest.mock import patch
from requests.exceptions import Timeout, ConnectionError as RequestsConnectionError, RequestException
from conftest import make_b64, make_mock_response


# ─── detect_content: モード不正値 ─────────────────
class TestDetectContentValidation:
    """detect_content のバリデーションテスト。"""

    def test_不正なmodeはValueErrorを投げる(self):
        """mode が text/object 以外は ValueError が発生すること。"""
        from vision_api import detect_content
        with pytest.raises(ValueError, match="不正なモード"):
            detect_content(make_b64(), mode="invalid")

    @patch.dict("os.environ", {"VISION_API_KEY": ""})
    def test_APIキー未設定はValueErrorを投げる(self):
        """VISION_API_KEY が未設定の場合は ValueError が発生すること。"""
        import vision_api
        # APIキーをクリア
        original = vision_api.API_KEY
        vision_api.API_KEY = None
        try:
            with pytest.raises(ValueError, match="APIキーが未設定"):
                from vision_api import detect_content
                detect_content(make_b64(), mode="text")
        finally:
            vision_api.API_KEY = original


# ─── detect_content: HTTP エラー ──────────────────
class TestDetectContentHttpErrors:
    """HTTPレベルのエラーハンドリングテスト。"""

    @patch("vision_api.session.post")
    def test_HTTP500はokFalseを返す(self, mock_post):
        """Vision API が HTTP 500 を返した場合は ok=False を返すこと。"""
        mock_post.return_value = make_mock_response(status_code=500)
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="object")
        assert result["ok"] is False
        assert result["error_code"] == "API_500"

    @patch("vision_api.session.post")
    def test_タイムアウトはokFalseを返す(self, mock_post):
        """タイムアウト発生時は ok=False, error_code=TIMEOUT を返すこと。"""
        mock_post.side_effect = Timeout()
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "TIMEOUT"

    @patch("vision_api.session.post")
    def test_接続エラーはokFalseを返す(self, mock_post):
        """接続失敗時は ok=False, error_code=CONNECTION_ERROR を返すこと。"""
        mock_post.side_effect = RequestsConnectionError()
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "CONNECTION_ERROR"

    @patch("vision_api.session.post")
    def test_その他通信エラーはokFalseを返す(self, mock_post):
        """RequestException 発生時は ok=False, error_code=REQUEST_ERROR を返すこと。"""
        mock_post.side_effect = RequestException("generic error")
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "REQUEST_ERROR"


# ─── detect_content: Vision API 部分エラー ────────
class TestDetectContentPartialError:
    """HTTP 200 だが responses[0].error がある場合のテスト。"""

    @patch("vision_api.session.post")
    def test_部分エラーはokFalseを返す(self, mock_post):
        """HTTP 200 でも responses[0].error があれば ok=False を返すこと。"""
        mock_post.return_value = make_mock_response(status_code=200, json_data={
            "responses": [{
                "error": {
                    "code": 400,
                    "message": "Bad image data",
                }
            }]
        })
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is False
        assert "VISION_400" in result["error_code"]
        assert "Bad image data" in result["message"]


# ─── パーサー境界ケース ───────────────────────────
class TestParsers:
    """_parse_text_response / _parse_object_response の境界ケース。"""

    def test_テキストレスポンスが空の場合空タプルを返す(self):
        """textAnnotations がない場合は (空リスト, None) を返すこと。"""
        from vision_api import _parse_text_response
        data, img_size = _parse_text_response({})
        assert data == []
        assert img_size is None

        data, img_size = _parse_text_response({"textAnnotations": []})
        assert data == []
        assert img_size is None

    def test_テキストレスポンスが個別アノテーションをパースする(self):
        """textAnnotations[1:] から各テキストのラベルと座標を返すこと。"""
        from vision_api import _parse_text_response
        data, img_size = _parse_text_response({
            "textAnnotations": [
                {
                    "description": "Hello World",
                    "boundingPoly": {"vertices": [
                        {"x": 0, "y": 0}, {"x": 100, "y": 0},
                        {"x": 100, "y": 50}, {"x": 0, "y": 50},
                    ]},
                },
                {
                    "description": "Hello",
                    "boundingPoly": {"vertices": [
                        {"x": 0, "y": 0}, {"x": 50, "y": 0},
                        {"x": 50, "y": 25}, {"x": 0, "y": 25},
                    ]},
                },
                {
                    "description": "World",
                    "boundingPoly": {"vertices": [
                        {"x": 55, "y": 0}, {"x": 100, "y": 0},
                        {"x": 100, "y": 25}, {"x": 55, "y": 25},
                    ]},
                },
            ]
        })
        assert len(data) == 2
        assert data[0]["label"] == "Hello"
        assert data[1]["label"] == "World"
        assert len(data[0]["bounds"]) == 4
        assert img_size == [100, 50]

    def test_テキストレスポンスが空文字アノテーションを除外する(self):
        """空文字・空白のdescriptionは除外されること。"""
        from vision_api import _parse_text_response
        data, _ = _parse_text_response({
            "textAnnotations": [
                {"description": "Full text", "boundingPoly": {"vertices": [
                    {"x": 0, "y": 0}, {"x": 100, "y": 0},
                    {"x": 100, "y": 50}, {"x": 0, "y": 50},
                ]}},
                {"description": "Hello", "boundingPoly": {"vertices": [
                    {"x": 0, "y": 0}, {"x": 50, "y": 0},
                    {"x": 50, "y": 25}, {"x": 0, "y": 25},
                ]}},
                {"description": "   ", "boundingPoly": {"vertices": [
                    {"x": 55, "y": 0}, {"x": 60, "y": 0},
                    {"x": 60, "y": 25}, {"x": 55, "y": 25},
                ]}},
            ]
        })
        assert len(data) == 1
        assert data[0]["label"] == "Hello"

    def test_物体レスポンスが空の場合空リストを返す(self):
        """localizedObjectAnnotations がない場合は空リストを返すこと。"""
        from vision_api import _parse_object_response
        assert _parse_object_response({}) == []
        assert _parse_object_response({"localizedObjectAnnotations": []}) == []

    def test_物体ラベルに日本語訳がない場合英語のみ表示(self):
        """翻訳辞書にないラベルは英語のみで表示すること。"""
        from vision_api import _parse_object_response
        result = _parse_object_response({
            "localizedObjectAnnotations": [{
                "name": "Quasar",
                "score": 0.99,
                "boundingPoly": {"normalizedVertices": [
                    {"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1},
                    {"x": 0.5, "y": 0.5}, {"x": 0.1, "y": 0.5},
                ]},
            }]
        })
        assert len(result) == 1
        assert "Quasar" in result[0]["label"]
        assert "（" not in result[0]["label"]
        assert len(result[0]["bounds"]) == 4


# ─── プロキシURLマスクテスト ────────────────────
class TestMaskProxyUrl:
    """_mask_proxy_url のユニットテスト。"""

    def test_認証情報付きURLがマスクされる(self):
        """user:pass@host 形式のURLで認証部分がマスクされること。"""
        from vision_api import _mask_proxy_url
        result = _mask_proxy_url("http://user:pass@proxy.example.com:8080")
        assert "user" not in result
        assert "pass" not in result
        assert "***:***@proxy.example.com:8080" in result
        assert result.startswith("http://")

    def test_認証情報なしURLはそのまま返す(self):
        """認証情報がないURLはマスクせずそのまま返すこと。"""
        from vision_api import _mask_proxy_url
        result = _mask_proxy_url("http://proxy.example.com:8080")
        assert result == "http://proxy.example.com:8080"

    def test_空文字はそのまま返す(self):
        """空文字はそのまま返すこと。"""
        from vision_api import _mask_proxy_url
        assert _mask_proxy_url("") == ""

    def test_Noneはそのまま返す(self):
        """Noneはそのまま返すこと。"""
        from vision_api import _mask_proxy_url
        assert _mask_proxy_url(None) is None


# ─── 画像安全チェックテスト ────────────────────
class TestImageSafetyCheck:
    """preprocess_image の安全チェックがバイパスされないことのテスト。"""

    @patch("vision_api.session.post")
    @patch("vision_api.preprocess_image")
    def test_ValueError時はdetect_contentがValueErrorを伝播する(self, mock_preprocess, mock_post):
        """preprocess_imageがValueErrorを投げた場合、detect_contentも伝播すること。"""
        mock_preprocess.side_effect = ValueError("画像サイズが大きすぎます")
        from vision_api import detect_content
        with pytest.raises(ValueError, match="画像サイズが大きすぎます"):
            detect_content(make_b64(), mode="text")
        # APIは呼ばれないこと
        mock_post.assert_not_called()

    @patch("vision_api.session.post")
    @patch("vision_api.preprocess_image")
    def test_非ValueErrorの前処理エラーはスキップしてAPI呼び出しを続行する(self, mock_preprocess, mock_post):
        """前処理でValueError以外のエラーが出た場合はスキップしてAPI呼び出しを続行すること。"""
        mock_preprocess.side_effect = OSError("一時的なI/Oエラー")
        mock_post.return_value = make_mock_response(status_code=200, json_data={
            "responses": [{"textAnnotations": []}]
        })
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is True
        mock_post.assert_called_once()
