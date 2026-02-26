"""
Vision AI Scanner - メインアプリケーション。
カメラ映像からテキスト抽出・物体検出を行うWebアプリケーション。
"""

import os
import base64
import hashlib
import logging
import secrets
import socket
import time
from collections import defaultdict
from threading import Lock

from flask import Flask, render_template, request, jsonify, g
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from vision_api import detect_content, get_proxy_status, set_proxy_enabled, VALID_MODES, API_KEY
from rate_limiter import (
    try_consume_request, release_request, RATE_LIMIT_DAILY,
    get_backend_type, REDIS_URL, seconds_until_midnight,
)

# ─── 設定 ──────────────────────────────────────
load_dotenv()

# Gunicorn環境ではGunicornのロガーを継承、開発環境では独自設定
_is_gunicorn = "gunicorn" in os.environ.get("SERVER_SOFTWARE", "")
if _is_gunicorn:
    # Gunicornのログハンドラーを活用（フォーマットはGunicorn設定に委譲）
    gunicorn_logger = logging.getLogger("gunicorn.error")
    logging.root.handlers = gunicorn_logger.handlers
    logging.root.setLevel(gunicorn_logger.level)
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,  # 開発環境: 既存のハンドラを上書きして確実にログ出力
    )
logger = logging.getLogger(__name__)
# werkzeug リクエストログを明示的に有効化
logging.getLogger("werkzeug").setLevel(logging.INFO)

APP_VERSION = "1.4.0"                     # テンプレートに自動注入される
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
APP_PORT = int(os.getenv("APP_PORT", "5001"))  # Gemini版(5000)と共存するためデフォルト5001
MAX_IMAGE_SIZE = 5 * 1024 * 1024          # 5MB（Base64デコード後）
MAX_REQUEST_BODY = 10 * 1024 * 1024       # 10MB（Base64 + JSONオーバーヘッド）
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")  # 管理API認証用シークレット

# ─── エラーコード定数（タイポ防止） ────────────────────
ERR_INVALID_FORMAT = "INVALID_FORMAT"
ERR_MISSING_IMAGE = "MISSING_IMAGE"
ERR_INVALID_MODE = "INVALID_MODE"
ERR_INVALID_BASE64 = "INVALID_BASE64"
ERR_IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
ERR_INVALID_IMAGE_FORMAT = "INVALID_IMAGE_FORMAT"
ERR_RATE_LIMITED = "RATE_LIMITED"
ERR_VALIDATION_ERROR = "VALIDATION_ERROR"
ERR_SERVER_ERROR = "SERVER_ERROR"
ERR_REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_UNAUTHORIZED = "UNAUTHORIZED"
ERR_INVALID_TYPE = "INVALID_TYPE"
ERR_METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"

# 起動時セキュリティチェック
def _check_admin_secret(secret):
    """ADMIN_SECRETの強度を検証し、警告メッセージのリストを返す。"""
    warnings = []
    if not secret:
        warnings.append("ADMIN_SECRET が未設定です。管理API（プロキシ設定変更）は常に403を返します。")
        return warnings
    if len(secret) < 16:
        warnings.append("ADMIN_SECRET が短すぎます（16文字以上を推奨）。")
    # 高エントロピー判定: 最低3種類の文字種（大文字/小文字/数字/記号）を含むこと
    char_types = sum([
        any(c.isupper() for c in secret),
        any(c.islower() for c in secret),
        any(c.isdigit() for c in secret),
        any(not c.isalnum() for c in secret),
    ])
    if char_types < 3:
        warnings.append(
            "ADMIN_SECRET のエントロピーが低い可能性があります（文字種が少ない）。"
            " ランダム生成を推奨: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return warnings

for _warn in _check_admin_secret(ADMIN_SECRET):
    logger.warning(_warn)


def _validate_api_key_format(key):
    """VISION_API_KEYの形式を簡易チェックし、警告メッセージのリストを返す。

    Google Cloud APIキーは通常39文字の英数字+ハイフン+アンダースコアで構成される。
    厳密なバリデーションではなく、明らかな設定ミス（空白混入、短すぎ等）の早期検出が目的。
    """
    warnings = []
    if not key:
        return warnings  # 未設定は別のチェックで検出済み
    import re
    if len(key) < 20:
        warnings.append(f"VISION_API_KEY が短すぎます（{len(key)}文字）。正しいキーか確認してください")
    if key != key.strip():
        warnings.append("VISION_API_KEY に前後の空白が含まれています。環境変数を確認してください")
    if not re.match(r'^[A-Za-z0-9_\-]+$', key):
        warnings.append("VISION_API_KEY に不正な文字が含まれています。英数字・ハイフン・アンダースコアのみ有効です")
    return warnings


for _warn in _validate_api_key_format(API_KEY):
    logger.warning(_warn)

# CORS: 許可するOrigin（カンマ区切り）。未設定 = 同一オリジンのみ（デフォルト安全）
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# 画像フォーマット検証: 許可するMIMEタイプのマジックバイト
ALLOWED_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}


