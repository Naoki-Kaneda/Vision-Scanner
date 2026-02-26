# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

Vision AI Scanner — カメラ映像からリアルタイムでテキスト抽出（OCR）・物体検出を行うWebアプリケーション。

- **本番URL**: https://vision-scanner.onrender.com/
- **ホスティング**: Render（`render.yaml` で構成）
- **リポジトリ**: https://github.com/Naoki-Kaneda/Vision-Scanner.git
- **Python**: 3.11+（CI: 3.11 / 3.12 / 3.13）

## 開発コマンド

```bash
# 仮想環境の有効化（Windows PowerShell）
venv\Scripts\Activate.ps1

# 依存ライブラリのインストール
pip install -r requirements.txt
pip install -r requirements-dev.txt

# サーバー起動（http://localhost:5001 ※APP_PORTで変更可）
python app.py
# または起動スクリプト（Linux: HTTPS自動対応、Windows: HTTP）
./start.sh          # Linux/Mac
start.bat           # Windows

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

**依存ファイルの使い分け:**
- `requirements.in`: トップレベル本番依存（バージョン範囲指定、pip-compileの入力）
- `requirements-dev.in`: トップレベル開発依存（pip-compileの入力）
- `requirements.txt`: 本番依存のピン留め（Renderデプロイで使用）
- `requirements-dev.txt`: 開発・テスト依存（pytest, ruff, bandit, pip-tools等）
- `requirements-lock.txt`: pip-compileで自動生成されたサブ依存込みのピン留め（CI使用）

**依存管理ワークフロー（pip-tools）:**
```bash
# 本番依存のlock再生成（requirements.in を編集後に実行）
pip-compile requirements.in -o requirements-lock.txt --strip-extras --no-header

# requirements.txt も requirements.in の変更に合わせて手動更新
# （Renderが requirements.txt を直接参照するため）

