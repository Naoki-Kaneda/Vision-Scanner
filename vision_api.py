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
from requests.packages.urllib3.util.retry import Retry
import urllib3
from dotenv import load_dotenv
from PIL import Image, ImageEnhance

from translations import OBJECT_TRANSLATIONS

# ─── 設定 ──────────────────────────────────────
load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

API_KEY = os.getenv("VISION_API_KEY")
API_URL = f"https://vision.googleapis.com/v1/images:annotate?key={API_KEY}"
PROXY_URL = os.getenv("PROXY_URL", "")

# ─── HTTPセッション（モジュールレベルで1回だけ作成） ──────
session = requests.Session()
retry_strategy = Retry(connect=3, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# プロキシ設定
if PROXY_URL:
    session.proxies = {"http": PROXY_URL, "https": PROXY_URL}
    logger.info("プロキシ設定: %s", PROXY_URL)

# SSL検証を無効化（企業プロキシ環境向け）
session.verify = False


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
        検出結果の文字列リスト。
    """
    if not API_KEY:
        raise ValueError("APIキーが未設定です。.envファイルにVISION_API_KEYを設定してください。")

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
                "imageContext": {"languageHints": ["en"]},
            }
        ]
    }

    try:
        response = session.post(API_URL, json=payload, timeout=15)

        if response.status_code != 200:
            logger.error("APIエラー (ステータス %d): %s", response.status_code, response.text)

        response.raise_for_status()
        result = response.json()

        responses = result.get("responses", [])
        if not responses:
            return []

        if mode == "text":
            return _parse_text_response(responses[0])
        else:
            return _parse_label_response(responses[0])

    except requests.exceptions.RequestException as e:
        logger.error("Vision API通信エラー: %s", e)
        return [f"Error: {str(e)}"]


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
