"""
Vision API モジュール。
Google Cloud Vision APIを使用してテキスト抽出（OCR）と物体検出を行う。
"""

from __future__ import annotations

import os
import io
import base64
import logging
from threading import Lock
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from dotenv import load_dotenv
from PIL import Image, ImageEnhance

from vision_types import (
    BoundingBox,
    ClassifyDataItem,
    DataItem,
    FaceDataItem,
    ProxyStatus,
    TextDataItem,
    TranslationDict,
    VisionErrorResponse,
    VisionResponse,
    VisionSuccessResponse,
    WebDataItem,
    WebDetail,
    WebEntity,
    WebPage,
)
from translations import (
    OBJECT_TRANSLATIONS,
    EMOTION_LIKELIHOOD,
    EMOTION_NAMES,
    LABEL_TRANSLATIONS,
)

# ─── 設定 ──────────────────────────────────────
# 単体テスト時にもenvが確実に読まれるよう、各モジュールでも呼ぶ（冪等）
load_dotenv()

logger = logging.getLogger(__name__)

API_KEY = os.getenv("VISION_API_KEY")
API_BASE_URL = "https://vision.googleapis.com/v1/images:annotate"

# プロキシ設定（NO_PROXY_MODE=trueなら初期状態でプロキシを無視）
NO_PROXY_MODE = os.getenv("NO_PROXY_MODE", "false").lower() == "true"
_RAW_PROXY_URL = os.getenv("PROXY_URL", "")


def _get_active_proxy_config() -> dict[str, str]:
    """現在の設定に基づいてプロキシ辞書を生成する"""
    if NO_PROXY_MODE or not _RAW_PROXY_URL:
        return {}
    return {"http": _RAW_PROXY_URL, "https": _RAW_PROXY_URL}


def _mask_proxy_url(url: str | None) -> str | None:
    """プロキシURLの認証情報をマスクする（例: http://user:pass@host → http://***:***@host）"""
    if not url or "@" not in url:
        return url
    scheme_end = url.find("://")
    if scheme_end == -1:
        return "***"
    at_pos = url.index("@")
    return url[:scheme_end + 3] + "***:***" + url[at_pos:]


VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() != "false"

# 許可されるモード値
VALID_MODES = {"text", "object", "label", "face", "logo", "classify", "web"}

# ─── Vision API パラメータ ─────────────────────────
FEATURE_TYPES = {
    "text": "DOCUMENT_TEXT_DETECTION",   # TEXT_DETECTIONより高精度
    "object": "OBJECT_LOCALIZATION",     # 座標付き物体検出（バウンディングボックス対応）
    "face": "FACE_DETECTION",            # 顔検出・感情分析
    "logo": "LOGO_DETECTION",            # ロゴ（ブランド）検出
    "classify": "LABEL_DETECTION",       # 画像分類タグ
    "web": "WEB_DETECTION",              # Web類似画像検索
}
MAX_RESULTS = 10               # APIが返す最大結果数

# ラベルモードで「ラベルあり」と判定する物体検出キーワード
LABEL_OBJECT_KEYWORDS = {
    "label", "sticker", "tag", "barcode", "qr code",
    "text", "number", "logo", "sign", "ticket", "badge",
    "packaging", "receipt", "document", "paper", "card",
    "banner", "poster", "envelope", "stamp",
}
LANGUAGE_HINTS = ["en", "ja"]  # OCR言語ヒント（優先順）
API_TIMEOUT_SECONDS = 15       # APIリクエストタイムアウト（秒）

# ─── エラーコード定数（タイポ防止） ─────────────────────
ERR_TIMEOUT = "TIMEOUT"
ERR_CONNECTION_ERROR = "CONNECTION_ERROR"
ERR_REQUEST_ERROR = "REQUEST_ERROR"
ERR_PARSE_ERROR = "PARSE_ERROR"
ERR_API_RESPONSE_NOT_JSON = "API_RESPONSE_NOT_JSON"

