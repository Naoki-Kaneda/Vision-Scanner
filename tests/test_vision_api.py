"""
vision_api.py の単体テスト。
部分エラー・タイムアウト・接続失敗・モード不正・パーサー境界ケースをカバー。
"""

import pytest
from unittest.mock import patch
from requests.exceptions import Timeout, ConnectionError as RequestsConnectionError, RequestException
from tests.helpers import make_b64, make_mock_response


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

    @patch("vision_api.session.post")
    def test_JSONパース失敗はPARSE_ERRORを返す(self, mock_post):
        """Content-Type=jsonだがパース失敗時は PARSE_ERROR を返すこと。"""
        mock_resp = make_mock_response(status_code=200, content_type="application/json")
        mock_resp.json.side_effect = ValueError("No JSON object could be decoded")
        mock_resp.text = "broken json {"
        mock_post.return_value = mock_resp
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "PARSE_ERROR"
        assert "解析に失敗" in result["message"]

    @patch("vision_api.session.post")
    def test_非JSONレスポンスはAPI_RESPONSE_NOT_JSONを返す(self, mock_post):
        """Content-TypeがHTMLなど非JSON時は API_RESPONSE_NOT_JSON を返すこと。"""
        mock_resp = make_mock_response(status_code=200, content_type="text/html; charset=utf-8")
        mock_resp.json.side_effect = ValueError("No JSON object could be decoded")
        mock_resp.text = "<html>Service Unavailable</html>"
        mock_post.return_value = mock_resp
        from vision_api import detect_content
        result = detect_content(make_b64(), mode="text")
        assert result["ok"] is False
        assert result["error_code"] == "API_RESPONSE_NOT_JSON"
        assert "Content-Type" in result["message"]
        assert "text/html" in result["message"]


# ─── detect_content: Vision API 部分エラー ────────
class TestDetectContentPartialError:
    """HTTP 200 だが responses[0].error がある場合のテスト。"""

    @patch("vision_api.session.post")
    def test_部分エラーで注釈なしはokFalseを返す(self, mock_post):
        """error のみで注釈が空の場合は ok=False を返すこと。"""
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

    @patch("vision_api.session.post")
    def test_部分エラーで注釈ありはokTrueとwarningsを返す(self, mock_post):
        """error と注釈が共存する場合は ok=True + warnings を返すこと。"""
        mock_post.return_value = make_mock_response(status_code=200, json_data={
            "responses": [{
                "error": {
                    "code": 14,
                    "message": "Partial failure",
                },
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
                ],
            }]
        })
        from vision_api import detect_content
        detect_content(make_b64(), mode="object")
        # 注釈なし（objectモードなのでlocalizedObjectAnnotationsが空）→ ok=False
        # ここではtextモードで注釈ありを直接テスト
        result_text = detect_content(make_b64(), mode="text")
        assert result_text["ok"] is True
        assert "warnings" in result_text
        assert len(result_text["warnings"]) == 1
        assert "VISION_14" in result_text["warnings"][0]
        assert len(result_text["data"]) == 1  # textAnnotations[1:]


# ─── detect_content: imageContext のモード制限 ────────
class TestImageContextRestriction:
    """imageContext が text/label モードのみに付与されることのテスト。"""

    @patch("vision_api.session.post")
    def test_objectモードでpayloadにimageContextが含まれない(self, mock_post):
        """mode=object の場合、APIリクエストに imageContext が含まれないこと。"""
        mock_post.return_value = make_mock_response(status_code=200, json_data={
            "responses": [{"localizedObjectAnnotations": []}]
        })
        from vision_api import detect_content
        detect_content(make_b64(), mode="object")
        # session.post に渡された json ペイロードを取得
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        request_item = payload["requests"][0]
        assert "imageContext" not in request_item

    @patch("vision_api.session.post")
    def test_textモードでpayloadにimageContextが含まれる(self, mock_post):
        """mode=text の場合、APIリクエストに imageContext.languageHints が含まれること。"""
        mock_post.return_value = make_mock_response(status_code=200, json_data={
            "responses": [{"textAnnotations": []}]
        })
        from vision_api import detect_content
        detect_content(make_b64(), mode="text")
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        request_item = payload["requests"][0]
        assert "imageContext" in request_item
        assert "languageHints" in request_item["imageContext"]

    @patch("vision_api.session.post")
    def test_faceモードでpayloadにimageContextが含まれない(self, mock_post):
        """mode=face の場合、APIリクエストに imageContext が含まれないこと。"""
        mock_post.return_value = make_mock_response(status_code=200, json_data={
            "responses": [{"faceAnnotations": []}]
        })
        from vision_api import detect_content
        detect_content(make_b64(), mode="face")
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        request_item = payload["requests"][0]
        assert "imageContext" not in request_item


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
        # フォールバック: fullTextAnnotation がないので textAnnotations[0] から推定
        assert img_size == [100, 50]

    def test_fullTextAnnotation優先で正確な画像サイズを取得する(self):
        """fullTextAnnotation.pages[0] の width/height を優先して使用すること。"""
        from vision_api import _parse_text_response
        data, img_size = _parse_text_response({
            "textAnnotations": [
                {
                    "description": "Hello",
                    "boundingPoly": {"vertices": [
                        {"x": 10, "y": 10}, {"x": 90, "y": 10},
                        {"x": 90, "y": 40}, {"x": 10, "y": 40},
                    ]},
                },
                {
                    "description": "Hello",
                    "boundingPoly": {"vertices": [
                        {"x": 10, "y": 10}, {"x": 90, "y": 10},
                        {"x": 90, "y": 40}, {"x": 10, "y": 40},
                    ]},
                },
            ],
            "fullTextAnnotation": {
                "pages": [{"width": 640, "height": 480}],
            },
        })
        # fullTextAnnotation の値が優先される（textAnnotations[0] の 90, 40 ではなく）
        assert img_size == [640, 480]

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


