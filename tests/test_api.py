"""
Vision AI Scanner - APIエンドポイントのテスト。
正常系（OCR/物体検出）、不正入力、API失敗時の4系統をカバー。
"""

import base64
import pytest
from unittest.mock import patch, MagicMock
from app import app


@pytest.fixture
def client():
    """Flaskテストクライアントを作成する。"""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ─── テスト用ヘルパー ──────────────────────────────
def create_valid_image_base64():
    """テスト用の最小限の有効なJPEG画像をBase64で返す。"""
    # 最小限の有効なJPEGバイナリ（1x1ピクセル）
    jpeg_bytes = (
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01'
        b'\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06'
        b'\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b'
        b'\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c'
        b'\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0'
        b'\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4'
        b'\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06'
        b'\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03'
        b'\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02'
        b'\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81'
        b'\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16'
        b'\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghij'
        b'stuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94'
        b'\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8'
        b'\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3'
        b'\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7'
        b'\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea'
        b'\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00'
        b'\x08\x01\x01\x00\x00?\x00T\xdb\xae\xa7\x1e\xf1R)l\xa8'
        b'\xab\xa1\xca\xff\xd9'
    )
    return base64.b64encode(jpeg_bytes).decode("utf-8")


# ─── 正常系テスト ──────────────────────────────────
class TestTextDetection:
    """テキスト抽出（OCR）の正常系テスト。"""

    @patch("app.detect_content")
    def test_テキスト抽出が正常に動作する(self, mock_detect, client):
        """有効な画像とmode=textで正常レスポンスを返すこと。"""
        mock_detect.return_value = {
            "ok": True,
            "data": ["Hello World", "12345"],
            "error_code": None,
            "message": None,
        }

        response = client.post("/api/analyze", json={
            "image": create_valid_image_base64(),
            "mode": "text",
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert len(data["data"]) == 2
        assert "Hello World" in data["data"]


class TestObjectDetection:
    """物体検出の正常系テスト。"""

    @patch("app.detect_content")
    def test_物体検出が正常に動作する(self, mock_detect, client):
        """有効な画像とmode=objectで正常レスポンスを返すこと。"""
        mock_detect.return_value = {
            "ok": True,
            "data": ["Person（人）- 95%", "Laptop（ノートPC）- 88%"],
            "error_code": None,
            "message": None,
        }

        response = client.post("/api/analyze", json={
            "image": create_valid_image_base64(),
            "mode": "object",
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert len(data["data"]) == 2


# ─── 不正入力テスト ──────────────────────────────
class TestInvalidInput:
    """不正な入力に対するバリデーションテスト。"""

    def test_JSONでないリクエストを拒否する(self, client):
        """Content-Typeがapplication/jsonでない場合は400を返すこと。"""
        response = client.post(
            "/api/analyze",
            data="not json",
            content_type="text/plain",
        )
        assert response.status_code == 400
        data = response.get_json()
        assert data["error_code"] == "INVALID_FORMAT"

    def test_画像データがないリクエストを拒否する(self, client):
        """imageフィールドがない場合は400を返すこと。"""
        response = client.post("/api/analyze", json={"mode": "text"})
        assert response.status_code == 400
        data = response.get_json()
        assert data["error_code"] == "MISSING_IMAGE"

    def test_不正なモードを拒否する(self, client):
        """mode が text/object 以外の場合は400を返すこと。"""
        response = client.post("/api/analyze", json={
            "image": create_valid_image_base64(),
            "mode": "invalid",
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data["error_code"] == "INVALID_MODE"

    def test_不正なBase64を拒否する(self, client):
        """Base64デコードに失敗する文字列は400を返すこと。"""
        response = client.post("/api/analyze", json={
            "image": "!!!not-valid-base64!!!",
            "mode": "text",
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data["error_code"] == "INVALID_BASE64"

    def test_大きすぎる画像を拒否する(self, client):
        """5MBを超える画像は400を返すこと。"""
        # 6MBのダミーデータ
        large_image = base64.b64encode(b"\xff" * (6 * 1024 * 1024)).decode("utf-8")
        response = client.post("/api/analyze", json={
            "image": large_image,
            "mode": "text",
        })
        assert response.status_code == 400
        data = response.get_json()
        assert data["error_code"] == "IMAGE_TOO_LARGE"

    def test_Nullの画像を拒否する(self, client):
        """imageフィールドがnullの場合は400を返すこと。"""
        response = client.post("/api/analyze", json={
            "image": None,
            "mode": "text",
        })
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "MISSING_IMAGE"

    def test_空文字の画像を拒否する(self, client):
        """imageフィールドが空文字の場合は400を返すこと。"""
        response = client.post("/api/analyze", json={
            "image": "   ",
            "mode": "text",
        })
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "MISSING_IMAGE"


# ─── API失敗時テスト ──────────────────────────────
class TestApiFailure:
    """Vision APIの障害時の動作テスト。"""

    @patch("app.detect_content")
    def test_API障害時にエラーレスポンスを返す(self, mock_detect, client):
        """detect_contentがエラーを返した場合、502を返すこと。"""
        mock_detect.return_value = {
            "ok": False,
            "data": [],
            "error_code": "API_500",
            "message": "Vision APIエラー",
        }

        response = client.post("/api/analyze", json={
            "image": create_valid_image_base64(),
            "mode": "text",
        })

        assert response.status_code == 502
        data = response.get_json()
        assert data["ok"] is False
        assert data["error_code"] == "API_500"

    @patch("app.detect_content")
    def test_サーバー例外時に500を返す(self, mock_detect, client):
        """予期しない例外発生時は500を返すこと。"""
        mock_detect.side_effect = RuntimeError("予期しないエラー")

        response = client.post("/api/analyze", json={
            "image": create_valid_image_base64(),
            "mode": "text",
        })

        assert response.status_code == 500
        data = response.get_json()
        assert data["ok"] is False
        assert data["error_code"] == "SERVER_ERROR"
