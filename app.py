"""
Vision AI Scanner - メインアプリケーション。
カメラ映像からテキスト抽出・物体検出を行うWebアプリケーション。
"""

import os
import base64
import logging
import time
import uuid
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
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")  # 管理API認証用シークレット

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


def try_consume_request(client_ip):
    """
    レート制限のチェックと予約を原子的に行う（TOCTOU競合防止）。

    制限内ならカウントを加算して (False, "", request_id) を返す。
    制限超過なら加算せず (True, エラーメッセージ, None) を返す。
    API呼び出し失敗時は release_request(client_ip, request_id) で予約を取り消すこと。

    Returns:
        tuple: (制限中か, エラーメッセージ, request_id|None)
    """
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    with rate_limit_lock:
        # 日次制限チェック
        daily = daily_count_store.get(client_ip, {"date": "", "count": 0})
        if daily.get("date") != today:
            daily = {"date": today, "count": 0}

        if daily["count"] >= RATE_LIMIT_DAILY:
            return True, f"1日あたりのAPI上限({RATE_LIMIT_DAILY}回)に達しました", None

        # 分間制限チェック（エントリは (timestamp, request_id) のタプル）
        entries = list(rate_limit_store.get(client_ip, []))
        recent = [e for e in entries if now - e[0] < 60]
        if len(recent) >= RATE_LIMIT_PER_MINUTE:
            return True, f"リクエスト頻度が高すぎます（上限: {RATE_LIMIT_PER_MINUTE}回/分）", None

        # チェック通過 → 一意IDで予約を原子的に記録
        request_id = uuid.uuid4().hex[:12]
        rate_limit_store[client_ip] = recent + [(now, request_id)]
        daily["count"] += 1
        daily_count_store[client_ip] = daily

    return False, "", request_id


def release_request(client_ip, request_id):
    """
    API呼び出し失敗時に指定IDの予約のみを取り消す（並行リクエスト安全）。
    """
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    with rate_limit_lock:
        # 指定IDのエントリのみを除去（他のリクエストに影響しない）
        entries = list(rate_limit_store.get(client_ip, []))
        new_entries = []
        removed = False
        for e in entries:
            if not removed and e[1] == request_id:
                removed = True
                continue
            if now - e[0] < 60:
                new_entries.append(e)
        rate_limit_store[client_ip] = new_entries

        # 除去できた場合のみ日次カウントを減算
        if removed:
            daily = daily_count_store.get(client_ip, {"date": "", "count": 0})
            if daily.get("date") == today and daily["count"] > 0:
                daily["count"] -= 1
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
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # CSP: self + Google Fonts + unsafe-inline（インラインstyle/onclick用）
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' blob: data:; "
        "media-src 'self' blob:; "
        "connect-src 'self'"
    )
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


# ─── ルーティング ────────────────────────────────
@app.route("/")
def index():
    """アプリケーションのメインページを表示する"""
    return render_template("index.html")


@app.route("/api/config/proxy", methods=["GET"])
def get_proxy_config():
    """現在のプロキシ設定状態を返す（認証時はURL情報付き、未認証時はON/OFFのみ）"""
    status = get_proxy_status()
    auth_header = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or auth_header != ADMIN_SECRET:
        # 未認証: ON/OFF状態のみ（URL情報は非公開）
        return jsonify({"enabled": status["enabled"]})
    return jsonify(status)


@app.route("/api/config/proxy", methods=["POST"])
def update_proxy_config():
    """プロキシ設定を更新する（認証必須）"""
    # シークレットキーによる認証
    auth_header = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or auth_header != ADMIN_SECRET:
        return _error_response("UNAUTHORIZED", "管理APIへのアクセス権がありません", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "enabled" not in data:
        return _error_response("INVALID_FORMAT", "enabledフィールドを含むJSONオブジェクトが必要です")

    # 型の厳密チェック: bool("false") == True を防止
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

    # ─── レート制限チェック＆予約（原子的） ──
    client_ip = request.remote_addr or "unknown"
    limited, limit_message, request_id = try_consume_request(client_ip)
    if limited:
        logger.info("rate_limited ip=%s reason=%s", client_ip, limit_message)
        return _error_response("RATE_LIMITED", limit_message, 429)

    # ─── Vision API呼び出し ─────────────
    try:
        result = detect_content(image_data, mode)

        # API失敗時は該当IDの予約のみ取り消す（成功時のみカウント消費）
        if result["ok"]:
            logger.info("api_success ip=%s mode=%s items=%d", client_ip, mode, len(result["data"]))
        else:
            release_request(client_ip, request_id)
            logger.warning("api_failure ip=%s mode=%s error_code=%s", client_ip, mode, result["error_code"])

        status_code = 200 if result["ok"] else 502
        return jsonify(result), status_code

    except ValueError as e:
        release_request(client_ip, request_id)
        logger.warning("validation_error ip=%s error=%s", client_ip, e)
        return _error_response("VALIDATION_ERROR", str(e))

    except Exception as e:
        release_request(client_ip, request_id)
        logger.error("server_error ip=%s error=%s", client_ip, e, exc_info=True)
        return _error_response("SERVER_ERROR", "内部サーバーエラーが発生しました", 500)


if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG, port=5000)
