"""
Vision AI Scanner - メインアプリケーション。
カメラ映像からテキスト抽出・物体検出を行うWebアプリケーション。
"""

import os
import base64
import logging
import time
from threading import Lock

# メモリリーク対策: cachetoolsを必須とする（requirements.txtに追加済み）
try:
    from cachetools import TTLCache
except ImportError:
    raise ImportError("cachetools がインストールされていません。pip install -r requirements.txt を実行してください。")

from flask import Flask, render_template, request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from vision_api import detect_content, get_proxy_status, set_proxy_enabled, VALID_MODES

# ─── 設定 ──────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
MAX_IMAGE_SIZE = 5 * 1024 * 1024          # 5MB（Base64デコード後）
MAX_REQUEST_BODY = 10 * 1024 * 1024       # 10MB（Base64 + JSONオーバーヘッド）

# ─── サーバー側レート制限（IP単位） ────────────────
RATE_LIMIT_PER_MINUTE = 20   # 1分あたりの最大リクエスト数
RATE_LIMIT_DAILY = 100       # 1日あたりの最大リクエスト数
RATE_LIMIT_WINDOW_TTL = 90   # スライドウィンドウTTL（秒）。60秒+30秒バッファ
RATE_LIMIT_DAILY_TTL = 86400 # 日次カウントTTL（秒）= 24時間
CACHE_MAX_SIZE = 10_000      # レート制限キャッシュの最大IP数

rate_limit_store = TTLCache(maxsize=CACHE_MAX_SIZE, ttl=RATE_LIMIT_WINDOW_TTL)
daily_count_store = TTLCache(maxsize=CACHE_MAX_SIZE, ttl=RATE_LIMIT_DAILY_TTL)

# スレッドセーフな操作のためのロック
rate_limit_lock = Lock()


def is_rate_limited(client_ip):
    """
    IP単位でレート制限をチェックする（判定のみ、カウントは加算しない）。

    Returns:
        tuple: (制限中か, エラーメッセージ)
    """
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    with rate_limit_lock:
        daily = daily_count_store.get(client_ip, {"date": "", "count": 0})
        if daily.get("date") != today:
            daily = {"date": today, "count": 0}

        if daily["count"] >= RATE_LIMIT_DAILY:
            return True, f"1日あたりのAPI上限({RATE_LIMIT_DAILY}回)に達しました"

        timestamps = list(rate_limit_store.get(client_ip, []))
        recent = [t for t in timestamps if now - t < 60]
        if len(recent) >= RATE_LIMIT_PER_MINUTE:
            return True, f"リクエスト頻度が高すぎます（上限: {RATE_LIMIT_PER_MINUTE}回/分）"

    return False, ""


def record_request(client_ip):
    """
    API成功後に呼び出す。判定と加算を分離することで「成功時のみカウント」方針を実現。
    """
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    with rate_limit_lock:
        # スライドウィンドウへ追加
        timestamps = list(rate_limit_store.get(client_ip, []))
        rate_limit_store[client_ip] = [t for t in timestamps if now - t < 60] + [now]

        # 日次カウント加算
        daily = daily_count_store.get(client_ip, {"date": "", "count": 0})
        if daily.get("date") != today:
            daily = {"date": today, "count": 0}
        daily["count"] += 1
        daily_count_store[client_ip] = daily


# ─── アプリケーション初期化 ─────────────────────
app = Flask(__name__)

# リクエストボディの最大サイズ（Base64画像の5MB + JSONオーバーヘッド）
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BODY

# プロキシ配下でのIP取得を正しく行う（X-Forwarded-For対応）
# 注意: リバースプロキシなしの直接公開時は x_for=0 にすること（BUG-03対策）
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
if TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


# ─── セキュリティヘッダー ─────────────────────────
@app.after_request
def add_security_headers(response):
    """全レスポンスにセキュリティヘッダーを付与する。"""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ─── レスポンスヘルパー ────────────────────────────
def _error_response(error_code, message, status_code=400):
    """標準化されたエラーレスポンスを生成する。"""
    return jsonify({
        "ok": False,
        "data": [],
        "error_code": error_code,
        "message": message,
    }), status_code


