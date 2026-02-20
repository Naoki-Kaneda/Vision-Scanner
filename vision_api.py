"""
Vision API モジュール。
Google Cloud Vision APIを使用してテキスト抽出（OCR）と物体検出を行う。
"""

import os
import io
import base64
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from dotenv import load_dotenv
from PIL import Image, ImageEnhance

from translations import OBJECT_TRANSLATIONS

# ─── 設定 ──────────────────────────────────────
load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("VISION_API_KEY")
# URLはdetect_content内で構築する（起動時にキーがなくてもNoneStrが埋まる問題を回避）
API_BASE_URL = "https://vision.googleapis.com/v1/images:annotate"

# プロキシ設定（NO_PROXY_MODE=trueなら初期状態でプロキシを無視）
NO_PROXY_MODE = os.getenv("NO_PROXY_MODE", "false").lower() == "true"
_RAW_PROXY_URL = os.getenv("PROXY_URL", "")


def _get_active_proxy_config():
    """現在の設定に基づいてプロキシ辞書を生成する"""
    if NO_PROXY_MODE or not _RAW_PROXY_URL:
        return {}
    return {"http": _RAW_PROXY_URL, "https": _RAW_PROXY_URL}


VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() != "false"

# 許可されるモード値
VALID_MODES = {"text", "object"}

# SSL検証無効時のみ警告を抑制
if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    logger.warning("⚠ SSL検証が無効化されています。本番環境では VERIFY_SSL=true を推奨します。")

if NO_PROXY_MODE:
    logger.info("ℹ️ NO_PROXY_MODE: プロキシ設定を無視します。")

# ─── HTTPセッション（モジュールレベルで1回だけ作成） ──────
session = requests.Session()
# connectリトライ + HTTPエラーコードの再試行
retry_strategy = Retry(
    total=3,
    connect=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503],
    allowed_methods=["POST"],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# 初期プロキシ設定適用
session.proxies = _get_active_proxy_config()
if session.proxies:
    logger.info("プロキシ設定: %s", _RAW_PROXY_URL)


# ─── プロキシ設定API ─────────────────────────────
def get_proxy_status():
    """現在のプロキシ設定状態を返す"""
    return {
        "enabled": not NO_PROXY_MODE and bool(_RAW_PROXY_URL),
        "url": _RAW_PROXY_URL if not NO_PROXY_MODE else "",
        "configured_url": _RAW_PROXY_URL
    }


def set_proxy_enabled(enabled: bool):
    """
    プロキシの有効/無効を切り替える
    Args:
        enabled (bool): Trueならプロキシ有効（PROXY_URLを使用）、Falseなら無効
    """
    global NO_PROXY_MODE
    NO_PROXY_MODE = not enabled
    
    config = _get_active_proxy_config()
    session.proxies = config
    
    status = "有効" if enabled else "無効"
    logger.info("プロキシ設定を変更しました: %s", status)
    return get_proxy_status()

# SSL検証設定
session.verify = VERIFY_SSL