# ─── 管理APIブルートフォース防御 ──────────────────
ADMIN_MAX_FAILURES = 5         # ブロックまでの連続失敗回数
ADMIN_BLOCK_WINDOW = 300       # 失敗追跡ウィンドウ（秒）= 5分
_admin_failures = defaultdict(list)   # {ip: [timestamp, ...]}
_admin_lock = Lock()


# ─── メトリクス（スレッドセーフ） ──────────────────
_metrics = defaultdict(int)
_metrics_lock = Lock()


def _record_metric(name, increment=1):
    """メトリクスカウンターをインクリメントする（スレッドセーフ）。"""
    with _metrics_lock:
        _metrics[name] += increment


def _reset_metrics_for_testing():
    """テスト用: メトリクスカウンターをリセットする。"""
    with _metrics_lock:
        _metrics.clear()


def _record_admin_failure(client_ip):
    """管理API認証失敗を記録する。"""
    with _admin_lock:
        now = time.time()
        cutoff = now - ADMIN_BLOCK_WINDOW
        # ウィンドウ外の古い記録を除去してから追加
        _admin_failures[client_ip] = [t for t in _admin_failures[client_ip] if t > cutoff]
        _admin_failures[client_ip].append(now)


def _is_admin_blocked(client_ip):
    """管理APIへのアクセスがブロックされているか判定する。"""
    with _admin_lock:
        now = time.time()
        cutoff = now - ADMIN_BLOCK_WINDOW
        _admin_failures[client_ip] = [t for t in _admin_failures[client_ip] if t > cutoff]
        return len(_admin_failures[client_ip]) >= ADMIN_MAX_FAILURES


# ─── アプリケーション初期化 ─────────────────────
app = Flask(__name__)

# Flask SECRET_KEY: 署名付きクッキー等の暗号化に使用（将来的な拡張に備える）
_flask_secret_key = os.getenv("FLASK_SECRET_KEY")
if _flask_secret_key:
    app.config["SECRET_KEY"] = _flask_secret_key
else:
    logger.warning(
        "FLASK_SECRET_KEY が未設定です。"
        " 署名付きセッション等を使用する場合は環境変数に設定してください。"
        " 生成例: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )

# リクエストボディの最大サイズ（Base64画像の5MB + JSONオーバーヘッド）
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BODY

# 静的ファイルのブラウザキャッシュを無効化（開発時のキャッシュ問題を防止）
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# テンプレートをリクエストごとにディスクから再読み込み
app.config["TEMPLATES_AUTO_RELOAD"] = True

# 静的ファイルのハッシュキャッシュ（起動中はファイル変更時に自動更新）
_static_hash_cache = {}


def _static_file_hash(filename):
    """静的ファイルのMD5ハッシュ先頭8文字を返す（キャッシュバスティング用）。

    filename単位でキャッシュし、mtimeが変わったら上書きする。
    従来は filename:mtime をキーにしていたため更新のたびに辞書が肥大していた。
    """
    filepath = os.path.join(app.static_folder, filename)
    try:
        mtime = os.path.getmtime(filepath)
        cached = _static_hash_cache.get(filename)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(filepath, "rb") as f:
            digest = hashlib.md5(f.read()).hexdigest()[:8]
        _static_hash_cache[filename] = (mtime, digest)
        return digest
    except OSError:
        return "0"


@app.context_processor
def inject_template_globals():
    """テンプレートに共通変数を注入する（キャッシュバスティング関数・バージョン）。"""
    return {"static_hash": _static_file_hash, "app_version": APP_VERSION}


# プロキシ配下でのIP取得を正しく行う（X-Forwarded-For対応）
def _parse_proxy_hops(raw_value):
    """TRUST_PROXY_HOPS の文字列を安全にパースする。不正値・0以下は 1 にフォールバック。"""
    try:
        hops = int(raw_value)
    except (ValueError, TypeError):
        logger.warning("TRUST_PROXY_HOPS の値が不正です (%r)。デフォルト 1 を使用します。", raw_value)
        return 1
    if hops <= 0:
        logger.warning("TRUST_PROXY_HOPS が 0 以下 (%d) です。1 に矯正します。", hops)
        return 1
    return hops


TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
TRUST_PROXY_HOPS = _parse_proxy_hops(os.getenv("TRUST_PROXY_HOPS", "1"))
if TRUST_PROXY:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUST_PROXY_HOPS, x_proto=TRUST_PROXY_HOPS,
        x_host=TRUST_PROXY_HOPS, x_prefix=TRUST_PROXY_HOPS,
    )


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
    csp_directives = (
        "default-src 'self'; "
        "script-src 'self'; "
        f"style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' blob: data:; "
        "media-src 'self' blob: mediastream:; "
        "connect-src 'self'"
    )
    # HTTPS環境ではHTTPリソースを自動的にHTTPSへアップグレード
    if request.is_secure:
        csp_directives += "; upgrade-insecure-requests"
    response.headers["Content-Security-Policy"] = csp_directives

    # ブラウザ権限を最小化: カメラのみ許可し、不要な権限は明示的に拒否
    response.headers["Permissions-Policy"] = "camera=(self), microphone=()"

    # HTML/JS/CSSのブラウザキャッシュを防止（開発中の更新反映を保証）
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    # HSTS: HTTPS環境下ではブラウザにHTTPS通信を強制（SSL剥ぎ取り攻撃を防止）
    # request.is_secure はリバースプロキシ経由(ProxyFix)でも正しく判定される
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

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