# ─── 画像前処理パラメータ ───────────────────────────
MAX_IMAGE_PIXELS = 20_000_000  # 最大ピクセル数（約80MB RAM相当）
CONTRAST_FACTOR = 1.5          # コントラスト強調係数
SHARPNESS_FACTOR = 1.5         # シャープネス強調係数（文字の輪郭を明確に）
JPEG_QUALITY = 95              # JPEG保存品質


# ─── 共通ユーティリティ ────────────────────────────
def _extract_bounds(poly_dict: dict[str, Any], coord_key: str = "vertices") -> BoundingBox:
    """boundingPolyの頂点座標を [[x, y], ...] 形式で抽出する。"""
    vertices = poly_dict.get(coord_key, [])
    return [[v.get("x", 0), v.get("y", 0)] for v in vertices] if vertices else []


def _build_label_with_translation(en_name: str, score: float, translation_dict: TranslationDict) -> str:
    """英語名・スコア・翻訳辞書からラベル文字列を生成する。"""
    ja_name = translation_dict.get(en_name.lower(), "")
    if ja_name:
        return f"{en_name}（{ja_name}）- {score:.0%}"
    return f"{en_name} - {score:.0%}"


# ─── レスポンスビルダー（辞書構築の一元化） ───────────────
def _make_success(data: list[DataItem], image_size: list[int] | None = None, warnings: list[str] | None = None, **extra: Any) -> VisionSuccessResponse:
    """成功レスポンス辞書を生成する。warningsがあれば部分成功として併記。"""
    result = {"ok": True, "data": data, "image_size": image_size,
              "error_code": None, "message": None, **extra}
    if warnings:
        result["warnings"] = warnings
    return result  # type: ignore[return-value]


def _make_error(error_code: str, message: str) -> VisionErrorResponse:
    """失敗レスポンス辞書を生成する。"""
    return {"ok": False, "data": [], "image_size": None,
            "error_code": error_code, "message": message}


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
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["POST"],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# 初期プロキシ設定適用
session.proxies = _get_active_proxy_config()
if session.proxies:
    logger.info("プロキシ設定: %s", _mask_proxy_url(_RAW_PROXY_URL))


# ─── プロキシ設定API ─────────────────────────────
_proxy_lock = Lock()


def get_proxy_status() -> ProxyStatus:
    """現在のプロキシ設定状態を返す（認証情報はマスク）"""
    return {
        "enabled": not NO_PROXY_MODE and bool(_RAW_PROXY_URL),
        "url": (_mask_proxy_url(_RAW_PROXY_URL) or "") if not NO_PROXY_MODE else "",
    }


def set_proxy_enabled(enabled: bool) -> ProxyStatus:
    """
    プロキシの有効/無効を切り替える（スレッド安全）。
    変更はロックで保護され、グローバル状態とセッション設定を原子的に更新する。
    Args:
        enabled (bool): Trueならプロキシ有効（PROXY_URLを使用）、Falseなら無効
    """
    global NO_PROXY_MODE
    with _proxy_lock:
        NO_PROXY_MODE = not enabled
        session.proxies = _get_active_proxy_config()

    status = "有効" if enabled else "無効"
    logger.info("プロキシ設定を変更しました: %s", status)
    return get_proxy_status()

# SSL検証設定
session.verify = VERIFY_SSL


# ─── 画像寸法取得 ─────────────────────────────────
def _get_image_dimensions(image_b64: str) -> list[int] | None:
    """
    Base64画像のピクセル寸法を取得する（デコードのみ、画像加工なし）。
    顔検出・ロゴ検出モードでバウンディングボックスの座標正規化に使用。

    Args:
        image_b64: Base64エンコードされた画像文字列。

    Returns:
        [width, height] または None（取得失敗時）
    """
    try:
        image_bytes = base64.b64decode(image_b64)
        with Image.open(io.BytesIO(image_bytes)) as img:
            return [img.width, img.height]
    except Exception:
        return None


