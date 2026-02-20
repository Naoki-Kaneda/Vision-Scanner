"""
Vision AI Scanner - メインアプリケーション。
カメラ映像からテキスト抽出・物体検出を行うWebアプリケーション。
"""

import os
import base64
import logging
import secrets

from flask import Flask, render_template, request, jsonify, g
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from vision_api import detect_content, get_proxy_status, set_proxy_enabled, VALID_MODES
from rate_limiter import try_consume_request, release_request

# ─── 設定 ──────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,  # 既存のハンドラを上書きして確実にログ出力
)
logger = logging.getLogger(__name__)
# werkzeug リクエストログを明示的に有効化
logging.getLogger("werkzeug").setLevel(logging.INFO)

FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
MAX_IMAGE_SIZE = 5 * 1024 * 1024          # 5MB（Base64デコード後）
MAX_REQUEST_BODY = 10 * 1024 * 1024       # 10MB（Base64 + JSONオーバーヘッド）
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")  # 管理API認証用シークレット

# CORS: 許可するOrigin（カンマ区切り）。未設定 = 同一オリジンのみ（デフォルト安全）
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# 画像フォーマット検証: 許可するMIMEタイプのマジックバイト
ALLOWED_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


# ─── アプリケーション初期化 ─────────────────────
app = Flask(__name__)

# リクエストボディの最大サイズ（Base64画像の5MB + JSONオーバーヘッド）
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BODY

# 静的ファイルのブラウザキャッシュを無効化（開発時のキャッシュ問題を防止）
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# テンプレートをリクエストごとにディスクから再読み込み
app.config["TEMPLATES_AUTO_RELOAD"] = True

# プロキシ配下でのIP取得を正しく行う（X-Forwarded-For対応）
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
if TRUST_PROXY:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


# ─── リクエストコンテキスト（request-id / CSPノンス） ──
@app.before_request
def set_request_context():
    """リクエストごとに一意のIDとCSPノンスを生成する。"""
    g.request_id = secrets.token_hex(8)
    g.csp_nonce = secrets.token_urlsafe(16)


# ─── セキュリティヘッダー ─────────────────────────
@app.after_request
def add_security_headers(response):
    """全レスポンスにセキュリティヘッダーを付与する。"""
    nonce = getattr(g, "csp_nonce", "")
    req_id = getattr(g, "request_id", "")

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # CSP: nonce化により unsafe-inline を完全排除
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' blob: data:; "
        "media-src 'self' blob: mediastream:; "
        "connect-src 'self'"
    )

    # カメラ・マイクのアクセスを同一オリジンに限定
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self)"

    # HTML/JS/CSSのブラウザキャッシュを防止（開発中の更新反映を保証）
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    # 相関IDをレスポンスヘッダーに付与（障害調査用）
    if req_id:
        response.headers["X-Request-Id"] = req_id

    # CORS: 明示的に許可されたOriginのみ
    if ALLOWED_ORIGINS:
        origin = request.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"

    return response


# ─── Flaskエラーハンドラ（統一JSONレスポンス） ─────
@app.errorhandler(413)
def handle_request_too_large(_e):
    """リクエストボディが MAX_CONTENT_LENGTH を超えた場合のJSONレスポンス。"""
    return jsonify({
        "ok": False,
        "data": [],
        "error_code": "REQUEST_TOO_LARGE",
        "message": f"リクエストサイズが上限({MAX_REQUEST_BODY // (1024*1024)}MB)を超えています",
    }), 413


@app.errorhandler(400)
def handle_bad_request(_e):
    """Flaskが投げる400エラーのJSONレスポンス。"""
    return jsonify({
        "ok": False,
        "data": [],
        "error_code": "BAD_REQUEST",
        "message": "不正なリクエストです",
    }), 400


# ─── レスポンスヘルパー ────────────────────────────
def _error_response(error_code, message, status_code=400):
    """標準化されたエラーレスポンスを生成する。"""
    return jsonify({
        "ok": False,
        "data": [],
        "error_code": error_code,
        "message": message,
    }), status_code


def _log(level, event, **kwargs):
    """構造化ログ出力（request-id自動付与）。"""
    req_id = getattr(g, "request_id", "-")
    parts = [f"event={event}", f"request_id={req_id}"]
    parts.extend(f"{k}={v}" for k, v in kwargs.items())
    getattr(logger, level)(" ".join(parts))