# ─── get_proxy_status: 4パターン回帰テスト ──────────────
class TestGetProxyStatus:
    """NO_PROXY_MODE と PROXY_URL の組み合わせ4パターンで get_proxy_status を検証する。"""

    @patch("vision_api.NO_PROXY_MODE", False)
    @patch("vision_api._RAW_PROXY_URL", "http://proxy.example.com:8080")
    def test_プロキシURL有りでNO_PROXY_MODE無効ならenabled(self):
        """PROXY_URL設定済み + NO_PROXY_MODE=false → enabled=True。"""
        from vision_api import get_proxy_status
        status = get_proxy_status()
        assert status["enabled"] is True
        assert "proxy.example.com" in status["url"]

    @patch("vision_api.NO_PROXY_MODE", True)
    @patch("vision_api._RAW_PROXY_URL", "http://proxy.example.com:8080")
    def test_プロキシURL有りでNO_PROXY_MODE有効ならdisabled(self):
        """PROXY_URL設定済み + NO_PROXY_MODE=true → enabled=False。"""
        from vision_api import get_proxy_status
        status = get_proxy_status()
        assert status["enabled"] is False
        assert status["url"] == ""

    @patch("vision_api.NO_PROXY_MODE", False)
    @patch("vision_api._RAW_PROXY_URL", "")
    def test_プロキシURL空でNO_PROXY_MODE無効ならdisabled(self):
        """PROXY_URL未設定 + NO_PROXY_MODE=false → enabled=False。"""
        from vision_api import get_proxy_status
        status = get_proxy_status()
        assert status["enabled"] is False

    @patch("vision_api.NO_PROXY_MODE", True)
    @patch("vision_api._RAW_PROXY_URL", "")
    def test_プロキシURL空でNO_PROXY_MODE有効ならdisabled(self):
        """PROXY_URL未設定 + NO_PROXY_MODE=true → enabled=False。"""
        from vision_api import get_proxy_status
        status = get_proxy_status()
        assert status["enabled"] is False
        assert status["url"] == ""

    @patch("vision_api.NO_PROXY_MODE", False)
    @patch("vision_api._RAW_PROXY_URL", "http://user:secret@proxy.example.com:8080")
    def test_認証情報付きURLはマスクされる(self):
        """認証情報付きのPROXY_URLが get_proxy_status で漏えいしないこと。"""
        from vision_api import get_proxy_status
        status = get_proxy_status()
        assert status["enabled"] is True
        assert "secret" not in status["url"]
        assert "***:***" in status["url"]