# ─── 画像前処理 ──────────────────────────────────
def preprocess_image(image_base64):
    """
    OCR精度向上のため画像の前処理を行う。
    コントラストとシャープネスを軽く強調する。

    Args:
        image_base64: Base64エンコードされた画像文字列。

    Returns:
        前処理済みのBase64エンコード画像文字列。
    """
    image_bytes = base64.b64decode(image_base64)
    img = Image.open(io.BytesIO(image_bytes))

    # 画像展開爆弾対策: ピクセル数が大きすぎる場合は前処理をスキップ
    max_pixels = 20_000_000  # 2000万ピクセル（約80MB RAM）
    if img.width * img.height > max_pixels:
        raise ValueError(f"画像サイズが大きすぎます: {img.width}x{img.height}")

    # RGBA/CMYK等のモードをRGBに変換（JPEG保存に必要）
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # コントラストを少し強調
    img = ImageEnhance.Contrast(img).enhance(1.5)

    # シャープネスを少し強調（文字の輪郭を明確に）
    img = ImageEnhance.Sharpness(img).enhance(1.5)

    # JPEG形式で高画質保存
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ─── API呼び出し ──────────────────────────────────
def detect_content(image_content_base64, mode="text"):
    """
    Google Cloud Vision APIで画像解析を行う。

    Args:
        image_content_base64: Base64エンコードされた画像文字列。
        mode: 'text'（テキスト抽出）または 'object'（物体検出）。

    Returns:
        dict: {"ok": bool, "data": list, "error_code": str|None, "message": str|None}

    Raises:
        ValueError: modeが不正な場合、またはAPIキー未設定の場合。
    """
    if not API_KEY:
        raise ValueError("APIキーが未設定です。.envファイルにVISION_API_KEYを設定してください。")

    api_url = f"{API_BASE_URL}?key={API_KEY}"

    if mode not in VALID_MODES:
        raise ValueError(f"不正なモード: '{mode}'。許可値: {VALID_MODES}")

    # DOCUMENT_TEXT_DETECTIONはTEXT_DETECTIONより高精度
    feature_type = "DOCUMENT_TEXT_DETECTION" if mode == "text" else "LABEL_DETECTION"

    # テキストモードの場合のみ前処理を適用
    if mode == "text":
        try:
            image_content_base64 = preprocess_image(image_content_base64)
        except Exception as e:
            logger.warning("前処理をスキップ: %s", e)

    # APIリクエストペイロード
    payload = {
        "requests": [
            {
                "image": {"content": image_content_base64},
                "features": [{"type": feature_type, "maxResults": 10}],
                "imageContext": {"languageHints": ["en", "ja"]},
            }
        ]
    }

    try:
        response = session.post(api_url, json=payload, timeout=15)

        if response.status_code != 200:
            logger.error("APIエラー (ステータス %d): %s", response.status_code, response.text)
            return {
                "ok": False,
                "data": [],
                "error_code": f"API_{response.status_code}",
                "message": f"Vision APIエラー (ステータス {response.status_code})",
            }

        result = response.json()
        responses = result.get("responses", [])
        if not responses:
            return {"ok": True, "data": [], "error_code": None, "message": None}

        # HTTP 200 でも responses[0] 内部にエラーが入る場合がある（Vision API の仕様）
        response_item = responses[0]
        partial_error = response_item.get("error")
        if partial_error:
            code = partial_error.get("code", "UNKNOWN")
            msg = partial_error.get("message", "Vision API 内部エラー")
            logger.error("Vision API 部分エラー (code=%s): %s", code, msg)
            return {
                "ok": False,
                "data": [],
                "error_code": f"VISION_{code}",
                "message": msg,
            }

        if mode == "text":
            data = _parse_text_response(response_item)
        else:
            data = _parse_label_response(response_item)

        return {"ok": True, "data": data, "error_code": None, "message": None}

    except requests.exceptions.Timeout:
        logger.error("Vision API タイムアウト")
        return {"ok": False, "data": [], "error_code": "TIMEOUT", "message": "APIリクエストがタイムアウトしました"}
    except requests.exceptions.ConnectionError as e:
        logger.error("Vision API 接続エラー: %s", e)
        return {"ok": False, "data": [], "error_code": "CONNECTION_ERROR", "message": "API接続に失敗しました"}
    except requests.exceptions.RequestException as e:
        logger.error("Vision API通信エラー: %s", e)
        return {"ok": False, "data": [], "error_code": "REQUEST_ERROR", "message": str(e)}


# ─── レスポンス解析（内部関数） ──────────────────────
def _parse_text_response(response_data):
    """テキスト検出レスポンスを解析して行ごとのリストを返す。"""
    text_annotations = response_data.get("textAnnotations", [])
    if not text_annotations:
        return []
    full_text = text_annotations[0].get("description", "")
    return [line for line in full_text.split("\n") if line.strip()]


def _parse_label_response(response_data):
    """ラベル検出レスポンスを解析して日本語併記のリストを返す。"""
    label_annotations = response_data.get("labelAnnotations", [])
    results = []
    for label in label_annotations:
        en_name = label.get("description", "")
        score = label.get("score", 0)
        ja_name = OBJECT_TRANSLATIONS.get(en_name.lower(), "")
        if ja_name:
            results.append(f"{en_name}（{ja_name}）- {score:.0%}")
        else:
            results.append(f"{en_name} - {score:.0%}")
    return results