# ─── レスポンスヘルパー ────────────────────────────
def _error_response(error_code, message, status_code=400, extra_fields=None, headers=None):
    """標準化されたエラーレスポンスを生成する。

    Args:
        error_code: エラーコード文字列
        message: エラーメッセージ
        status_code: HTTPステータスコード
        extra_fields: レスポンスJSONに追加するフィールド辞書
        headers: レスポンスに追加するHTTPヘッダー辞書
    """
    body = {
        "ok": False,
        "data": [],
        "error_code": error_code,
        "message": message,
    }
    if extra_fields:
        body.update(extra_fields)
    response = jsonify(body)
    response.status_code = status_code
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response


# ─── Flaskエラーハンドラ（_error_response で統一） ─────
@app.errorhandler(413)
def handle_request_too_large(_e):
    """リクエストボディが MAX_CONTENT_LENGTH を超えた場合のJSONレスポンス。"""
    return _error_response(
        ERR_REQUEST_TOO_LARGE,
        f"リクエストサイズが上限({MAX_REQUEST_BODY // (1024*1024)}MB)を超えています",
        413,
    )


@app.errorhandler(400)
def handle_bad_request(_e):
    """Flaskが投げる400エラーのJSONレスポンス。"""
    return _error_response(ERR_BAD_REQUEST, "不正なリクエストです", 400)


@app.errorhandler(405)
def handle_method_not_allowed(_e):
    """許可されていないHTTPメソッドのJSONレスポンス。"""
    return _error_response(ERR_METHOD_NOT_ALLOWED, "許可されていないHTTPメソッドです", 405)


def _log(level, event, **kwargs):
    """構造化ログ出力（request-id自動付与、PII自動マスク）。"""
    from pii_mask import mask_pii
    req_id = getattr(g, "request_id", "-")
    parts = [f"event={event}", f"request_id={req_id}"]
    for k, v in kwargs.items():
        # 文字列値にPIIマスキングを適用
        if isinstance(v, str):
            v = mask_pii(v)
        parts.append(f"{k}={v}")
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


# ─── ヘルスチェック ──────────────────────────────
@app.route("/healthz")
def healthz():
    """Liveness: アプリケーションが起動しているか（依存なし）"""
    return jsonify({"status": "ok"})