# ─── 画像前処理 ──────────────────────────────────
def preprocess_image(image_base64: str) -> str:
    """
    OCR精度向上のため画像の前処理を行う。
    コントラストとシャープネスを軽く強調する。

    Args:
        image_base64: Base64エンコードされた画像文字列。

    Returns:
        前処理済みのBase64エンコード画像文字列。
    """
    image_bytes = base64.b64decode(image_base64)
    with Image.open(io.BytesIO(image_bytes)) as img:
        # 画像展開爆弾対策: ピクセル数が大きすぎる場合は拒否
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise ValueError(f"画像サイズが大きすぎます: {img.width}x{img.height}")

        # RGBA/CMYK等のモードをRGBに変換（JPEG保存に必要）
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")  # type: ignore[assignment]

        # コントラスト・シャープネスを強調（OCR精度向上）
        img = ImageEnhance.Contrast(img).enhance(CONTRAST_FACTOR)  # type: ignore[assignment]
        img = ImageEnhance.Sharpness(img).enhance(SHARPNESS_FACTOR)  # type: ignore[assignment]

        # JPEG形式で高画質保存
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ─── ペイロード構築 ─────────────────────────────────
def _build_request_payload(image_b64: str, mode: str, features: list[dict[str, Any]]) -> dict[str, Any]:
    """APIリクエストのペイロードを組み立てる。"""
    request_item = {
        "image": {"content": image_b64},
        "features": features,
    }
    # languageHints はテキスト検出向け仕様のため、text/label モードのみ付与する
    if mode in ("text", "label"):
        request_item["imageContext"] = {"languageHints": LANGUAGE_HINTS}
    return {"requests": [request_item]}


