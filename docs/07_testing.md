# テスト仕様書

Vision AI Scanner プロジェクトのテスト戦略、テスト構成、テストケース一覧をまとめた仕様書です。

---

## 目次

1. [テスト戦略](#テスト戦略)
2. [テスト実行方法](#テスト実行方法)
3. [テストクラス一覧](#テストクラス一覧)
   - [APIエンドポイントテスト（test_api.py）](#apiエンドポイントテストtest_apipy)
   - [Vision API単体テスト（test_vision_api.py）](#vision-api単体テストtest_vision_apipy)
   - [E2Eテスト（test_ui.py）](#e2eテストtest_uipy)
4. [テストカバレッジの対象範囲](#テストカバレッジの対象範囲)
5. [モック戦略](#モック戦略)
6. [テストフィクスチャ](#テストフィクスチャ)

---

## テスト戦略

本プロジェクトでは、以下の3層でテストを構成しています。

| レイヤー | 対象ファイル | 役割 | 実行頻度 |
|----------|-------------|------|---------|
| **単体テスト** | `tests/test_vision_api.py` | `vision_api.py` の関数を個別に検証。HTTPエラー、パーサー、ユーティリティ関数のロジックを確認 | CI毎回 |
| **APIテスト（結合テスト）** | `tests/test_api.py` | Flaskテストクライアント経由で `/api/analyze` 等のエンドポイントを検証。バリデーション、セキュリティヘッダー、CORS、レート制限の統合動作を確認 | CI毎回 |
| **E2Eテスト** | `tests/e2e/test_ui.py` | Playwright（Chromium）でブラウザを操作し、DOM構造・モード切替・エラー表示・設定APIとの連携を検証 | CI毎回（Playwright導入環境のみ） |

### テストピラミッドの方針

- **単体テスト**: 最も多くのケースを網羅。外部API呼び出しはすべてモックし、高速に実行
- **APIテスト**: Flaskの `test_client()` を使い、HTTPリクエスト/レスポンスレベルで動作を確認
- **E2Eテスト**: カメラ機能はCI環境で利用不可のため、DOM構造・UI操作・エラーハンドリングに限定。Playwright未インストール時は自動スキップ

---

## テスト実行方法

### 前提条件

```bash
# 仮想環境の有効化（Windows PowerShell）
venv\Scripts\Activate.ps1

# テスト用依存ライブラリのインストール
pip install -r requirements-dev.txt

# E2Eテスト用ブラウザのインストール（任意）
playwright install chromium
```

### テスト実行コマンド

```bash
# 全テスト実行（E2E含む）
pytest tests/ -v

# APIエンドポイントテストのみ
pytest tests/test_api.py -v

# Vision API単体テストのみ
pytest tests/test_vision_api.py -v

# E2Eテストのみ
pytest tests/e2e/ -v

# 特定テストクラスの実行
pytest tests/test_api.py::TestInvalidInput -v

# 特定テストメソッドの実行
pytest tests/test_api.py::TestInvalidInput::test_不正なモードを拒否する -v

# カバレッジレポート付きで実行
pytest tests/ -v --cov=. --cov-report=html
```

---

## テストクラス一覧

### APIエンドポイントテスト（test_api.py）

`app.py` のFlaskエンドポイントをテストクライアント経由で検証します。正常系、不正入力、API障害、セキュリティ、レート制限、ヘルスチェックの6系統をカバーします。

#### TestTextDetection（テキスト抽出の正常系）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_テキスト抽出が正常に動作する` | 有効なJPEG画像 + `mode=text` でHTTP 200、`ok=True`、`data` に検出テキスト2件が返ること |

#### TestObjectDetection（物体検出の正常系）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_物体検出が正常に動作する` | 有効なJPEG画像 + `mode=object` でHTTP 200、`ok=True`、`data` に物体ラベル（日本語訳付き）2件が返ること |

#### TestInvalidInput（不正入力のバリデーション）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_JSONでないリクエストを拒否する` | Content-Type が `text/plain` の場合にHTTP 400、`error_code=INVALID_FORMAT` |
| `test_画像データがないリクエストを拒否する` | `image` フィールドが欠落している場合にHTTP 400、`error_code=MISSING_IMAGE` |
| `test_不正なモードを拒否する` | `mode` が `text`/`object` 以外の場合にHTTP 400、`error_code=INVALID_MODE` |
| `test_不正なBase64を拒否する` | Base64デコード不可能な文字列でHTTP 400、`error_code=INVALID_BASE64` |
| `test_大きすぎる画像を拒否する` | 6MBのデータでHTTP 400、`error_code=IMAGE_TOO_LARGE` |
| `test_Nullの画像を拒否する` | `image: null` でHTTP 400、`error_code=MISSING_IMAGE` |
| `test_空文字の画像を拒否する` | `image: "   "` でHTTP 400、`error_code=MISSING_IMAGE` |
| `test_JSONが配列のリクエストを拒否する` | JSONボディが配列の場合にHTTP 400、`error_code=INVALID_FORMAT` |
| `test_壊れたJSONでもJSON形式のエラーを返す` | Content-Type が `application/json` だが本文が不正JSONの場合にHTTP 400、JSONエラーレスポンスが返ること |

#### TestImageFormatValidation（画像フォーマット検証）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_不正なフォーマットを拒否する` | GIF magic byte のバイナリでHTTP 400、`error_code=INVALID_IMAGE_FORMAT` |
| `test_JPEG画像を受け入れる` | JPEG magic byte 画像でHTTP 200 |
| `test_PNG画像を受け入れる` | PNG magic byte 画像でHTTP 200 |
| `test_テキストデータを拒否する` | プレーンテキストのBase64でHTTP 400、`error_code=INVALID_IMAGE_FORMAT` |

#### TestApiFailure（Vision API障害時の動作）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_API障害時にエラーレスポンスを返す` | `detect_content` が `ok=False` を返した場合にHTTP 502、`error_code=API_500` |
| `test_サーバー例外時に500を返す` | `detect_content` が `RuntimeError` を投げた場合にHTTP 500、`error_code=SERVER_ERROR` |

#### TestProxySecurity（プロキシAPI認証・情報漏えい防止）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_プロキシGETにconfigured_urlが含まれない` | GETレスポンスに `configured_url` フィールドが含まれないこと（情報漏えい防止） |
| `test_認証なしのプロキシPOSTは403を返す` | `X-Admin-Secret` ヘッダーなしでHTTP 403、`error_code=UNAUTHORIZED` |
| `test_不正なシークレットでは403を返す` | 誤ったシークレットでHTTP 403 |
| `test_正しいシークレットでプロキシを更新できる` | 正しいシークレットでHTTP 200、`ok=True` |
| `test_enabled文字列falseは型エラーを返す` | `enabled: "false"`（文字列）でHTTP 400、`error_code=INVALID_TYPE`（`bool("false")==True` バグの防止） |

#### TestRateLimitAtomicity（レート制限のアトミック性）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_API失敗時にレート制限カウントが戻る` | API失敗後に `get_daily_count` が0であること（`release_request` で予約取消） |
| `test_例外発生時もレート制限カウントが戻る` | 例外発生後もカウントが0に戻ること |

#### TestErrorHandlers（Flask例外ハンドラ）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_413エラーがJSONで返る` | `MAX_CONTENT_LENGTH` 超過時にHTTP 413、`error_code=REQUEST_TOO_LARGE` のJSON応答 |

#### TestProxyGetAuth（プロキシGETの認証レベル）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_未認証GETではURL情報が含まれない` | 認証なしGETで `enabled` のみ返し、`url` フィールドは含まれないこと |
| `test_認証済みGETではURL情報が含まれる` | 認証ありGETで `url` フィールドも含まれること |

#### TestProxyMalformedInput（プロキシPOSTの不正入力）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_壊れたJSONでプロキシPOSTは400を返す` | 壊れたJSONボディでHTTP 400、`error_code=INVALID_FORMAT` |

#### TestSecurityHeaders（セキュリティヘッダー）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_CSPヘッダが存在する` | レスポンスに `Content-Security-Policy` が含まれ、`default-src 'self'` が設定されていること |
| `test_CSPにunsafe_inlineが含まれない` | CSPに `'unsafe-inline'` が含まれないこと（nonce化済み） |
| `test_CSPにノンスが含まれる` | CSPの `style-src` に `nonce-` 値が含まれること |
| `test_レガシーXSSヘッダが存在しない` | `X-XSS-Protection` ヘッダーが含まれないこと |

#### TestRequestId（リクエスト相関ID）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_レスポンスにX_Request_Idヘッダーが含まれる` | 全レスポンスに `X-Request-Id`（16文字）が付与されること |
| `test_リクエストごとに異なるIDが生成される` | 連続リクエストで異なるIDが割り当てられること |
| `test_APIレスポンスにもX_Request_Idが含まれる` | `/api/analyze` のレスポンスにもIDが含まれること |

#### TestCors（CORSヘッダー）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_デフォルトではCORSヘッダーが付かない` | `ALLOWED_ORIGINS` 未設定時に `Access-Control-Allow-Origin` が付かないこと |
| `test_許可されたOriginにCORSヘッダーが付く` | 許可されたOriginに `Access-Control-Allow-Origin` が付与されること |
| `test_許可されていないOriginにはCORSヘッダーが付かない` | 許可されていないOriginにはCORSヘッダーが付かないこと |

#### TestRateLimitsConfig（レート制限設定API）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_日次上限値が取得できる` | `GET /api/config/limits` が `daily_limit`（正の整数）を返すこと |
| `test_環境変数で変更した上限値が反映される` | `RATE_LIMIT_DAILY=50` 設定時に `/api/config/limits` に反映されること |

#### TestHealthChecks（ヘルスチェック）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_healthzが200を返す` | `GET /healthz` が常にHTTP 200、`status=ok` を返すこと |
| `test_readyzがAPIキー設定済みで200を返す` | `VISION_API_KEY` 設定済みで `/readyz` がHTTP 200、全チェック項目がOK |
| `test_readyzがAPIキー未設定で503を返す` | `API_KEY` 空で `/readyz` がHTTP 503、`api_key_configured=False` |
| `test_readyzがRedisフォールバック時に503を返す` | `REDIS_URL` 設定済みでインメモリフォールバック時にHTTP 503 + Redis警告 |
| `test_readyzがRedis未設定のインメモリは正常扱い` | `REDIS_URL` 未設定でインメモリの場合はHTTP 200（意図的なので正常） |

#### TestAdminSecretCheck（ADMIN_SECRET強度検証）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_未設定は未設定警告のみ` | 空文字の場合は「未設定」警告1件のみ |
| `test_短すぎる値は長さ警告` | 16文字未満で「短すぎ」警告が出ること |
| `test_低エントロピー値はエントロピー警告` | 文字種が2種以下で「エントロピー」警告が出ること |
| `test_高エントロピー値は警告なし` | 十分な長さ・文字種のランダム値で警告が出ないこと |

---

### Vision API単体テスト（test_vision_api.py）

`vision_api.py` の関数を直接テストします。HTTPセッションのモック、パーサーの境界値テスト、ユーティリティ関数のテストを含みます。

#### TestDetectContentValidation（detect_content のバリデーション）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_不正なmodeはValueErrorを投げる` | `mode="invalid"` で `ValueError("不正なモード")` が発生すること |
| `test_APIキー未設定はValueErrorを投げる` | `API_KEY=None` で `ValueError("APIキーが未設定")` が発生すること |

#### TestDetectContentHttpErrors（HTTPエラーハンドリング）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_HTTP500はokFalseを返す` | Vision APIがHTTP 500を返した場合に `ok=False, error_code=API_500` |
| `test_タイムアウトはokFalseを返す` | `Timeout` 例外で `ok=False, error_code=TIMEOUT` |
| `test_接続エラーはokFalseを返す` | `ConnectionError` 例外で `ok=False, error_code=CONNECTION_ERROR` |
| `test_その他通信エラーはokFalseを返す` | `RequestException` 例外で `ok=False, error_code=REQUEST_ERROR` |

#### TestDetectContentPartialError（Vision API部分エラー）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_部分エラーはokFalseを返す` | HTTP 200だが `responses[0].error` がある場合に `ok=False, error_code=VISION_400` |

#### TestParsers（パーサーの境界ケース）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_テキストレスポンスが空の場合空タプルを返す` | `textAnnotations` がない/空の場合に `([], None)` を返すこと |
| `test_テキストレスポンスが個別アノテーションをパースする` | `textAnnotations[1:]` から各テキストのラベル・座標を正しくパースすること |
| `test_fullTextAnnotation優先で正確な画像サイズを取得する` | `fullTextAnnotation.pages[0]` の `width/height` を優先して使用すること |
| `test_テキストレスポンスが空文字アノテーションを除外する` | 空文字・空白の `description` が除外されること |
| `test_物体レスポンスが空の場合空リストを返す` | `localizedObjectAnnotations` がない/空の場合に `[]` を返すこと |
| `test_物体ラベルに日本語訳がない場合英語のみ表示` | 翻訳辞書にないラベルは英語のみで表示（`（` 括弧なし） |

#### TestMaskProxyUrl（プロキシURLマスク）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_認証情報付きURLがマスクされる` | `user:pass@host` 形式で認証部分が `***:***@host` にマスクされること |
| `test_認証情報なしURLはそのまま返す` | 認証情報がないURLはマスクせずそのまま返すこと |
| `test_空文字はそのまま返す` | 空文字はそのまま返すこと |
| `test_Noneはそのまま返す` | `None` はそのまま返すこと |

#### TestImageSafetyCheck（画像安全チェック）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_ValueError時はdetect_contentがValueErrorを伝播する` | `preprocess_image` が `ValueError` を投げた場合にAPI呼び出しせず伝播すること |
| `test_非ValueErrorの前処理エラーはスキップしてAPI呼び出しを続行する` | `OSError` 等はスキップしてAPI呼び出しを続行すること |

#### TestGetProxyStatus（プロキシステータス4パターン回帰テスト）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_プロキシURL有りでNO_PROXY_MODE無効ならenabled` | `PROXY_URL` 設定済み + `NO_PROXY_MODE=false` で `enabled=True` |
| `test_プロキシURL有りでNO_PROXY_MODE有効ならdisabled` | `PROXY_URL` 設定済み + `NO_PROXY_MODE=true` で `enabled=False` |
| `test_プロキシURL空でNO_PROXY_MODE無効ならdisabled` | `PROXY_URL` 未設定 + `NO_PROXY_MODE=false` で `enabled=False` |
| `test_プロキシURL空でNO_PROXY_MODE有効ならdisabled` | `PROXY_URL` 未設定 + `NO_PROXY_MODE=true` で `enabled=False` |
| `test_認証情報付きURLはマスクされる` | 認証情報付きURLが `get_proxy_status` で漏えいしないこと |

---

### E2Eテスト（test_ui.py）

Playwrightを使用したブラウザレベルのUI動作検証です。カメラ機能はCI環境で利用不可のため、DOM構造・モード切替・エラー表示・設定APIとの連携に限定しています。

#### TestPageLoad（ページ読み込みと初期状態）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_ページが正常に読み込まれる` | ページタイトルに「Vision AI Scanner」が含まれること |
| `test_全UIコントロールが存在する` | `#btn-scan`, `#btn-camera`, `#btn-file`, `#mode-text`, `#mode-object`, `#result-list`, `#api-counter` がすべて表示されていること |
| `test_CSPヘッダーにunsafe_inlineが含まれない` | レスポンスヘッダーのCSPに `'unsafe-inline'` が含まれないこと |

#### TestModeSwitch（モード切替のUI動作）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_テキストモードがデフォルトでアクティブ` | 初期状態で `#mode-text` が `active` クラスを持つこと |
| `test_物体モードに切り替えできる` | `#mode-object` クリック後にクラスが切り替わること |
| `test_モード切替で結果リストがリセットされる` | モード切替時にプレースホルダーテキスト（「スキャン」を含む）に戻ること |

#### TestErrorDisplay（エラー時のUI表示）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_APIエラーレスポンスをJSONで受け取れる` | `image` なしリクエストでJSON `error_code=MISSING_IMAGE` が返ること |
| `test_不正フォーマットにJSONエラーが返る` | 非JSONリクエストでJSON `error_code=INVALID_FORMAT` が返ること |

#### TestConfigEndpoints（設定APIエンドポイントのE2E検証）

| テストケース名 | 検証内容 |
|---------------|---------|
| `test_APIカウンタにサーバー上限値が反映される` | `loadRateLimits()` 完了後にAPIカウンタが `API: 数字/数字` 形式になること |
| `test_Proxyバッジに設定状態が表示される` | `loadProxyConfig()` 完了後にProxy設定バッジが `ON` または `OFF` を表示すること |

---

## テストカバレッジの対象範囲

### バックエンド

| モジュール | テスト対象範囲 |
|-----------|---------------|
| `app.py` | 全エンドポイント（`/api/analyze`, `/api/config/proxy`, `/api/config/limits`, `/healthz`, `/readyz`）、バリデーション、セキュリティヘッダー、CORS、レート制限、エラーハンドラ |
| `vision_api.py` | `detect_content()`、`_parse_text_response()`、`_parse_object_response()`、`_mask_proxy_url()`、`preprocess_image()`、`get_proxy_status()` |
| `rate_limiter.py` | `try_consume_request()` / `release_request()` のアトミック性（`test_api.py` 経由で間接検証） |

### フロントエンド（E2Eで間接検証）

| コンポーネント | テスト対象範囲 |
|---------------|---------------|
| DOM構造 | 全UIコントロールの存在確認 |
| モード切替 | テキスト/物体モードの切り替えとクラス状態 |
| 設定API連携 | APIカウンタ・Proxy設定バッジの動的更新 |
| エラーハンドリング | 不正リクエスト時のJSONエラーレスポンス処理 |

### テスト対象外

- カメラ映像のキャプチャ処理（CI環境でカメラ利用不可）
- requestAnimationFrame ベースの安定化検出ループ
- localStorage の永続化（ブラウザAPI依存）
- Google Cloud Vision API の実呼び出し（常にモック）

---

## モック戦略

### 使用ツール

- **`unittest.mock.patch`**: 標準ライブラリのモック機構を使用
- **`unittest.mock.MagicMock`**: レスポンスオブジェクト等の汎用モック

### モック対象と方針

| モック対象 | パッチ先 | 理由 |
|-----------|---------|------|
| `detect_content()` | `app.detect_content` | Vision API実呼び出しを回避し、正常/異常レスポンスを制御 |
| `session.post()` | `vision_api.session.post` | HTTPリクエストを模擬し、タイムアウト・接続エラー等を再現 |
| `preprocess_image()` | `vision_api.preprocess_image` | 画像前処理のエラーパスを検証 |
| `ADMIN_SECRET` | `app.ADMIN_SECRET` | テスト用のシークレット値を注入 |
| `API_KEY` | `app.API_KEY` | APIキー未設定状態を再現 |
| `ALLOWED_ORIGINS` | `app.ALLOWED_ORIGINS` | CORS設定を動的に変更 |
| `RATE_LIMIT_DAILY` | `app.RATE_LIMIT_DAILY` | レート制限値を変更してテスト |
| `REDIS_URL` | `app.REDIS_URL` | Redis接続状態を制御 |
| `get_backend_type()` | `app.get_backend_type` | レート制限バックエンド種別を制御 |
| `NO_PROXY_MODE` | `vision_api.NO_PROXY_MODE` | プロキシモードを切り替え |
| `_RAW_PROXY_URL` | `vision_api._RAW_PROXY_URL` | プロキシURLを差し替え |

### モック設計の原則

1. **最小限のモック**: テスト対象以外の外部依存のみをモックする
2. **返り値の厳密な定義**: `detect_content` のモック返り値は実際のレスポンス形式（`ok`, `data`, `image_size`, `error_code`, `message`）に厳密に一致させる
3. **副作用の検証**: `mock_post.assert_not_called()` や `mock_post.assert_called_once()` で呼び出し有無を検証
4. **`patch.dict` の活用**: 環境変数の差し替えに `@patch.dict("os.environ", ...)` を使用

---

## テストフィクスチャ

### 共通フィクスチャ（tests/conftest.py）

| フィクスチャ/ヘルパー | 種類 | 説明 |
|---------------------|------|------|
| `client` | pytest fixture | Flaskテストクライアントを作成。テスト間でレート制限ステートを `reset_for_testing()` でリセットし、`app.config["TESTING"] = True` を設定 |
| `create_valid_image_base64()` | ヘルパー関数 | テスト用の最小限の有効なJPEG画像（1x1ピクセル）をBase64エンコードして返す |
| `create_valid_png_base64()` | ヘルパー関数 | テスト用の最小限の有効なPNG画像（1x1ピクセル、赤色）をBase64エンコードして返す |
| `make_b64(data)` | ヘルパー関数 | 任意のバイトデータを最小限のBase64文字列に変換。デフォルトはJPEG SOI+EOIマーカー `\xff\xd8\xff\xd9` |
| `make_mock_response(status_code, json_data)` | ヘルパー関数 | `requests.Response` のモックオブジェクトを生成。`status_code` と `json()` の返り値を設定 |

### E2Eフィクスチャ（tests/e2e/conftest.py）

| フィクスチャ | スコープ | 説明 |
|------------|---------|------|
| `live_server` | session | Flaskアプリをポート5099でバックグラウンドスレッド起動。`daemon=True` でプロセス終了時に自動停止。1秒の起動待ちを含む。`http://127.0.0.1:5099` をyield |
| `page` | function | Playwright Chromium（ヘッドレス）のページオブジェクト。テストごとにブラウザコンテキストを新規作成し、`live_server` URLに遷移した状態でyield。テスト終了時にブラウザを閉じる |

### フィクスチャの依存関係

```
live_server (session scope)
  └── page (function scope)
        └── 各E2Eテストケース

client (function scope)
  └── 各APIテスト / Vision APIテストケース
```

### 自動スキップ機構

E2Eテストファイル（`test_ui.py` および `conftest.py`）の先頭で以下を実行しています。

```python
pytest.importorskip("playwright")
```

これにより、Playwrightが未インストールの環境ではE2Eテスト全体が自動的にスキップされ、CIの失敗を防ぎます。
