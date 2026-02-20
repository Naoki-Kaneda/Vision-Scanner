# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

Vision AI Scanner — カメラ映像からリアルタイムでテキスト抽出（OCR）・物体検出を行うWebアプリケーション。Google Cloud Vision APIをバックエンドで使用し、フロントエンドはバニラJS（フレームワークなし）で構築。

## 開発コマンド

```bash
# 仮想環境の有効化（Windows PowerShell）
venv\Scripts\Activate.ps1

# 依存ライブラリのインストール
pip install -r requirements.txt
pip install -r requirements-dev.txt

# サーバー起動（http://localhost:5000）
python app.py

# テスト実行
pytest tests/ -v

# 単一テストファイルの実行
pytest tests/test_api.py -v
pytest tests/test_vision_api.py -v

# 特定テストクラス/メソッドの実行
pytest tests/test_api.py::TestInvalidInput -v
pytest tests/test_api.py::TestInvalidInput::test_不正なモードを拒否する -v

# リンター
ruff check .

# セキュリティスキャン
bandit -r . --exclude ./venv
```

## アーキテクチャ

### リクエストフロー

```
ブラウザ(script.js) → POST /api/analyze → app.py(バリデーション+レート制限) → vision_api.py(前処理+API呼び出し) → Google Cloud Vision API
```

### バックエンド（Python/Flask）

- **`app.py`**: Flaskエントリーポイント。`/api/analyze`エンドポイントでリクエストバリデーション（Base64検証、サイズ上限5MB、モード列挙チェック）とIP単位のサーバー側レート制限（20回/分、100回/日、TTLCacheで管理）を行う。ビジネスロジックは`vision_api.py`に委譲。
- **`vision_api.py`**: Google Cloud Vision APIクライアント。`detect_content()`が単一エントリーポイント。テキストモードでは画像前処理（Pillow: コントラスト+シャープネス強調）を適用。`requests.Session`をモジュールレベルで共有し、リトライ戦略（3回、指数バックオフ、429/5xx再試行）を組み込み。レスポンス解析は`_parse_text_response()`と`_parse_label_response()`に分離。
- **`translations.py`**: 物体検出ラベルの英日翻訳辞書（`OBJECT_TRANSLATIONS`）。`_parse_label_response()`がルックアップに使用。

### フロントエンド（バニラJS）

- **`static/script.js`**: カメラ制御、フレーム間差分による静止検知（`requestAnimationFrame`ループ）、ターゲットボックス内クロップ→Base64化→`/api/analyze`へPOST。API使用量はlocalStorageで日次管理。エラー時は5秒後に自動再試行。
- **`templates/index.html`**: Jinja2テンプレート。左パネル（映像+コントロール）と右パネル（検出結果）の2カラム構成。
- **`static/style.css`**: Glassmorphism風ダークテーマ。CSS変数でデザイントークン管理。768px以下でシングルカラムに切り替え。

### レート制限の二重構造

クライアント側（localStorage: 100回/日）とサーバー側（TTLCache: 20回/分+100回/日、IP単位）の二重制限。**成功時のみカウント加算**する方針で、判定（`is_rate_limited`）と記録（`record_request`）を分離。

## テスト構成

- `tests/test_api.py`: Flaskテストクライアントを使用したAPIエンドポイントテスト。`detect_content`をモックしてバリデーション4系統（正常OCR / 正常物体検出 / 不正入力 / API障害）をカバー。
- `tests/test_vision_api.py`: `vision_api.py`の単体テスト。`session.post`をモックしてHTTPエラー、タイムアウト、部分エラー、パーサー境界ケースをカバー。

## 環境変数（`.env`）

| 変数 | 必須 | 説明 |
|------|------|------|
| `VISION_API_KEY` | Yes | Google Cloud Vision APIキー |
| `PROXY_URL` | No | 企業プロキシURL |
| `VERIFY_SSL` | No | SSL検証（デフォルト`true`） |
| `FLASK_DEBUG` | No | デバッグモード（デフォルト`false`） |
| `NO_PROXY_MODE` | No | `true`でプロキシ設定を無視 |

## コーディング規約

- コミット形式: `feat:` / `fix:` / `test:` / `refactor:` / `docs:` / `chore:` + 日本語メッセージ
- コード内コメント・docstringは日本語
- 変数名は英語（ローマ字禁止）
- `app.py`のルートハンドラは薄く保ち、ロジックは`vision_api.py`に配置
- テスト名は日本語可（例: `test_テキスト抽出が正常に動作する`）
- APIレスポンス形式: `{"ok": bool, "data": list, "error_code": str|None, "message": str|None}`
- XSS対策: フロントエンドでは`innerHTML`ではなくDOM操作（`textContent`/`createTextNode`）を使用
- MVVMや継承パターンは使用しない
