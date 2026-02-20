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

# ─── Vision API パラメータ ─────────────────────────
FEATURE_TYPES = {
    "text": "DOCUMENT_TEXT_DETECTION",   # TEXT_DETECTIONより高精度
    "object": "OBJECT_LOCALIZATION",     # 座標付き物体検出（バウンディングボックス対応）
}
MAX_RESULTS = 10               # APIが返す最大結果数
LANGUAGE_HINTS = ["en", "ja"]  # OCR言語ヒント（優先順）
API_TIMEOUT_SECONDS = 15       # APIリクエストタイムアウト（秒）

# ─── 画像前処理パラメータ ───────────────────────────
MAX_IMAGE_PIXELS = 20_000_000  # 最大ピクセル数（約80MB RAM相当）
CONTRAST_FACTOR = 1.5          # コントラスト強調係数
SHARPNESS_FACTOR = 1.5         # シャープネス強調係数（文字の輪郭を明確に）
JPEG_QUALITY = 95              # JPEG保存品質

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

    # 画像展開爆弾対策: ピクセル数が大きすぎる場合は拒否
    if img.width * img.height > MAX_IMAGE_PIXELS:
        raise ValueError(f"画像サイズが大きすぎます: {img.width}x{img.height}")

    # RGBA/CMYK等のモードをRGBに変換（JPEG保存に必要）
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # コントラスト・シャープネスを強調（OCR精度向上）
    img = ImageEnhance.Contrast(img).enhance(CONTRAST_FACTOR)
    img = ImageEnhance.Sharpness(img).enhance(SHARPNESS_FACTOR)

    # JPEG形式で高画質保存
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ─── API呼び出し ──────────────────────────────────
def detect_content(image_b64, mode="text"):
    """
    Google Cloud Vision APIで画像解析を行う。

    Args:
        image_b64: Base64エンコードされた画像文字列。
        mode: 'text'（テキスト抽出）または 'object'（物体検出）。

    Returns:
        dict: {
            "ok": bool,
            "data": list[dict],  # [{"label": str, "bounds": [[x,y],...]}, ...]
            "image_size": [w, h] | None,  # テキストモードのみ（ピクセル座標の基準）
            "error_code": str|None,
            "message": str|None,
        }

    Raises:
        ValueError: modeが不正な場合、またはAPIキー未設定の場合。
    """
    if not API_KEY:
        raise ValueError("APIキーが未設定です。.envファイルにVISION_API_KEYを設定してください。")

    if mode not in VALID_MODES:
        raise ValueError(f"不正なモード: '{mode}'。許可値: {VALID_MODES}")

    api_url = f"{API_BASE_URL}?key={API_KEY}"
    feature_type = FEATURE_TYPES[mode]

    # テキストモードの場合のみ前処理を適用
    if mode == "text":
        try:
            image_b64 = preprocess_image(image_b64)
        except Exception as e:
            logger.warning("前処理をスキップ: %s", e)

    # APIリクエストペイロード
    payload = {
        "requests": [
            {
                "image": {"content": image_b64},
                "features": [{"type": feature_type, "maxResults": MAX_RESULTS}],
                "imageContext": {"languageHints": LANGUAGE_HINTS},
            }
        ]
    }

    try:
        response = session.post(api_url, json=payload, timeout=API_TIMEOUT_SECONDS)

        if response.status_code != 200:
            logger.error("APIエラー (ステータス %d): %s", response.status_code, response.text)
            return {
                "ok": False,
                "data": [],
                "image_size": None,
                "error_code": f"API_{response.status_code}",
                "message": f"Vision APIエラー (ステータス {response.status_code})",
            }

        result = response.json()
        responses = result.get("responses", [])
        if not responses:
            return {"ok": True, "data": [], "image_size": None, "error_code": None, "message": None}

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
                "image_size": None,
                "error_code": f"VISION_{code}",
                "message": msg,
            }

        if mode == "text":
            data, image_size = _parse_text_response(response_item)
        else:
            data = _parse_object_response(response_item)
            image_size = None  # 物体モードは正規化座標（0〜1）を使用

        return {"ok": True, "data": data, "image_size": image_size, "error_code": None, "message": None}

    except requests.exceptions.Timeout:
        logger.error("Vision API タイムアウト")
        return {"ok": False, "data": [], "image_size": None, "error_code": "TIMEOUT", "message": "APIリクエストがタイムアウトしました"}
    except requests.exceptions.ConnectionError as e:
        logger.error("Vision API 接続エラー: %s", e)
        return {"ok": False, "data": [], "image_size": None, "error_code": "CONNECTION_ERROR", "message": "API接続に失敗しました"}
    except requests.exceptions.RequestException as e:
        logger.error("Vision API通信エラー: %s", e)
        return {"ok": False, "data": [], "image_size": None, "error_code": "REQUEST_ERROR", "message": str(e)}


# ─── レスポンス解析（内部関数） ──────────────────────
def _parse_text_response(response_data):
    """
    テキスト検出レスポンスを解析する。
    各テキストブロックのラベルとバウンディングボックス座標を返す。

    Returns:
        tuple: (data_list, image_size)
            data_list: [{"label": str, "bounds": [[x,y], ...]}, ...]
            image_size: [width, height] ピクセル座標の基準サイズ
    """
    text_annotations = response_data.get("textAnnotations", [])
    if not text_annotations:
        return [], None

    # 画像サイズを最初のアノテーション（フルテキスト）の座標から推定
    full_bounds = text_annotations[0].get("boundingPoly", {}).get("vertices", [])
    if full_bounds:
        max_x = max(v.get("x", 0) for v in full_bounds)
        max_y = max(v.get("y", 0) for v in full_bounds)
        image_size = [max_x, max_y]
    else:
        image_size = None

    # textAnnotations[1:] が個別の単語/ブロック（座標付き）
    results = []
    for annotation in text_annotations[1:]:
        text = annotation.get("description", "").strip()
        if not text:
            continue
        vertices = annotation.get("boundingPoly", {}).get("vertices", [])
        bounds = [[v.get("x", 0), v.get("y", 0)] for v in vertices] if vertices else []
        results.append({"label": text, "bounds": bounds})

    return results, image_size


def _parse_object_response(response_data):
    """
    物体検出（OBJECT_LOCALIZATION）レスポンスを解析する。
    各物体のラベルと正規化バウンディングボックス座標（0〜1）を返す。

    Returns:
        list: [{"label": str, "bounds": [[x,y], ...]}, ...]
    """
    objects = response_data.get("localizedObjectAnnotations", [])
    results = []
    for obj in objects:
        en_name = obj.get("name", "")
        score = obj.get("score", 0)
        ja_name = OBJECT_TRANSLATIONS.get(en_name.lower(), "")

        if ja_name:
            label = f"{en_name}（{ja_name}）- {score:.0%}"
        else:
            label = f"{en_name} - {score:.0%}"

        # normalizedVertices は 0〜1 の正規化座標
        vertices = obj.get("boundingPoly", {}).get("normalizedVertices", [])
        bounds = [[v.get("x", 0), v.get("y", 0)] for v in vertices] if vertices else []

        results.append({"label": label, "bounds": bounds})

    return results