# ─── API通信 ──────────────────────────────────────
def _call_vision_api(payload: dict[str, Any], request_id: str, mode: str) -> VisionResponse | dict[str, Any]:
    """
    Vision API を呼び出し、responses[0] の辞書を返す。
    通信エラー・HTTPエラー・パースエラー時は _make_error 辞書を返す。
    レスポンスが空の場合は _make_success([]) を返す。
    """
    try:
        api_headers = {"x-goog-api-key": API_KEY}
        response = session.post(API_BASE_URL, json=payload, headers=api_headers, timeout=API_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        logger.error("[%s] Vision API タイムアウト (mode=%s)", request_id, mode)
        return _make_error(ERR_TIMEOUT, "APIリクエストがタイムアウトしました")
    except requests.exceptions.ConnectionError as e:
        logger.error("[%s] Vision API 接続エラー (mode=%s): %s", request_id, mode, e)
        return _make_error(ERR_CONNECTION_ERROR, "API接続に失敗しました")
    except requests.exceptions.RequestException as e:
        logger.error("[%s] Vision API通信エラー (mode=%s): %s", request_id, mode, e)
        return _make_error(ERR_REQUEST_ERROR, str(e))

    if response.status_code != 200:
        logger.error("[%s] APIエラー (mode=%s, ステータス %d): %.500s", request_id, mode, response.status_code, response.text)
        return _make_error(f"API_{response.status_code}", f"Vision APIエラー (ステータス {response.status_code})")

    try:
        result = response.json()
    except (ValueError, TypeError) as parse_err:
        content_type = response.headers.get("Content-Type", "不明")
        logger.error("[%s] APIレスポンスのJSONパースに失敗 (mode=%s, content-type=%s): %s (先頭200文字: %.200s)",
                     request_id, mode, content_type, parse_err, response.text)
        error_code = ERR_API_RESPONSE_NOT_JSON if "json" not in content_type.lower() else ERR_PARSE_ERROR
        return _make_error(error_code, f"APIレスポンスの解析に失敗しました (Content-Type: {content_type})")

    responses = result.get("responses", [])
    logger.info("Vision API レスポンス keys: %s", list(responses[0].keys()) if responses else "empty")
    if not responses:
        return _make_success([])

    return responses[0]  # type: ignore[no-any-return]


# ─── 部分エラー判定 ─────────────────────────────────
def _check_partial_error(response_item: dict[str, Any], request_id: str, mode: str) -> tuple[list[str] | None, str | None, str | None]:
    """
    responses[0].error を検査し、部分エラー情報を返す。

    Returns:
        tuple: (partial_warnings, error_code, error_msg)
            部分エラーなしの場合は (None, None, None)。
    """
    partial_error = response_item.get("error")
    if not partial_error:
        return None, None, None
    code = partial_error.get("code", "UNKNOWN")
    msg = partial_error.get("message", "Vision API 内部エラー")
    logger.warning("[%s] Vision API 部分エラー (mode=%s, code=%s): %s", request_id, mode, code, msg)
    return [f"VISION_{code}: {msg}"], f"VISION_{code}", msg


def _partial_error_or_success(data: list[DataItem], partial_warnings: list[str] | None, error_code: str | None, error_msg: str | None,
                              image_size: list[int] | None = None, **extra: Any) -> VisionResponse:
    """部分エラーあり + 注釈データなし → 完全失敗、それ以外は成功を返す。"""
    if partial_warnings and not data:
        return _make_error(error_code or "", error_msg or "")
    return _make_success(data, image_size, warnings=partial_warnings, **extra)


# ─── モード別パース分岐 ──────────────────────────────
def _dispatch_parse(mode: str, response_item: dict[str, Any], image_b64: str) -> tuple[list[DataItem], list[int] | None, dict[str, Any]]:
    """
    モードに応じてレスポンスをパースし、(data, image_size, extra_kwargs) を返す。
    extra_kwargs はモード固有フィールド（label_detected, web_detail等）。
    """
    if mode == "text":
        text_data, image_size = _parse_text_response(response_item)
        logger.info("テキスト検出結果: %d件, image_size=%s", len(text_data), image_size)
        return text_data, image_size, {}  # type: ignore[return-value]

    if mode == "label":
        label_data, image_size, label_detected, label_reason = _parse_label_response(response_item)
        logger.info("ラベル検出結果: detected=%s, reason=%s", label_detected, label_reason)
        return label_data, image_size, {"label_detected": label_detected, "label_reason": label_reason}  # type: ignore[return-value]

    if mode == "face":
        image_size = _get_image_dimensions(image_b64)
        face_data = _parse_face_response(response_item)
        logger.info("顔検出結果: %d件, image_size=%s", len(face_data), image_size)
        return face_data, image_size, {}  # type: ignore[return-value]

    if mode == "logo":
        image_size = _get_image_dimensions(image_b64)
        logo_data = _parse_logo_response(response_item)
        logger.info("ロゴ検出結果: %d件, image_size=%s", len(logo_data), image_size)
        return logo_data, image_size, {}  # type: ignore[return-value]

    if mode == "classify":
        classify_data = _parse_classify_response(response_item)
        logger.info("分類タグ結果: %d件", len(classify_data))
        return classify_data, None, {}  # type: ignore[return-value]

    if mode == "web":
        web_data, web_detail = _parse_web_response(response_item)
        logger.info("Web検索結果: entities=%d件", len(web_detail.get("entities", [])))
        return web_data, None, {"web_detail": web_detail}

    # object モード
    obj_data = _parse_object_response(response_item)
    logger.info("物体検出結果: %d件", len(obj_data))
    return obj_data, None, {}  # type: ignore[return-value]


# ─── API呼び出し（公開エントリーポイント） ───────────────
def detect_content(image_b64: str, mode: str = "text", request_id: str = "") -> VisionResponse:
    """
    Google Cloud Vision APIで画像解析を行う。

    Args:
        image_b64: Base64エンコードされた画像文字列。
        mode: 検出モード（text/object/label/face/logo/classify/web）。
        request_id: リクエスト相関ID（ログ追跡用、省略可）。

    Returns:
        dict: {"ok": bool, "data": list, "image_size": ..., "error_code": ..., "message": ...}
            モード固有: label_detected, label_reason (label) / web_detail (web)
            部分成功時: warnings リスト

    Raises:
        ValueError: modeが不正な場合、またはAPIキー未設定の場合。
    """
    if not API_KEY:
        raise ValueError("APIキーが未設定です。.envファイルにVISION_API_KEYを設定してください。")
    if mode not in VALID_MODES:
        raise ValueError(f"不正なモード: '{mode}'。許可値: {VALID_MODES}")

    # features 構築
    if mode == "label":
        features = [
            {"type": "DOCUMENT_TEXT_DETECTION", "maxResults": MAX_RESULTS},
            {"type": "OBJECT_LOCALIZATION", "maxResults": MAX_RESULTS},
        ]
    else:
        features = [{"type": FEATURE_TYPES[mode], "maxResults": MAX_RESULTS}]

    # 前処理（テキスト系モードのみ）
    if mode in ("text", "label"):
        try:
            image_b64 = preprocess_image(image_b64)
        except ValueError:
            raise
        except Exception as e:
            logger.warning("前処理をスキップ（画像強調のみ省略）: %s", e)

    # API呼び出し
    payload = _build_request_payload(image_b64, mode, features)
    api_result = _call_vision_api(payload, request_id, mode)

    # _call_vision_api がエラー辞書や空成功を返した場合はそのまま返却
    if isinstance(api_result, dict) and "ok" in api_result:
        return api_result  # type: ignore[return-value]

    # パース分岐 + 部分エラー判定
    response_item = api_result
    partial_warnings, err_code, err_msg = _check_partial_error(response_item, request_id, mode)
    data, image_size, extra = _dispatch_parse(mode, response_item, image_b64)
    return _partial_error_or_success(data, partial_warnings, err_code, err_msg,
                                     image_size=image_size, **extra)


# ─── レスポンス解析（内部関数） ──────────────────────
def _parse_text_response(response_data: dict[str, Any]) -> tuple[list[TextDataItem], list[int] | None]:
    """
    テキスト検出レスポンスを解析する。
    各テキストブロックのラベルとバウンディングボックス座標を返す。

    Returns:
        tuple: (data_list, image_size)
            data_list: [{"label": str, "bounds": [[x,y], ...]}, ...]
            image_size: [width, height] ピクセル座標の基準サイズ
    """
    text_annotations = response_data.get("textAnnotations", [])
    logger.info("textAnnotations件数: %d", len(text_annotations))
    if text_annotations:
        full_text = text_annotations[0].get("description", "")
        from pii_mask import mask_pii
        logger.info("OCR全文テキスト（先頭100文字）: %s", mask_pii(full_text[:100]))
    if not text_annotations:
        return [], None

    # 画像サイズ取得: fullTextAnnotation.pages[0] が正確（APIが返す実画像寸法）
    image_size = None
    pages = response_data.get("fullTextAnnotation", {}).get("pages", [])
    if pages:
        page = pages[0]
        pw = page.get("width", 0)
        ph = page.get("height", 0)
        if pw > 0 and ph > 0:
            image_size = [pw, ph]

    # フォールバック: fullTextAnnotation がない場合は最初のアノテーション座標から推定
    if image_size is None:
        full_bounds = text_annotations[0].get("boundingPoly", {}).get("vertices", [])
        if full_bounds:
            max_x = max(v.get("x", 0) for v in full_bounds)
            max_y = max(v.get("y", 0) for v in full_bounds)
            if max_x > 0 and max_y > 0:
                image_size = [max_x, max_y]

    # textAnnotations[1:] が個別の単語/ブロック（座標付き）
    results: list[TextDataItem] = []
    for annotation in text_annotations[1:]:
        text = annotation.get("description", "").strip()
        if not text:
            continue
        bounds = _extract_bounds(annotation.get("boundingPoly", {}))
        results.append({"label": text, "bounds": bounds})

    return results, image_size


def _parse_label_response(response_data: dict[str, Any]) -> tuple[list[TextDataItem], list[int] | None, bool, str]:
    """
    ラベル検出レスポンスを解析する。
    テキスト検出と物体検出の両方の結果を組み合わせて、ラベルの有無を判定する。

    判定ロジック:
        - テキストが検出された → ラベルあり（OK）
        - ラベル関連の物体が検出された → ラベルあり（OK）
        - どちらも検出されない → ラベルなし（NG）

    Returns:
        tuple: (data_list, image_size, label_detected, label_reason)
            data_list: 検出された項目のリスト
            image_size: ピクセル座標の基準サイズ（テキスト検出時のみ）
            label_detected: bool ラベルが検出されたか
            label_reason: str 判定理由の説明
    """
    reasons: list[str] = []
    all_data: list[TextDataItem] = []

    # テキスト検出の結果を確認
    text_annotations = response_data.get("textAnnotations", [])
    has_text = len(text_annotations) > 1  # [0]は全文、[1:]が個別テキスト

    image_size = None
    if has_text:
        text_data, image_size = _parse_text_response(response_data)
        all_data.extend(text_data)
        # 検出されたテキストの先頭部分を理由に含める
        full_text = text_annotations[0].get("description", "").strip()
        preview = full_text[:30] + ("..." if len(full_text) > 30 else "")
        reasons.append(f"テキスト検出: 「{preview}」")

    # 物体検出の結果を確認（ラベル関連のキーワードに一致するもの）
    objects = response_data.get("localizedObjectAnnotations", [])
    label_objects = []
    for obj in objects:
        name = obj.get("name", "")
        if name.lower() in LABEL_OBJECT_KEYWORDS:
            score = obj.get("score", 0)
            ja_name = OBJECT_TRANSLATIONS.get(name.lower(), "")
            display = f"{name}（{ja_name}）" if ja_name else name
            label_objects.append(f"{display} {score:.0%}")

    has_label_object = len(label_objects) > 0
    if has_label_object:
        reasons.append(f"物体検出: {', '.join(label_objects)}")

    label_detected = has_text or has_label_object

    if label_detected:
        label_reason = " / ".join(reasons)
    else:
        label_reason = "テキスト・ラベル関連の物体が検出されませんでした"

    return all_data, image_size, label_detected, label_reason


def _parse_object_response(response_data: dict[str, Any]) -> list[TextDataItem]:
    """
    物体検出（OBJECT_LOCALIZATION）レスポンスを解析する。
    各物体のラベルと正規化バウンディングボックス座標（0〜1）を返す。

    Returns:
        list: [{"label": str, "bounds": [[x,y], ...]}, ...]
    """
    objects = response_data.get("localizedObjectAnnotations", [])
    results: list[TextDataItem] = []
    for obj in objects:
        en_name = obj.get("name", "")
        score = obj.get("score", 0)
        label = _build_label_with_translation(en_name, score, OBJECT_TRANSLATIONS)

        # normalizedVertices は 0〜1 の正規化座標
        bounds = _extract_bounds(obj.get("boundingPoly", {}), coord_key="normalizedVertices")

        results.append({"label": label, "bounds": bounds})

    return results


def _parse_face_response(response_data: dict[str, Any]) -> list[FaceDataItem]:
    """
    顔検出（FACE_DETECTION）レスポンスを解析する。
    各顔のバウンディングボックスと感情分析結果を返す。

    Returns:
        list: [{
            "label": str,
            "bounds": [[x,y], ...],  # ピクセル座標
            "emotions": dict,        # {"joy": "LIKELY", ...}
            "confidence": float,
        }, ...]
    """
    annotations = response_data.get("faceAnnotations", [])
    results: list[FaceDataItem] = []
    for idx, face in enumerate(annotations, 1):
        confidence = face.get("detectionConfidence", 0)

        # 感情データを構造化
        emotions = {
            "joy": face.get("joyLikelihood", "UNKNOWN"),
            "sorrow": face.get("sorrowLikelihood", "UNKNOWN"),
            "anger": face.get("angerLikelihood", "UNKNOWN"),
            "surprise": face.get("surpriseLikelihood", "UNKNOWN"),
        }

        # POSSIBLE以上の感情のみラベルに含める
        significant_levels = {"POSSIBLE", "LIKELY", "VERY_LIKELY"}
        significant_emotions = []
        for emo_key, emo_value in emotions.items():
            if emo_value in significant_levels:
                ja_name = EMOTION_NAMES.get(emo_key, emo_key)
                ja_level = EMOTION_LIKELIHOOD.get(emo_value, emo_value)
                significant_emotions.append(f"{ja_name}({ja_level})")

        emotion_text = ", ".join(significant_emotions) if significant_emotions else "表情なし"
        label = f"顔{idx}: {emotion_text} - {confidence:.0%}"

        # バウンディングボックス（fdBoundingPoly優先、なければboundingPoly）
        fd_poly = face.get("fdBoundingPoly", {})
        poly = fd_poly if fd_poly.get("vertices") else face.get("boundingPoly", {})
        bounds = _extract_bounds(poly)

        results.append({
            "label": label,
            "bounds": bounds,
            "emotions": emotions,
            "confidence": confidence,
        })

    return results


def _parse_logo_response(response_data: dict[str, Any]) -> list[TextDataItem]:
    """
    ロゴ検出（LOGO_DETECTION）レスポンスを解析する。
    各ロゴのブランド名、スコア、バウンディングボックスを返す。

    Returns:
        list: [{"label": str, "bounds": [[x,y], ...]}, ...]
    """
    annotations = response_data.get("logoAnnotations", [])
    results: list[TextDataItem] = []
    for logo in annotations:
        name = logo.get("description", "不明")
        score = logo.get("score", 0)
        label = f"{name} - {score:.0%}"

        bounds = _extract_bounds(logo.get("boundingPoly", {}))

        results.append({"label": label, "bounds": bounds})

    return results


def _parse_classify_response(response_data: dict[str, Any]) -> list[ClassifyDataItem]:
    """
    分類タグ（LABEL_DETECTION）レスポンスを解析する。
    画像全体に対する分類ラベルとスコアを返す（座標なし）。

    Returns:
        list: [{"label": str, "score": float}, ...]
    """
    annotations = response_data.get("labelAnnotations", [])
    results: list[ClassifyDataItem] = []
    for item in annotations:
        en_name = item.get("description", "")
        score = item.get("score", 0)
        label = _build_label_with_translation(en_name, score, LABEL_TRANSLATIONS)
        results.append({"label": label, "score": score})

    return results


def _parse_web_response(response_data: dict[str, Any]) -> tuple[list[WebDataItem], WebDetail]:
    """
    Web類似検索（WEB_DETECTION）レスポンスを解析する。
    エンティティ情報、関連ページ、類似画像URLを返す。

    Returns:
        tuple: (data_list, web_detail)
            data_list: 統一データ形式（推定ラベル等）
            web_detail: 構造化されたWeb検索結果
    """
    web = response_data.get("webDetection", {})

    # ベストゲス推定
    best_guess_labels = web.get("bestGuessLabels", [])
    best_guess = best_guess_labels[0].get("label", "") if best_guess_labels else None

    # Webエンティティ（上位5件）
    entities: list[WebEntity] = []
    for entity in web.get("webEntities", [])[:5]:
        name = entity.get("description", "")
        if name:
            entities.append({"name": name, "score": entity.get("score", 0)})

    # 関連ページ（上位5件）
    pages: list[WebPage] = []
    for page_info in web.get("pagesWithMatchingImages", [])[:5]:
        pages.append({
            "url": page_info.get("url", ""),
            "title": page_info.get("pageTitle", ""),
        })

    # 類似画像URL（上位3件）
    similar_images: list[str] = [
        img.get("url", "")
        for img in web.get("visuallySimilarImages", [])[:3]
        if img.get("url")
    ]

    # 統一data形式（ラベルのみ、boundsなし）
    data: list[WebDataItem] = []
    if best_guess:
        data.append({"label": f"推定: {best_guess}"})
    for ent in entities:
        data.append({"label": f"{ent['name']} ({ent['score']:.0%})"})

    web_detail: WebDetail = {
        "best_guess": best_guess,
        "entities": entities,
        "pages": pages,
        "similar_images": similar_images,
    }

    return data, web_detail
