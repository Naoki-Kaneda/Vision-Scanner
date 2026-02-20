"""
vision_api.py の単体テスト。
部分エラー・タイムアウト・接続失敗・モード不正・パーサー境界ケースをカバー。
"""

import base64
import pytest
from unittest.mock import patch, MagicMock
from requests.exceptions import Timeout, ConnectionError as RequestsConnectionError, RequestException


# ─── テスト用ヘルパー ──────────────────────────────
def _make_b64(data: bytes = b"\xff\xd8\xff\xd9") -> str:
    """最小限のBase64文字列を生成する。"""
    return base64.b64encode(data).decode()


def _mock_response(status_code=200, json_data=None):
    """requests.Responseのモックを作成する。"""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data or {}
    mock.text = str(json_data)
    return mock


# ─── detect_content: モード不正値 ─────────────────
class TestDetectContentValidation:
    """detect_content のバリデーションテスト。"""

    def test_不正なmodeはValueErrorを投げる(self):
        """mode が text/object 以外は ValueError が発生すること。"""
        from vision_api import detect_content
        with pytest.raises(ValueError, match="不正なモード"):
            detect_content(_make_b64(), mode="invalid")

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
                detect_content(_make_b64(), mode="text")
        finally:
            vision_api.API_KEY = original


# ─── detect_content: HTTP エラー ──────────────────
class TestDetectContentHttpErrors:
    """HTTPレベルのエラーハンドリングテスト。"""

    @patch("vision_api.session.post")
    def test_HTTP500はokFalseを返す(self, mock_post):
        """Vision API が HTTP 500 を返した場合は ok=False を返すこと。"""
        mock_post.return_value = _mock_response(status_code=500)
        from vision_api import detect_content
        result = detect_content(_make_b64(), mode="object")
        assert result["ok"] is False
        assert result["error_code"] == "API_500"

    @patch("vision_api.session.post")
    def test_タイムアウトはokFalseを返す(self, mock_post):
        """タイムアウト発生時は ok=False, error_code=TIMEOUT を返すこと。"""
        mock_post.side_effect = Timeout()
        from vision_api import detect_content
        result = detect_content(_make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "TIMEOUT"

    @patch("vision_api.session.post")
    def test_接続エラーはokFalseを返す(self, mock_post):
        """接続失敗時は ok=False, error_code=CONNECTION_ERROR を返すこと。"""
        mock_post.side_effect = RequestsConnectionError()
        from vision_api import detect_content
        result = detect_content(_make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "CONNECTION_ERROR"

    @patch("vision_api.session.post")
    def test_その他通信エラーはokFalseを返す(self, mock_post):
        """RequestException 発生時は ok=False, error_code=REQUEST_ERROR を返すこと。"""
        mock_post.side_effect = RequestException("generic error")
        from vision_api import detect_content
        result = detect_content(_make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "REQUEST_ERROR"


# ─── detect_content: Vision API 部分エラー ────────
class TestDetectContentPartialError:
    """HTTP 200 だが responses[0].error がある場合のテスト。"""

    @patch("vision_api.session.post")
    def test_部分エラーはokFalseを返す(self, mock_post):
        """HTTP 200 でも responses[0].error があれば ok=False を返すこと。"""
        mock_post.return_value = _mock_response(status_code=200, json_data={
            "responses": [{
                "error": {
                    "code": 400,
                    "message": "Bad image data",
                }
            }]
        })
        from vision_api import detect_content
        result = detect_content(_make_b64(), mode="text")
        assert result["ok"] is False
        assert "VISION_400" in result["error_code"]
        assert "Bad image data" in result["message"]


# ─── パーサー境界ケース ───────────────────────────
class TestParsers:
    """_parse_text_response / _parse_label_response の境界ケース。"""

    def test_テキストレスポンスが空の場合空リストを返す(self):
        """textAnnotations がない場合は空リストを返すこと。"""
        from vision_api import _parse_text_response
        assert _parse_text_response({}) == []
        assert _parse_text_response({"textAnnotations": []}) == []

    def test_テキストレスポンスが空行を除外する(self):
        """空行・空白行はフィルタリングされること。"""
        from vision_api import _parse_text_response
        result = _parse_text_response({
            "textAnnotations": [{"description": "Hello\n\n  \nWorld"}]
        })
        assert result == ["Hello", "World"]

    def test_ラベルレスポンスが空の場合空リストを返す(self):
        """labelAnnotations がない場合は空リストを返すこと。"""
        from vision_api import _parse_label_response
        assert _parse_label_response({}) == []
        assert _parse_label_response({"labelAnnotations": []}) == []

    def test_ラベルに日本語訳がない場合英語のみ表示(self):
        """翻訳辞書にないラベルは英語のみで表示すること。"""
        from vision_api import _parse_label_response
        result = _parse_label_response({
            "labelAnnotations": [{"description": "Quasar", "score": 0.99}]
        })
        assert len(result) == 1
        assert "Quasar" in result[0]
        assert "（" not in result[0]  # 日本語括弧がないこと