@app.route("/readyz")
def readyz():
    """Readiness: リクエスト処理可能か（APIキー・バックエンド等の設定チェック）

    クエリパラメータ:
        check_api=true: Vision APIエンドポイントへのDNS到達性も検査する（オプション）
    """
    rate_backend = get_backend_type()

    # REDIS_URL が設定されているのにインメモリにフォールバックしている場合は警告
    redis_fallback = bool(REDIS_URL) and rate_backend == "in_memory"

    api_key_warnings = _validate_api_key_format(API_KEY)
    api_key_valid = bool(API_KEY) and len(api_key_warnings) == 0

    checks = {
        "api_key_configured": bool(API_KEY),
        "api_key_format_ok": api_key_valid,
        "rate_limiter_backend": rate_backend,
        "rate_limiter_ok": not redis_fallback,
        "trust_proxy": TRUST_PROXY,
        "trust_proxy_hops": TRUST_PROXY_HOPS,
    }

    warnings_list = list(api_key_warnings)
    if redis_fallback:
        warnings_list.append(
            "REDIS_URL が設定されていますが、Redis接続に失敗しインメモリにフォールバックしています"
        )

    # オプション: Vision APIエンドポイントの到達性チェック
    if request.args.get("check_api", "").lower() == "true":
        try:
            socket.getaddrinfo("vision.googleapis.com", 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            checks["api_reachable"] = True
        except socket.gaierror:
            checks["api_reachable"] = False
            warnings_list.append("Vision API (vision.googleapis.com) のDNS解決に失敗しました")

    all_ok = bool(API_KEY) and not redis_fallback and checks.get("api_reachable", True)

    response_data = {
        "status": "ok" if all_ok else "not_ready",
        "checks": checks,
    }
    if warnings_list:
        response_data["warnings"] = warnings_list

    return jsonify(response_data), 200 if all_ok else 503


# ─── メトリクスエンドポイント（Prometheus互換） ───────
@app.route("/metrics")
def metrics_endpoint():
    """Prometheus互換テキスト形式でメトリクスを返す。"""
    with _metrics_lock:
        snapshot = dict(_metrics)

    lines = []
    # カウンター: api_requests_total
    lines.append("# HELP vision_api_requests_total API解析リクエスト総数")
    lines.append("# TYPE vision_api_requests_total counter")
    for status in ("success", "api_error", "server_error"):
        key = f"api_requests_total__{status}"
        lines.append(f'vision_api_requests_total{{status="{status}"}} {snapshot.get(key, 0)}')

    # カウンター: rate_limited_total
    lines.append("# HELP vision_rate_limited_total レート制限発動回数")
    lines.append("# TYPE vision_rate_limited_total counter")
    lines.append(f"vision_rate_limited_total {snapshot.get('rate_limited_total', 0)}")

    # カウンター: dry_run_total
    lines.append("# HELP vision_dry_run_total Dry Runリクエスト総数")
    lines.append("# TYPE vision_dry_run_total counter")
    lines.append(f"vision_dry_run_total {snapshot.get('dry_run_total', 0)}")

    # モード別カウンター
    lines.append("# HELP vision_requests_by_mode モード別リクエスト数")
    lines.append("# TYPE vision_requests_by_mode counter")
    for key, val in sorted(snapshot.items()):
        if key.startswith("mode__"):
            mode_name = key.replace("mode__", "")
            lines.append(f'vision_requests_by_mode{{mode="{mode_name}"}} {val}')

    response_text = "\n".join(lines) + "\n"
    return response_text, 200, {"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}


# ─── ルーティング ────────────────────────────────
@app.route("/")
def index():
    """アプリケーションのメインページを表示する"""
    return render_template("index.html", csp_nonce=g.csp_nonce)


@app.route("/api/config/limits", methods=["GET"])
def get_rate_limits():
    """レート制限設定値をフロントエンドに返す"""
    return jsonify({"daily_limit": RATE_LIMIT_DAILY})


@app.route("/api/config/proxy", methods=["GET"])
def get_proxy_config():
    """現在のプロキシ設定状態を返す（認証時はURL情報付き、未認証時はON/OFFのみ）"""
    status = get_proxy_status()
    auth_header = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or not secrets.compare_digest(auth_header, ADMIN_SECRET):
        # 認証ヘッダーが送られてきたが不正 → 攻撃の兆候としてログ記録
        if auth_header:
            _log("warning", "admin_auth_failed", ip=request.remote_addr, method="GET", endpoint="/api/config/proxy")
        return jsonify({"enabled": status["enabled"]})
    return jsonify(status)


@app.route("/api/config/proxy", methods=["POST"])
def update_proxy_config():
    """プロキシ設定を更新する（認証必須）"""
    client_ip = request.remote_addr or "unknown"

    # 管理APIブルートフォース防御: 短時間の連続失敗をブロック
    if _is_admin_blocked(client_ip):
        _log("warning", "admin_blocked", ip=client_ip, reason="too_many_failures")
        return _error_response(
            ERR_RATE_LIMITED, "認証失敗が多すぎます。しばらく経ってから再試行してください", 429,
            extra_fields={"retry_after": ADMIN_BLOCK_WINDOW},
            headers={"Retry-After": str(ADMIN_BLOCK_WINDOW)},
        )

    auth_header = request.headers.get("X-Admin-Secret", "")
    if not ADMIN_SECRET or not secrets.compare_digest(auth_header, ADMIN_SECRET):
        _record_admin_failure(client_ip)
        _log("warning", "admin_auth_failed", ip=client_ip, method="POST", endpoint="/api/config/proxy")
        return _error_response(ERR_UNAUTHORIZED, "管理APIへのアクセス権がありません", 403)

    if not request.is_json:
        return _error_response(ERR_INVALID_FORMAT, "リクエストはJSON形式である必要があります")

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "enabled" not in data:
        return _error_response(ERR_INVALID_FORMAT, "enabledフィールドを含むJSONオブジェクトが必要です")

    if not isinstance(data["enabled"], bool):
        return _error_response(ERR_INVALID_TYPE, "enabledフィールドはboolean型(true/false)である必要があります")

    new_status = set_proxy_enabled(data["enabled"])
    return jsonify({"ok": True, "status": new_status})


def _validate_analyze_request():
    """
    /api/analyze のリクエストを検証し、画像データ・モード・Dry Runフラグを返す。

    Returns:
        tuple: (image_data, mode, dry_run, None) 成功時
               (None, None, None, error_response) 失敗時
    """
    if not request.is_json:
        return None, None, None, _error_response(ERR_INVALID_FORMAT, "リクエストはJSON形式である必要があります")

    data = request.get_json(silent=True)
    if data is None:
        return None, None, None, _error_response(ERR_INVALID_FORMAT, "JSONのパースに失敗しました")

    if not isinstance(data, dict):
        return None, None, None, _error_response(ERR_INVALID_FORMAT, "リクエストボディはJSONオブジェクトである必要があります")

    image_data = data.get("image")
    if not image_data or not isinstance(image_data, str) or not image_data.strip():
        return None, None, None, _error_response(ERR_MISSING_IMAGE, "画像データがありません")

    mode = data.get("mode", "text")
    if mode not in VALID_MODES:
        return None, None, None, _error_response(ERR_INVALID_MODE, f"不正なモード: '{mode}'。許可値: {list(VALID_MODES)}")

    # data:image/jpeg;base64, プレフィックスを除去
    if "," in image_data:
        image_data = image_data.split(",")[1]

    # Base64デコード検証 & サイズチェック & フォーマット検証
    try:
        decoded = base64.b64decode(image_data, validate=True)
        if len(decoded) > MAX_IMAGE_SIZE:
            return None, None, None, _error_response(
                ERR_IMAGE_TOO_LARGE,
                f"画像サイズが上限({MAX_IMAGE_SIZE // (1024*1024)}MB)を超えています",
            )
        # MIME magic byte 検証（JPEG/PNGのみ許可）
        if not _validate_image_format(decoded):
            return None, None, None, _error_response(
                ERR_INVALID_IMAGE_FORMAT,
                "許可されていない画像形式です（JPEG/PNGのみ対応）",
            )
    except Exception:
        return None, None, None, _error_response(ERR_INVALID_BASE64, "画像データのBase64デコードに失敗しました")

    dry_run = data.get("dry_run", False) is True
    return image_data, mode, dry_run, None


# ─── Dry Run ダミーレスポンス定義 ─────────────────────
_DRY_RUN_RESPONSES = {
    "text": {
        "ok": True,
        "data": [
            {"label": "[DRY RUN] サンプルテキスト - Hello World",
             "bounds": [[10, 20], [200, 20], [200, 50], [10, 50]]},
        ],
        "image_size": [640, 480],
        "error_code": None, "message": None,
    },
    "object": {
        "ok": True,
        "data": [
            {"label": "[DRY RUN] Cup（カップ）- 92%",
             "bounds": [[0.2, 0.3], [0.6, 0.3], [0.6, 0.8], [0.2, 0.8]]},
        ],
        "image_size": None,
        "error_code": None, "message": None,
    },
    "label": {
        "ok": True,
        "data": [{"label": "[DRY RUN] ラベルあり"}],
        "image_size": None,
        "error_code": None, "message": None,
        "label_detected": True,
        "label_reason": "[DRY RUN] テストデータ: テキスト検出済み",
    },
    "face": {
        "ok": True,
        "data": [
            {"label": "[DRY RUN] 顔1: 喜び=高い",
             "bounds": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.5], [0.1, 0.5]]},
        ],
        "image_size": [640, 480],
        "error_code": None, "message": None,
    },
    "logo": {
        "ok": True,
        "data": [
            {"label": "[DRY RUN] SampleLogo - 88%",
             "bounds": [[0.2, 0.2], [0.5, 0.2], [0.5, 0.4], [0.2, 0.4]]},
        ],
        "image_size": [640, 480],
        "error_code": None, "message": None,
    },
    "classify": {
        "ok": True,
        "data": [
            {"label": "[DRY RUN] 電子機器 - 95%"},
            {"label": "[DRY RUN] ガジェット - 88%"},
        ],
        "image_size": None,
        "error_code": None, "message": None,
    },
    "web": {
        "ok": True,
        "data": [{"label": "[DRY RUN] サンプル画像"}],
        "image_size": None,
        "error_code": None, "message": None,
        "web_detail": {
            "best_guess": "[DRY RUN] テスト画像",
            "entities": [{"name": "Test Object", "score": 0.95}],
            "pages": [],
            "similar_images": [],
        },
    },
}