# ─── 顔検出パーサーテスト ─────────────────────────────
class TestFaceParser:
    """_parse_face_response のテスト。"""

    def test_空レスポンスで空リストを返す(self):
        from vision_api import _parse_face_response
        assert _parse_face_response({}) == []
        assert _parse_face_response({"faceAnnotations": []}) == []

    def test_感情付き顔を正しくパースする(self):
        from vision_api import _parse_face_response
        result = _parse_face_response({
            "faceAnnotations": [{
                "boundingPoly": {"vertices": [
                    {"x": 10, "y": 10}, {"x": 100, "y": 10},
                    {"x": 100, "y": 100}, {"x": 10, "y": 100},
                ]},
                "detectionConfidence": 0.95,
                "joyLikelihood": "VERY_LIKELY",
                "sorrowLikelihood": "VERY_UNLIKELY",
                "angerLikelihood": "UNLIKELY",
                "surpriseLikelihood": "POSSIBLE",
            }]
        })
        assert len(result) == 1
        assert "喜び" in result[0]["label"]
        assert result[0]["confidence"] == 0.95
        assert len(result[0]["bounds"]) == 4
        assert result[0]["emotions"]["joy"] == "VERY_LIKELY"

    def test_fdBoundingPolyを優先する(self):
        from vision_api import _parse_face_response
        result = _parse_face_response({
            "faceAnnotations": [{
                "boundingPoly": {"vertices": [
                    {"x": 0, "y": 0}, {"x": 200, "y": 0},
                    {"x": 200, "y": 200}, {"x": 0, "y": 200},
                ]},
                "fdBoundingPoly": {"vertices": [
                    {"x": 50, "y": 50}, {"x": 150, "y": 50},
                    {"x": 150, "y": 150}, {"x": 50, "y": 150},
                ]},
                "detectionConfidence": 0.9,
                "joyLikelihood": "UNLIKELY",
                "sorrowLikelihood": "UNLIKELY",
                "angerLikelihood": "UNLIKELY",
                "surpriseLikelihood": "UNLIKELY",
            }]
        })
        assert result[0]["bounds"][0] == [50, 50]


# ─── ロゴ検出パーサーテスト ────────────────────────────
class TestLogoParser:
    """_parse_logo_response のテスト。"""

    def test_空レスポンスで空リストを返す(self):
        from vision_api import _parse_logo_response
        assert _parse_logo_response({}) == []

    def test_ロゴを正しくパースする(self):
        from vision_api import _parse_logo_response
        result = _parse_logo_response({
            "logoAnnotations": [{
                "description": "Google",
                "score": 0.95,
                "boundingPoly": {"vertices": [
                    {"x": 10, "y": 10}, {"x": 100, "y": 10},
                    {"x": 100, "y": 50}, {"x": 10, "y": 50},
                ]},
            }]
        })
        assert len(result) == 1
        assert "Google" in result[0]["label"]
        assert "95%" in result[0]["label"]
        assert len(result[0]["bounds"]) == 4


# ─── 分類タグパーサーテスト ────────────────────────────
class TestClassifyParser:
    """_parse_classify_response のテスト。"""

    def test_空レスポンスで空リストを返す(self):
        from vision_api import _parse_classify_response
        assert _parse_classify_response({}) == []

    def test_分類タグを正しくパースする(self):
        from vision_api import _parse_classify_response
        result = _parse_classify_response({
            "labelAnnotations": [
                {"description": "Laptop", "score": 0.98, "topicality": 0.98},
                {"description": "Electronics", "score": 0.92, "topicality": 0.92},
            ]
        })
        assert len(result) == 2
        assert "Laptop" in result[0]["label"]
        assert result[0]["score"] == 0.98

    def test_翻訳辞書にある場合日本語が付与される(self):
        from vision_api import _parse_classify_response
        result = _parse_classify_response({
            "labelAnnotations": [
                {"description": "Laptop", "score": 0.98, "topicality": 0.98},
            ]
        })
        assert "ノートPC" in result[0]["label"]


# ─── Web検索パーサーテスト ─────────────────────────────
class TestWebParser:
    """_parse_web_response のテスト。"""

    def test_空レスポンスで空を返す(self):
        from vision_api import _parse_web_response
        data, detail = _parse_web_response({})
        assert data == []
        assert detail["best_guess"] is None
        assert detail["entities"] == []

    def test_Web検索結果を正しくパースする(self):
        from vision_api import _parse_web_response
        data, detail = _parse_web_response({
            "webDetection": {
                "bestGuessLabels": [{"label": "torque wrench"}],
                "webEntities": [
                    {"description": "TOHNICHI", "score": 0.85},
                    {"description": "Torque wrench", "score": 0.7},
                ],
                "pagesWithMatchingImages": [
                    {"url": "https://example.com/page1", "pageTitle": "Example Page"},
                ],
                "visuallySimilarImages": [
                    {"url": "https://example.com/img1.jpg"},
                ],
            }
        })
        assert detail["best_guess"] == "torque wrench"
        assert len(detail["entities"]) == 2
        assert detail["entities"][0]["name"] == "TOHNICHI"
        assert len(detail["pages"]) == 1
        assert len(detail["similar_images"]) == 1
        assert any("torque wrench" in d["label"] for d in data)
