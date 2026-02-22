# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

Vision AI Scanner — カメラ映像からリアルタイムでテキスト抽出（OCR）・物体検出を行うWebアプリケーション。

- **本番URL**: https://vision-scanner.onrender.com/
- **ホスティング**: Render（`render.yaml` で構成、gunicorn起動）
- **リポジトリ**: https://github.com/Naoki-Kaneda/Vision-Scanner.git

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

# E2Eテスト（Playwright必須、別途 playwright install chromium）
pytest tests/e2e/ -v

# リンター
ruff check .

# セキュリティスキャン
bandit -r . --exclude ./tests,./venv,./.venv -q

# 依存関係の脆弱性チェック
pip-audit
```

## アーキテクチャ

### リクエストフロー

```
ブラウザ(script.js) → POST /api/analyze → app.py(バリデーション+レート制限) → vision_api.py(前処理+API呼び出し) → Google Cloud Vision API
```

### バックエンド（Python/Flask）

- **`app.py`**: Flaskエントリーポイント。`/api/analyze`でリクエストバリデーション（Base64検証、MIMEマジックバイト検証、サイズ上限5MB、モード列挙チェック）とIP単位レート制限を行う。ルートハンドラは薄く保ち、ロジックは`vision_api.py`に委譲。`before_request`で相関ID(`g.request_id`)とCSPノンス(`g.csp_nonce`)を生成。
- **`vision_api.py`**: Google Cloud Vision APIクライアント。`detect_content()`が単一エントリーポイント。テキストモードでは画像前処理（Pillow: コントラスト+シャープネス強調）を適用。`requests.Session`をモジュールレベルで共有し、リトライ戦略（3回、指数バックオフ、429/5xx再試行）を組み込み。APIキーは`x-goog-api-key`ヘッダーで送信（URLパラメータ不使用）。
- **`rate_limiter.py`**: Redis接続時はLuaスクリプトで原子的操作（マルチプロセス安全）、未接続時はインメモリ(TTLCache)にフォールバック。公開API: `try_consume_request()` / `release_request()`。API失敗時は`release_request()`で予約を取り消し、ユーザーのクォータを消費しない。
- **`translations.py`**: 物体検出ラベルの英日翻訳辞書（`_parse_object_response()`で使用）。

### フロントエンド（バニラJS — フレームワーク不使用）

- **`static/script.js`**: カメラ制御、フレーム間差分による静止検知（`requestAnimationFrame`ループ）、ターゲットボックス内クロップ→Base64化→`/api/analyze`へPOST。API使用量はlocalStorageで日次管理。イベントハンドラは`init()`内で`addEventListener`登録（CSP準拠）。
- **`templates/index.html`**: Jinja2テンプレート。CSPノンスを`{{ csp_nonce }}`で受け渡し。
- **`static/style.css`**: Glassmorphism風ダークテーマ。CSS変数でデザイントークン管理。

### セキュリティ構成

- **CSP**: `script-src 'self'`、`style-src 'self' 'nonce-...'`（unsafe-inline排除）
- **CORS**: デフォルト同一オリジンのみ。`ALLOWED_ORIGINS`で明示的に許可
- **相関ID**: 全リクエストに`X-Request-Id`ヘッダー付与（ログと一致）
- **MIME検証**: JPEG/PNGのmagic byte検証（Base64デコード後）
- **レート制限**: Redis原子操作 or インメモリ二重構造（分間+日次）

### CI/CD

- `.github/workflows/ci.yml`: pytest + ruff + bandit + pip-audit
- `.github/workflows/secrets-scan.yml`: シークレットスキャン
- `.github/dependabot.yml`: pip依存+GitHub Actions週次チェック
- Renderへの自動デプロイ: mainブランチへのpushで自動反映

## テスト構成

- `tests/test_api.py`: Flaskテストクライアントを使用したAPIエンドポイントテスト（正常OCR / 物体検出 / 不正入力 / API障害 / セキュリティヘッダー / CORS / request-id / MIME検証 / レート制限設定API / ヘルスチェック）
- `tests/test_vision_api.py`: `vision_api.py`の単体テスト（HTTPエラー、タイムアウト、部分エラー、パーサー境界ケース、プロキシ状態4パターン回帰テスト）
- `tests/e2e/test_ui.py`: Playwright E2Eテスト（ページ読み込み、モード切替、エラー表示、設定API反映検証）
- `tests/conftest.py`: 共通フィクスチャ（Flaskテストクライアント等）

## 環境変数（`.env`）

| 変数 | 必須 | 説明 |
|------|------|------|
| `VISION_API_KEY` | Yes | Google Cloud Vision APIキー |
| `PROXY_URL` | No | 企業プロキシURL |
| `VERIFY_SSL` | No | SSL検証（デフォルト`true`） |
| `FLASK_DEBUG` | No | デバッグモード（デフォルト`false`） |
| `NO_PROXY_MODE` | No | `true`でプロキシ設定を無視 |
| `ADMIN_SECRET` | No | 管理API認証シークレット |
| `REDIS_URL` | No | Redisレート制限用（未設定=インメモリ） |
| `ALLOWED_ORIGINS` | No | CORS許可Origin（カンマ区切り） |
| `RATE_LIMIT_PER_MINUTE` | No | 分間上限（デフォルト20） |
| `RATE_LIMIT_DAILY` | No | 日次上限（デフォルト1000） |
| `SSL_CERT_PATH` | No | SSL証明書ファイルパス（未設定=HTTP） |
| `SSL_KEY_PATH` | No | SSL秘密鍵ファイルパス（未設定=HTTP） |
| `TRUST_PROXY` | No | リバースプロキシ信頼（デフォルト`false`） |
| `TRUST_PROXY_HOPS` | No | プロキシホップ数（デフォルト`1`、多段LB時に増やす） |

## コーディング規約

- コミット形式: `feat:` / `fix:` / `test:` / `refactor:` / `docs:` / `chore:` + 日本語メッセージ
- コード内コメント・docstringは日本語
- 変数名は英語（ローマ字禁止）
- テスト名は日本語可（例: `test_テキスト抽出が正常に動作する`）
- APIレスポンス形式: `{"ok": bool, "data": list, "error_code": str|None, "message": str|None}`
- XSS対策: フロントエンドでは`innerHTML`ではなくDOM操作（`textContent`/`createTextNode`）を使用
- CSP対策: HTML inline属性（onclick, style）禁止 → JSイベントリスナー/CSSクラスを使用
- MVVMや継承パターンは使用しない