# ─── ルーティング ────────────────────────────────
@app.route("/")
def index():
    """アプリケーションのメインページを表示する"""
    return render_template("index.html")


@app.route("/api/config/proxy", methods=["GET"])
def get_proxy_config():
    """現在のプロキシ設定状態を返す"""
    return jsonify(get_proxy_status())


@app.route("/api/config/proxy", methods=["POST"])
def update_proxy_config():
    """プロキシ設定を更新する"""
    data = request.json
    if not data or "enabled" not in data:
        return jsonify({"ok": False, "message": "enabledフィールドが必要です"}), 400

    new_status = set_proxy_enabled(bool(data["enabled"]))
    return jsonify({"ok": True, "status": new_status})


def _validate_analyze_request():
    """
    /api/analyze のリクエストを検証し、画像データとモードを返す。

    Returns:
        tuple: (image_data, mode, None) 成功時
               (None, None, error_response) 失敗時
    """
    # JSONフォーマットチェック
    if not request.is_json:
        return None, None, _error_response("INVALID_FORMAT", "リクエストはJSON形式である必要があります")

    # Content-Type は application/json だが本文が壊れている場合の安全なパース
    data = request.get_json(silent=True)
    if data is None:
        return None, None, _error_response("INVALID_FORMAT", "JSONのパースに失敗しました")

    # JSON が dict 以外（null, 配列等）のとき AttributeError を防ぐ
    if not isinstance(data, dict):
        return None, None, _error_response("INVALID_FORMAT", "リクエストボディはJSONオブジェクトである必要があります")

    # 画像データの存在チェック（Nullや空文字も拒否）
    image_data = data.get("image")
    if not image_data or not isinstance(image_data, str) or not image_data.strip():
        return None, None, _error_response("MISSING_IMAGE", "画像データがありません")

    # モードのバリデーション
    mode = data.get("mode", "text")
    if mode not in VALID_MODES:
        return None, None, _error_response("INVALID_MODE", f"不正なモード: '{mode}'。許可値: {list(VALID_MODES)}")

    # data:image/jpeg;base64, プレフィックスを除去
    if "," in image_data:
        image_data = image_data.split(",")[1]

    # Base64デコード検証 & サイズチェック
    try:
        decoded = base64.b64decode(image_data, validate=True)
        if len(decoded) > MAX_IMAGE_SIZE:
            return None, None, _error_response(
                "IMAGE_TOO_LARGE",
                f"画像サイズが上限({MAX_IMAGE_SIZE // (1024*1024)}MB)を超えています",
            )
    except Exception:
        return None, None, _error_response("INVALID_BASE64", "画像データのBase64デコードに失敗しました")

    return image_data, mode, None


@app.route("/api/analyze", methods=["POST"])
def analyze_endpoint():
    """
    画像を受け取り、Vision APIで解析して結果を返す。

    リクエストJSON:
        image: Base64エンコードされた画像（data:image/jpeg;base64,...形式）
        mode: 'text'（OCR）または 'object'（物体検出）

    レスポンスJSON:
        ok: 成功/失敗
        data: 検出結果の文字列リスト
        error_code: エラーコード（エラー時のみ）
        message: エラーメッセージ（エラー時のみ）
    """
    # ─── リクエスト検証 ─────────────────
    image_data, mode, validation_error = _validate_analyze_request()
    if validation_error:
        return validation_error

    # ─── レート制限チェック ──────────────
    client_ip = request.remote_addr or "unknown"
    limited, limit_message = is_rate_limited(client_ip)
    if limited:
        return _error_response("RATE_LIMITED", limit_message, 429)

    # ─── Vision API呼び出し ─────────────
    try:
        result = detect_content(image_data, mode)

        # 成功時のみサーバー側カウント加算（判定と加算を分離）
        if result["ok"]:
            record_request(client_ip)

        status_code = 200 if result["ok"] else 502
        return jsonify(result), status_code

    except ValueError as e:
        logger.warning("バリデーションエラー: %s", e)
        return _error_response("VALIDATION_ERROR", str(e))

    except Exception as e:
        logger.error("サーバーエラー: %s", e, exc_info=True)
        return _error_response("SERVER_ERROR", "内部サーバーエラーが発生しました", 500)


if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG, port=5000)
