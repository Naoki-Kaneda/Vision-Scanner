"""
Vision AI Scanner - メインアプリケーション。
カメラ映像からテキスト抽出・物体検出を行うWebアプリケーション。
"""

import logging
from flask import Flask, render_template, request, jsonify
from vision_api import detect_content

# ─── ログ設定 ──────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

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
        results: 検出結果の文字列リスト
    """
    try:
        data = request.json
        if "image" not in data:
            return jsonify({"error": "画像データがありません"}), 400

        image_data = data["image"]
        mode = data.get("mode", "text")

        # data:image/jpeg;base64, プレフィックスを除去
        if "," in image_data:
            image_data = image_data.split(",")[1]

        results = detect_content(image_data, mode)
        return jsonify({"results": results})

    except Exception as e:
        logger.error("サーバーエラー: %s", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