# ─── 画像フォーマット検証 ──────────────────────────
def _validate_image_format(decoded_bytes):
    """
    デコード済みバイト列のマジックバイトを検査し、許可されたフォーマットか判定する。

    Returns:
        bool: JPEG/PNG なら True、それ以外は False
    """
    for magic_bytes in ALLOWED_IMAGE_MAGIC:
        if decoded_bytes[:len(magic_bytes)] == magic_bytes:
            return True
    return False


# ─── ルーティング ────────────────────────────────
@app.route("/")
def index():
    """アプリケーションのメインページを表示する"""
    return render_template("index.html", csp_nonce=g.csp_nonce)


@app.route("/api/config/proxy", methods=["GET"])
def get_proxy_config():
    """現在のプロキシ設定状態を返す（認証時はURL情報付き、未認証時はON/OFFのみ）"""
    status = get_proxy_status()
    auth_header = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or auth_header != ADMIN_SECRET:
        return jsonify({"enabled": status["enabled"]})
    return jsonify(status)


@app.route("/api/config/proxy", methods=["POST"])
def update_proxy_config():
    """プロキシ設定を更新する（認証必須）"""
    auth_header = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or auth_header != ADMIN_SECRET:
        return _error_response("UNAUTHORIZED", "管理APIへのアクセス権がありません", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "enabled" not in data:
        return _error_response("INVALID_FORMAT", "enabledフィールドを含むJSONオブジェクトが必要です")

    if not isinstance(data["enabled"], bool):
        return _error_response("INVALID_TYPE", "enabledフィールドはboolean型(true/false)である必要があります")

    new_status = set_proxy_enabled(data["enabled"])
    return jsonify({"ok": True, "status": new_status})


def _validate_analyze_request():
    """
    /api/analyze のリクエストを検証し、画像データとモードを返す。

    Returns:
        tuple: (image_data, mode, None) 成功時
               (None, None, error_response) 失敗時
    """
    if not request.is_json:
        return None, None, _error_response("INVALID_FORMAT", "リクエストはJSON形式である必要があります")

    data = request.get_json(silent=True)
    if data is None:
        return None, None, _error_response("INVALID_FORMAT", "JSONのパースに失敗しました")

    if not isinstance(data, dict):
        return None, None, _error_response("INVALID_FORMAT", "リクエストボディはJSONオブジェクトである必要があります")

    image_data = data.get("image")
    if not image_data or not isinstance(image_data, str) or not image_data.strip():
        return None, None, _error_response("MISSING_IMAGE", "画像データがありません")

    mode = data.get("mode", "text")
    if mode not in VALID_MODES:
        return None, None, _error_response("INVALID_MODE", f"不正なモード: '{mode}'。許可値: {list(VALID_MODES)}")

    # data:image/jpeg;base64, プレフィックスを除去
    if "," in image_data:
        image_data = image_data.split(",")[1]

    # Base64デコード検証 & サイズチェック & フォーマット検証
    try:
        decoded = base64.b64decode(image_data, validate=True)
        if len(decoded) > MAX_IMAGE_SIZE:
            return None, None, _error_response(
                "IMAGE_TOO_LARGE",
                f"画像サイズが上限({MAX_IMAGE_SIZE // (1024*1024)}MB)を超えています",
            )
        # MIME magic byte 検証（JPEG/PNGのみ許可）
        if not _validate_image_format(decoded):
            return None, None, _error_response(
                "INVALID_IMAGE_FORMAT",
                "許可されていない画像形式です（JPEG/PNGのみ対応）",
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

    # ─── レート制限チェック＆予約（原子的） ──
    client_ip = request.remote_addr or "unknown"
    limited, limit_message, request_id = try_consume_request(client_ip)
    if limited:
        _log("info", "rate_limited", ip=client_ip, reason=limit_message)
        return _error_response("RATE_LIMITED", limit_message, 429)

    # ─── Vision API呼び出し ─────────────
    try:
        result = detect_content(image_data, mode)

        if result["ok"]:
            _log("info", "api_success", ip=client_ip, mode=mode, items=len(result["data"]))
        else:
            release_request(client_ip, request_id)
            _log("warning", "api_failure", ip=client_ip, mode=mode, error_code=result["error_code"])

        status_code = 200 if result["ok"] else 502
        return jsonify(result), status_code

    except ValueError as e:
        release_request(client_ip, request_id)
        _log("warning", "validation_error", ip=client_ip, error=str(e))
        return _error_response("VALIDATION_ERROR", str(e))

    except Exception as e:
        release_request(client_ip, request_id)
        _log("error", "server_error", ip=client_ip, error=str(e))
        return _error_response("SERVER_ERROR", "内部サーバーエラーが発生しました", 500)


if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG, port=5000)