def _generate_dry_run_response(mode):
    """Dry Runモード用のダミーレスポンスを返す。"""
    return _DRY_RUN_RESPONSES.get(mode, _DRY_RUN_RESPONSES["text"])


@app.route("/api/analyze", methods=["OPTIONS"])
def analyze_preflight():
    """CORSプリフライトリクエストを明示的に処理する。

    after_request でCORSヘッダーを付与しているが、OPTIONSを明示しないと
    一部のWSGIサーバー（gunicorn等）が405を返す環境差分がある。
    空の204レスポンスを返し、after_requestがCORSヘッダーを付与する。
    """
    return "", 204


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
    image_data, mode, dry_run, validation_error = _validate_analyze_request()
    if validation_error:
        return validation_error

    client_ip = request.remote_addr or "unknown"

    # ─── Dry Runモード: APIキーもレート制限も消費しない ──
    if dry_run:
        _record_metric("dry_run_total")
        _record_metric(f"mode__{mode}")
        _log("info", "dry_run", ip=client_ip, mode=mode)
        return jsonify(_generate_dry_run_response(mode)), 200

    # ─── レート制限チェック＆予約（原子的） ──
    _record_metric(f"mode__{mode}")

    limited, limit_message, request_id, limit_type = try_consume_request(client_ip)
    if limited:
        _record_metric("rate_limited_total")
        _log("info", "rate_limited", ip=client_ip, reason=limit_message, limit_type=limit_type)
        # Retry-After: 分間制限は60秒、日次制限は翌日0時までの秒数
        if limit_type == "daily":
            retry_after = seconds_until_midnight()
        else:
            retry_after = 60
        return _error_response(
            ERR_RATE_LIMITED, limit_message, 429,
            extra_fields={"retry_after": retry_after, "limit_type": limit_type},
            headers={"Retry-After": str(retry_after)},
        )

    # ─── Vision API呼び出し ─────────────
    try:
        result = detect_content(image_data, mode, request_id=g.request_id)

        if result["ok"]:
            _record_metric("api_requests_total__success")
            _log("info", "api_success", ip=client_ip, mode=mode, items=len(result["data"]))
        else:
            _record_metric("api_requests_total__api_error")
            release_request(client_ip, request_id)
            _log("warning", "api_failure", ip=client_ip, mode=mode, error_code=result["error_code"])

        status_code = 200 if result["ok"] else 502
        return jsonify(result), status_code

    except ValueError as e:
        release_request(client_ip, request_id)
        _log("warning", "validation_error", ip=client_ip, mode=mode, error=str(e))
        return _error_response(ERR_VALIDATION_ERROR, str(e))

    except Exception as e:
        _record_metric("api_requests_total__server_error")
        release_request(client_ip, request_id)
        _log("error", "server_error", ip=client_ip, mode=mode, error=str(e))
        return _error_response(ERR_SERVER_ERROR, "内部サーバーエラーが発生しました", 500)


if __name__ == "__main__":
    ssl_cert = os.environ.get("SSL_CERT_PATH")
    ssl_key = os.environ.get("SSL_KEY_PATH")
    if ssl_cert and ssl_key:
        logger.info("HTTPS モードで起動 (証明書: %s)", ssl_cert)
        app.run(debug=FLASK_DEBUG, host="0.0.0.0", port=APP_PORT,
                ssl_context=(ssl_cert, ssl_key))
    else:
        app.run(debug=FLASK_DEBUG, port=APP_PORT)
