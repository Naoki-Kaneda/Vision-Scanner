"""
Vision AI Scanner - メインアプリケーション。
カメラ映像からテキスト抽出・物体検出を行うWebアプリケーション。
"""

import os
import base64
import logging
import time
from collections import defaultdict

try:
    from cachetools import TTLCache
    _USE_TTL_CACHE = True
except ImportError:
    _USE_TTL_CACHE = False

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from vision_api import detect_content

# ─── 設定 ──────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB（Base64デコード後）
VALID_MODES = {"text", "object"}

# ─── サーバー側レート制限（IP単位） ────────────────
RATE_LIMIT_PER_MINUTE = 20  # 1分あたりの最大リクエスト数
RATE_LIMIT_DAILY = 100      # 1日あたりの最大リクエスト数

# メモリリーク対策: TTLCacheで上限付きIPキャッシュ（cachetools未導入時はdefaultdict）
if _USE_TTL_CACHE:
    # TTL=86400秒（1日）、最大10000 IP
    rate_limit_store = TTLCache(maxsize=10000, ttl=90)   # 1分半のスライドウィンドウ用
    daily_count_store = TTLCache(maxsize=10000, ttl=86400)  # 1日TTL
else:
    rate_limit_store = defaultdict(list)
    daily_count_store = defaultdict(lambda: {"date": "", "count": 0})


def is_rate_limited(client_ip):
    """
    IP単位でレート制限をチェックする。

    Returns:
        tuple: (制限中か, エラーメッセージ)
    """
    now = time.time()
    today = time.strftime("%Y-%m-%d")

    # 日次制限チェック
    daily = daily_count_store.get(client_ip, {"date": "", "count": 0})
    if daily.get("date") != today:
        daily = {"date": today, "count": 0}

    if daily["count"] >= RATE_LIMIT_DAILY:
        return True, f"1日あたりのAPI上限({RATE_LIMIT_DAILY}回)に達しました"

    # 1分あたりの制限チェック（スライドウィンドウ）
    timestamps = list(rate_limit_store.get(client_ip, []))
    rate_limit_store[client_ip] = [t for t in timestamps if now - t < 60]

    if len(rate_limit_store[client_ip]) >= RATE_LIMIT_PER_MINUTE:
        return True, f"リクエスト頻度が高すぎます（上限: {RATE_LIMIT_PER_MINUTE}回/分）"

    # チェック通過後にのみカウント加算（クライアント側と方針統一）
    rate_limit_store[client_ip].append(now)
    daily["count"] += 1
    daily_count_store[client_ip] = daily

    return False, ""


# ─── アプリケーション初期化 ─────────────────────
app = Flask(__name__)


# ─── ルーティング ────────────────────────────────
@app.route("/")
def index():
    """メインページを表示する。"""
    return render_template("index.html")


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
    # JSONフォーマットチェック
    if not request.is_json:
        return jsonify({
            "ok": False, "data": [],
            "error_code": "INVALID_FORMAT",
            "message": "リクエストはJSON形式である必要があります",
        }), 400

    data = request.json

    # JSON が dict 以外（null, 配列等）のとき AttributeError を防ぐ
    if not isinstance(data, dict):
        return jsonify({
            "ok": False, "data": [],
            "error_code": "INVALID_FORMAT",
            "message": "リクエストボディはJSONオブジェクトである必要があります",
        }), 400

    # 画像データの存在チェック（Nullや空文字も拒否）
    image_data = data.get("image")
    if not image_data or not isinstance(image_data, str) or not image_data.strip():
        return jsonify({
            "ok": False, "data": [],
            "error_code": "MISSING_IMAGE",
            "message": "画像データがありません",
        }), 400

    # モードのバリデーション
    mode = data.get("mode", "text")
    if mode not in VALID_MODES:
        return jsonify({
            "ok": False, "data": [],
            "error_code": "INVALID_MODE",
            "message": f"不正なモード: '{mode}'。許可値: {list(VALID_MODES)}",
        }), 400

    # data:image/jpeg;base64, プレフィックスを除去
    if "," in image_data:
        image_data = image_data.split(",")[1]

    # Base64デコード検証 & サイズチェック
    try:
        decoded = base64.b64decode(image_data, validate=True)
        if len(decoded) > MAX_IMAGE_SIZE:
            return jsonify({
                "ok": False, "data": [],
                "error_code": "IMAGE_TOO_LARGE",
                "message": f"画像サイズが上限({MAX_IMAGE_SIZE // (1024*1024)}MB)を超えています",
            }), 400
    except Exception:
        return jsonify({
            "ok": False, "data": [],
            "error_code": "INVALID_BASE64",
            "message": "画像データのBase64デコードに失敗しました",
        }), 400

    # サーバー側レート制限チェック
    client_ip = request.remote_addr or "unknown"
    limited, limit_message = is_rate_limited(client_ip)
    if limited:
        return jsonify({
            "ok": False, "data": [],
            "error_code": "RATE_LIMITED",
            "message": limit_message,
        }), 429

    # Vision API呼び出し
    try:
        result = detect_content(image_data, mode)
        status_code = 200 if result["ok"] else 502
        return jsonify(result), status_code

    except ValueError as e:
        logger.warning("バリデーションエラー: %s", e)
        return jsonify({
            "ok": False, "data": [],
            "error_code": "VALIDATION_ERROR",
            "message": str(e),
        }), 400

    except Exception as e:
        logger.error("サーバーエラー: %s", e, exc_info=True)
        return jsonify({
            "ok": False, "data": [],
            "error_code": "SERVER_ERROR",
            "message": "内部サーバーエラーが発生しました",
        }), 500


if __name__ == "__main__":
    app.run(debug=FLASK_DEBUG, port=5000)