# 開発依存のlock再生成
pip-compile requirements-dev.in -o requirements-dev-lock.txt --strip-extras --no-header
```

## アーキテクチャ

### リクエストフロー

```
ブラウザ(script.js) → POST /api/analyze → app.py(バリデーション+レート制限) → vision_api.py(前処理+API呼び出し) → Google Cloud Vision API
```

### バックエンド（Python/Flask）

- **`app.py`**: Flaskエントリーポイント。ルートハンドラは薄く保ち、ビジネスロジックは`vision_api.py`に委譲。`before_request`で相関ID(`g.request_id`)とCSPノンス(`g.csp_nonce`)を生成。リクエストバリデーション（Base64検証、MIMEマジックバイト検証、サイズ上限5MB、モード列挙チェック）とIP単位レート制限を担当。
- **`vision_api.py`**: Google Cloud Vision APIクライアント。`detect_content(image_b64, mode)`が単一エントリーポイント。テキストモードでは画像前処理（Pillow: コントラスト+シャープネス強調）を適用。`requests.Session`をモジュールレベルで共有し、リトライ戦略（3回、指数バックオフ、429/5xx再試行）を組み込み。APIキーは`x-goog-api-key`ヘッダーで送信（URLパラメータ不使用）。
- **`rate_limiter.py`**: Redis接続時はLuaスクリプトで原子的操作（マルチプロセス安全）、未接続時はインメモリ(TTLCache)にフォールバック。公開API: `try_consume_request()` / `release_request()` / `get_daily_count()` / `get_backend_type()`。API失敗時は`release_request()`で予約を取り消し、ユーザーのクォータを消費しない。
- **`translations.py`**: 物体検出ラベルの英日翻訳辞書（`_parse_object_response()`で使用）。`OBJECT_TRANSLATIONS` / `EMOTION_LIKELIHOOD` / `EMOTION_NAMES` / `LABEL_TRANSLATIONS` をエクスポート。

### APIエンドポイント一覧

| メソッド | パス | 認証 | 説明 |
|----------|------|------|------|
| `GET` | `/` | - | メインページ（Jinja2テンプレート） |
| `POST` | `/api/analyze` | - | 画像解析（メインAPI） |
| `OPTIONS` | `/api/analyze` | - | CORSプリフライト |
| `GET` | `/api/config/limits` | - | レート制限設定値（フロント用） |
| `GET` | `/api/config/proxy` | 任意 | プロキシ設定状態（認証時は詳細付き） |
| `POST` | `/api/config/proxy` | 必須 | プロキシ設定更新（`X-Admin-Secret`ヘッダー） |
| `GET` | `/healthz` | - | Liveness（プロセス生存確認） |
| `GET` | `/readyz` | - | Readiness（API Key・Redis確認） |

### Vision API モード

| mode | Vision API Feature | 備考 |
|------|--------------------|------|
| `text` | `DOCUMENT_TEXT_DETECTION` | Pillow前処理あり、`imageContext.languageHints`付与 |
| `object` | `OBJECT_LOCALIZATION` | 正規化座標（0〜1）で返却 |
| `label` | `LABEL_DETECTION` + `OBJECT_LOCALIZATION` | 2機能同時リクエスト、`imageContext.languageHints`付与 |
| `face` | `FACE_DETECTION` | 感情分析（joy/sorrow/anger/surprise） |
| `logo` | `LOGO_DETECTION` | |
| `classify` | `LABEL_DETECTION` | |
| `web` | `WEB_DETECTION` | Web類似画像検索 |

`imageContext`（`languageHints: ["en"]`）は `text` / `label` モードのみに付与（Google公式仕様準拠）。モード一覧は `vision_api.py` の `VALID_MODES` 定数で管理。

### APIレスポンス形式

```json
{"ok": true, "data": [...], "image_size": {...}, "error_code": null, "message": null}
```

- 部分成功時（API部分エラー + 注釈あり）: `ok=true` + `"warnings": ["VISION_14: ..."]`
- 部分エラー + 注釈なし: `ok=false` + `error_code` / `message`
- モード固有フィールド: `label_detected` / `label_reason`（label）、`web_detail`（web）
- エラーコード定数は `app.py` の `ERR_*` で一元管理（例: `ERR_INVALID_FORMAT`, `ERR_RATE_LIMITED`）

### フロントエンド（バニラJS — フレームワーク不使用）

- **`static/script.js`**: カメラ制御、フレーム間差分による静止検知（`requestAnimationFrame`ループ）、ターゲットボックス内クロップ→Base64化→`/api/analyze`へPOST。API使用量はlocalStorageで日次管理。イベントハンドラは`init()`内で`addEventListener`登録（CSP準拠）。
- **`templates/index.html`**: Jinja2テンプレート。CSPノンスを`{{ csp_nonce }}`で受け渡し。
- **`static/style.css`**: Glassmorphism風ダークテーマ。CSS変数でデザイントークン管理。

### セキュリティ構成

- **CSP**: `script-src 'self'`、`style-src 'self' 'nonce-...'`（unsafe-inline排除）。HTTPS環境では`upgrade-insecure-requests`を自動付与
- **HSTS**: HTTPS環境下で`Strict-Transport-Security: max-age=31536000; includeSubDomains`を自動付与
- **CORS**: デフォルト同一オリジンのみ。`ALLOWED_ORIGINS`で明示的に許可
- **相関ID**: 全リクエストに`X-Request-Id`ヘッダー付与（ログと一致）
- **MIME検証**: JPEG/PNGのmagic byte検証（Base64デコード後）
- **レート制限**: Redis原子操作 or インメモリ二重構造（分間+日次）
- **管理APIブルートフォース防御**: 5分間に5回認証失敗でIPブロック（429）
- **Permissions-Policy**: `camera=(self), microphone=()`

### CI/CD

- `.github/workflows/ci.yml`: pytest（Python 3.11/3.12/3.13） + ruff + bandit + pip-audit + osv-scanner + detect-secrets
- `.github/workflows/secrets-scan.yml`: シークレットスキャン
- `.github/dependabot.yml`: pip依存+GitHub Actions週次チェック
- Renderへの自動デプロイ: mainブランチへのpushで `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 30` が起動

## テスト構成

- `tests/test_api.py`: Flaskテストクライアントを使用したAPIエンドポイントテスト（正常OCR / 物体検出 / 不正入力 / API障害 / セキュリティヘッダー / CORS / request-id / MIME検証 / レート制限設定API / ヘルスチェック / ProxyHopsパース）
- `tests/test_vision_api.py`: `vision_api.py`の単体テスト（HTTPエラー、タイムアウト、部分エラー・部分成功、パーサー境界ケース、プロキシ状態4パターン回帰テスト、imageContext制限テスト）
- `tests/e2e/test_ui.py`: Playwright E2Eテスト（ページ読み込み、モード切替、エラー表示、設定API反映検証）
- `tests/conftest.py`: 共通フィクスチャ。`client`フィクスチャ＝Flaskテストクライアント + `reset_for_testing()`でレート制限ステートをリセット
- `tests/helpers.py`: テスト用ヘルパー関数（`create_valid_image_base64` / `create_valid_png_base64` / `make_b64` / `make_mock_response`）

**テスト作成時の注意:**
- 新しいテストは既存の`client`フィクスチャを使用すること（レート制限が自動リセットされる）
- CIでは`VISION_API_KEY=test-dummy-key`で実行される（実APIは呼ばない）
- Vision APIの呼び出しは `unittest.mock.patch` で `requests.Session.post` をモックする

## 重要な設計パターン

### `load_dotenv()` 冪等パターン
各モジュール（`app.py`, `vision_api.py`, `rate_limiter.py`）がそれぞれ `load_dotenv()` を呼ぶ。単体テスト時にモジュールが個別にインポートされても環境変数が確実に読まれるための設計。

### レート制限のクォータ返却
API呼び出しが失敗した場合、`release_request()` で消費済みのクォータを返却する。これによりユーザーの日次上限がAPI障害で無駄に消費されることを防ぐ。

### 環境変数の安全パース
`int()` 変換は `try/except` でフォールバック値を設定する（`_parse_proxy_hops` パターン参照）。

## 環境変数（`.env`）

| 変数 | 必須 | 説明 |
|------|------|------|
| `VISION_API_KEY` | Yes | Google Cloud Vision APIキー |
| `APP_PORT` | No | サーバーポート（デフォルト`5001`） |
| `PROXY_URL` | No | 企業プロキシURL |
| `VERIFY_SSL` | No | SSL検証（デフォルト`true`） |
| `FLASK_DEBUG` | No | デバッグモード（デフォルト`false`） |
| `NO_PROXY_MODE` | No | `true`でプロキシ設定を無視 |
| `ADMIN_SECRET` | No | 管理API認証シークレット（未設定時は管理APIが常に403） |
| `REDIS_URL` | No | Redisレート制限用（未設定=インメモリ） |
| `ALLOWED_ORIGINS` | No | CORS許可Origin（カンマ区切り） |
| `RATE_LIMIT_PER_MINUTE` | No | 分間上限（デフォルト20） |
| `RATE_LIMIT_DAILY` | No | 日次上限（デフォルト1000） |
| `SSL_CERT_PATH` | No | SSL証明書ファイルパス（未設定=HTTP） |
| `SSL_KEY_PATH` | No | SSL秘密鍵ファイルパス（未設定=HTTP） |
| `TRUST_PROXY` | No | リバースプロキシ信頼（デフォルト`false`） |
| `TRUST_PROXY_HOPS` | No | プロキシホップ数（デフォルト`1`、不正値は1にフォールバック） |
| `FLASK_SECRET_KEY` | No | Flask署名付きセッション用秘密鍵（未設定時は警告ログ出力） |

## コーディング規約

- コミット形式: `feat:` / `fix:` / `test:` / `refactor:` / `docs:` / `chore:` + 日本語メッセージ
- コード内コメント・docstringは日本語
- 変数名は英語（ローマ字禁止）
- テスト名は日本語可（例: `test_テキスト抽出が正常に動作する`）
- XSS対策: フロントエンドでは`innerHTML`ではなくDOM操作（`textContent`/`createTextNode`）を使用
- CSP対策: HTML inline属性（onclick, style）禁止 → JSイベントリスナー/CSSクラスを使用
- MVVMや継承パターンは使用しない
