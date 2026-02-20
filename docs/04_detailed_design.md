# 詳細設計書（プログラム詳細設計） - Vision AI Scanner

| 項目 | 内容 |
|------|------|
| ドキュメント名 | 詳細設計書 |
| プロジェクト名 | Vision AI Scanner |
| 公開URL | https://vision-scanner.onrender.com/ |
| バージョン | 1.0 |
| 最終更新日 | 2026-02-20 |

---

## 1. ドキュメント構成

本書はシステムを構成する各モジュールの内部設計を記述する。

| モジュール | ファイル | 責務 |
|-----------|---------|------|
| メインアプリケーション | `app.py` | ルーティング、バリデーション、セキュリティ、ミドルウェア |
| Vision APIクライアント | `vision_api.py` | Google Cloud Vision API呼び出し、画像前処理、レスポンス解析 |
| レート制限 | `rate_limiter.py` | IP単位の分間/日次レート制限（Redis / インメモリ二重構造） |
| 翻訳辞書 | `translations.py` | 物体検出ラベルの英日翻訳マッピング |
| フロントエンド | `static/script.js` | カメラ制御、静止検知、画像クロップ、API通信、結果描画 |
| スタイル | `static/style.css` | Glassmorphismダークテーマ、レスポンシブデザイン |
| テンプレート | `templates/index.html` | Jinja2テンプレート、CSPノンス受け渡し |

---

## 2. app.py — メインアプリケーション

### 2.1 モジュール概要

Flaskアプリケーションのエントリーポイント。リクエストの受信からバリデーション、セキュリティヘッダー付与、レート制限チェック、Vision API呼び出しの委譲までを担当する。ビジネスロジックは持たず、「薄いコントローラー」として振る舞う。

### 2.2 定数定義

| 定数名 | 値 | 説明 |
|--------|-----|------|
| `FLASK_DEBUG` | 環境変数（デフォルト `false`） | デバッグモード |
| `MAX_IMAGE_SIZE` | `5 * 1024 * 1024`（5MB） | Base64デコード後の画像サイズ上限 |
| `MAX_REQUEST_BODY` | `10 * 1024 * 1024`（10MB） | リクエストボディ全体のサイズ上限 |
| `ADMIN_SECRET` | 環境変数 | 管理API認証用シークレット |
| `ALLOWED_ORIGINS` | 環境変数（カンマ区切り） | CORS許可Origin一覧 |
| `ALLOWED_IMAGE_MAGIC` | `{b"\xff\xd8\xff": "image/jpeg", b"\x89PNG...": "image/png"}` | 許可するMIMEマジックバイト |
| `TRUST_PROXY` | 環境変数（デフォルト `false`） | リバースプロキシ信頼設定 |

### 2.3 関数一覧

#### `_check_admin_secret(secret) → list[str]`

**責務**: ADMIN_SECRETの強度を検証し、警告メッセージを返す。

| チェック項目 | 条件 | 警告内容 |
|-------------|------|---------|
| 未設定 | `secret` が空文字 | 管理APIが常に403を返す旨を通知 |
| 長さ不足 | 16文字未満 | 16文字以上を推奨 |
| 低エントロピー | 文字種3種未満（大文字/小文字/数字/記号） | ランダム生成を推奨 |

#### `set_request_context() → None`

**責務**: `@app.before_request` フック。すべてのリクエストに対して以下を生成する。

| 属性 | 生成方法 | 用途 |
|------|---------|------|
| `g.request_id` | `secrets.token_hex(8)` — 16文字の16進数文字列 | ログ・レスポンスヘッダーでの相関ID |
| `g.csp_nonce` | `secrets.token_urlsafe(16)` — URL安全なBase64文字列 | CSP nonce値（`<style>`タグに付与） |

#### `add_security_headers(response) → Response`

**責務**: `@app.after_request` フック。全レスポンスにセキュリティヘッダーを付与する。

| ヘッダー | 値 | 目的 |
|---------|-----|------|
| `X-Content-Type-Options` | `nosniff` | MIMEスニッフィング防止 |
| `X-Frame-Options` | `DENY` | クリックジャッキング防止 |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | リファラー情報漏洩防止 |
| `Content-Security-Policy` | nonce化CSP（後述） | XSS防止 |
| `Permissions-Policy` | `camera=(self), microphone=(self)` | カメラ/マイクを同一オリジンに限定 |
| `Cache-Control` | `no-store, no-cache, must-revalidate, max-age=0` | キャッシュ無効化 |
| `X-Request-Id` | `g.request_id` の値 | 障害調査用の相関ID |

**CSPポリシー詳細**:

```
default-src 'self';
script-src 'self';
style-src 'self' 'nonce-{nonce}' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' blob: data:;
media-src 'self' blob: mediastream:;
connect-src 'self'
```

#### `_validate_image_format(decoded_bytes) → bool`

**責務**: デコード済みバイト列の先頭バイトを `ALLOWED_IMAGE_MAGIC` と照合し、JPEG/PNGかを判定する。

**処理フロー**:
1. `ALLOWED_IMAGE_MAGIC` の各マジックバイトとデコード済みバイト列の先頭を比較
2. いずれかに一致すれば `True`、すべて不一致なら `False`

#### `_error_response(error_code, message, status_code=400) → tuple`

**責務**: 統一エラーレスポンスを生成する。

**レスポンス形式**:
```json
{
  "ok": false,
  "data": [],
  "error_code": "<error_code>",
  "message": "<message>"
}
```

#### `_validate_analyze_request() → tuple`

**責務**: `/api/analyze` のリクエストボディを段階的に検証する。

**バリデーションフロー**:

```
1. Content-Type が JSON か → INVALID_FORMAT
2. JSONパース可能か → INVALID_FORMAT
3. JSONオブジェクトか → INVALID_FORMAT
4. image フィールド存在・文字列・非空か → MISSING_IMAGE
5. mode が {"text", "object"} に含まれるか → INVALID_MODE
6. data:image/...;base64, プレフィックス除去
7. Base64デコード可能か → INVALID_BASE64
8. デコード後サイズ ≤ 5MB か → IMAGE_TOO_LARGE
9. マジックバイトが JPEG/PNG か → INVALID_IMAGE_FORMAT
```

**成功時**: `(image_data, mode, None)` を返す
**失敗時**: `(None, None, error_response)` を返す

#### `analyze_endpoint() → Response`

**責務**: メインAPIエンドポイント `POST /api/analyze` のハンドラ。

**処理シーケンス**:

```
[リクエスト受信]
    │
    ▼
[_validate_analyze_request()]
    │ 失敗 → エラーレスポンス返却
    ▼
[try_consume_request(client_ip)]
    │ 制限中 → 429 レスポンス返却
    ▼
[detect_content(image_data, mode)]
    │ 成功 → 200 レスポンス返却
    │ 失敗 → release_request() → 502 レスポンス返却
    │ ValueError → release_request() → 400 レスポンス返却
    │ Exception → release_request() → 500 レスポンス返却
    ▼
[レスポンス返却]
```

**重要な設計判断**: API呼び出し失敗時は `release_request()` でレート制限の予約を取り消し、ユーザーのクォータを消費しない。

#### `healthz() → Response`

**責務**: Liveness ヘルスチェック。アプリケーションの起動確認（依存サービス不要）。

**レスポンス**: `{"status": "ok"}` — 常に200を返す。

#### `readyz() → Response`

**責務**: Readiness ヘルスチェック。リクエスト処理可能かを判定する。

**チェック項目**:

| チェック | 条件 | 不合格時の影響 |
|---------|------|--------------|
| `api_key_configured` | `VISION_API_KEY` が設定済み | 503を返す |
| `rate_limiter_ok` | Redis設定時にフォールバックしていない | 503 + 警告メッセージ |

---

## 3. vision_api.py — Vision APIクライアント

### 3.1 モジュール概要

Google Cloud Vision APIとの通信を一手に担うモジュール。画像前処理、APIリクエスト構築、レスポンス解析、エラーハンドリング、リトライ制御を内包する。

### 3.2 定数定義

| 定数名 | 値 | 説明 |
|--------|-----|------|
| `API_KEY` | 環境変数 `VISION_API_KEY` | Google Cloud Vision APIキー |
| `API_BASE_URL` | `https://vision.googleapis.com/v1/images:annotate` | APIエンドポイント |
| `NO_PROXY_MODE` | 環境変数（デフォルト `false`） | プロキシ無視フラグ |
| `VERIFY_SSL` | 環境変数（デフォルト `true`） | SSL証明書検証 |
| `VALID_MODES` | `{"text", "object"}` | 許可される解析モード |
| `FEATURE_TYPES` | `{"text": "DOCUMENT_TEXT_DETECTION", "object": "OBJECT_LOCALIZATION"}` | モードとAPIフィーチャーの対応 |
| `MAX_RESULTS` | `10` | APIが返す最大結果数 |
| `LANGUAGE_HINTS` | `["en", "ja"]` | OCR言語ヒント（優先順） |
| `API_TIMEOUT_SECONDS` | `15` | リクエストタイムアウト（秒） |
| `MAX_IMAGE_PIXELS` | `20,000,000` | 最大許容ピクセル数（約80MB RAM相当） |
| `CONTRAST_FACTOR` | `1.5` | コントラスト強調係数 |
| `SHARPNESS_FACTOR` | `1.5` | シャープネス強調係数 |
| `JPEG_QUALITY` | `95` | JPEG保存品質 |

### 3.3 HTTPセッション設計

モジュールレベルで `requests.Session` を1つ作成し、全リクエストで共有する。

**リトライ戦略**:

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `total` | 3 | 最大リトライ回数 |
| `connect` | 3 | 接続リトライ回数 |
| `backoff_factor` | 0.5 | 指数バックオフ係数（0.5s → 1s → 2s） |
| `status_forcelist` | `[429, 500, 502, 503]` | リトライ対象HTTPステータス |
| `allowed_methods` | `["POST"]` | リトライ対象HTTPメソッド |

### 3.4 関数一覧

#### `preprocess_image(image_base64) → str`

**責務**: OCR精度向上のための画像前処理。

**処理フロー**:

```
[Base64デコード]
    │
    ▼
[Pillow で画像読み込み]
    │
    ▼
[ピクセル数チェック（≤ 20,000,000px）]
    │ 超過 → ValueError 送出
    ▼
[RGBA/CMYK → RGB 変換]
    │
    ▼
[コントラスト強調（×1.5）]
    │
    ▼
[シャープネス強調（×1.5）]
    │
    ▼
[JPEG形式で再エンコード（品質95）]
    │
    ▼
[Base64文字列として返却]
```

**設計根拠**: カメラ映像は照明条件が一定でないため、コントラストとシャープネスを軽く強調することでOCR精度が向上する。過度な強調はノイズ増幅につながるため、係数1.5に留めている。

#### `detect_content(image_b64, mode, request_id) → dict`

**責務**: Vision APIの単一エントリーポイント。モードに応じてテキスト抽出または物体検出を行う。

**APIリクエスト構造**:

```json
{
  "requests": [{
    "image": {"content": "<Base64画像>"},
    "features": [{"type": "<FEATURE_TYPE>", "maxResults": 10}],
    "imageContext": {"languageHints": ["en", "ja"]}
  }]
}
```

**認証方式**: APIキーは `x-goog-api-key` ヘッダーで送信（URLパラメータだとプロキシログに記録されるリスクを回避）。

**レスポンス形式**:

```json
{
  "ok": true,
  "data": [{"label": "検出テキスト", "bounds": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]}],
  "image_size": [width, height],
  "error_code": null,
  "message": null
}
```

**エラーハンドリング階層**:

| 例外/条件 | error_code | HTTPステータス |
|-----------|-----------|---------------|
| APIキー未設定 | — | ValueError送出（呼び出し元で処理） |
| HTTPステータス ≠ 200 | `API_{status}` | 呼び出し元で502 |
| responses[0].error あり | `VISION_{code}` | 呼び出し元で502 |
| `requests.Timeout` | `TIMEOUT` | 呼び出し元で502 |
| `requests.ConnectionError` | `CONNECTION_ERROR` | 呼び出し元で502 |
| その他の通信エラー | `REQUEST_ERROR` | 呼び出し元で502 |

#### `_parse_text_response(response_data) → tuple[list, list|None]`

**責務**: テキスト検出（`DOCUMENT_TEXT_DETECTION`）のレスポンスを解析する。

**解析ロジック**:

1. **画像サイズ取得**（優先順位）:
   - `fullTextAnnotation.pages[0].width/height`（API提供の正確な値）
   - `textAnnotations[0].boundingPoly.vertices` の最大x/y（フォールバック推定）
2. **テキストブロック抽出**: `textAnnotations[1:]`（インデックス0は全文テキストのため除外）
3. **各ブロック**: `label`（テキスト内容）と `bounds`（4頂点のピクセル座標）を返す

**返却形式**: `(data_list, image_size)`
- `data_list`: `[{"label": str, "bounds": [[x,y], ...]}, ...]`
- `image_size`: `[width, height]` または `None`

#### `_parse_object_response(response_data) → list`

**責務**: 物体検出（`OBJECT_LOCALIZATION`）のレスポンスを解析する。

**解析ロジック**:

1. `localizedObjectAnnotations` から各物体を抽出
2. 英語ラベルを `OBJECT_TRANSLATIONS` で日本語に変換
3. ラベル形式: `"English（日本語）- 95%"` または `"English - 95%"`（翻訳なし時）
4. 座標: `normalizedVertices`（0〜1の正規化座標）

#### `get_proxy_status() → dict`

**責務**: 現在のプロキシ設定状態を返す。認証情報はマスクして返却する。

#### `set_proxy_enabled(enabled) → None`

**責務**: プロキシの有効/無効を実行時に切り替える。`_proxy_lock` でスレッドセーフに操作する。

---

## 4. rate_limiter.py — レート制限モジュール

### 4.1 モジュール概要

IP単位の分間/日次レート制限を提供する。Redis接続時はLuaスクリプトによる原子操作（マルチプロセス安全）、未接続時はインメモリ（TTLCache）にフォールバックする二重構造。

### 4.2 定数定義

| 定数名 | デフォルト値 | 説明 |
|--------|-------------|------|
| `REDIS_URL` | 環境変数（未設定時=インメモリ） | Redis接続URL |
| `RATE_LIMIT_PER_MINUTE` | `20` | IP単位の分間リクエスト上限 |
| `RATE_LIMIT_DAILY` | `1000` | IP単位の日次リクエスト上限 |

### 4.3 バックエンド選択ロジック

```
[起動時]
    │
    ▼
[REDIS_URL 環境変数の確認]
    │ 設定あり → Redis接続試行
    │             │ 成功 → RedisRateLimiter を使用
    │             │ 失敗 → InMemoryRateLimiter にフォールバック（警告ログ出力）
    │ 設定なし → InMemoryRateLimiter を使用
    ▼
[シングルトンとして _backend に保持]
```

### 4.4 クラス設計

#### `RedisRateLimiter`

**責務**: Redisを用いたマルチプロセス安全なレート制限。

**Luaスクリプト — `_LUA_CONSUME`（チェック＆予約の原子操作）**:

```
1. 分間ウィンドウから60秒超のエントリを削除（ZREMRANGEBYSCORE）
2. 日次カウントを取得し、上限チェック
3. 分間エントリ数を取得し、上限チェック
4. 予約を追加（ZADD + INCR）
5. 日次キーのTTLが未設定なら翌日0時までのTTLを設定
```

**Luaスクリプト — `_LUA_RELEASE`（予約取り消し）**:

```
1. 指定IDの分間エントリを削除（ZREM）
2. 削除成功時、日次カウントをデクリメント（DECR）
```

**Redisキー設計**:

| キー名 | 型 | TTL | 用途 |
|--------|-----|-----|------|
| `rate:minute:{ip}` | Sorted Set（スコア=タイムスタンプ） | 90秒 | 分間スライディングウィンドウ |
| `rate:daily:{ip}:{date}` | String（カウンター） | 翌日0時まで | 日次カウンター |

#### `InMemoryRateLimiter`

**責務**: シングルプロセス用のフォールバックレート制限。

**内部データ構造**:

| フィールド | 型 | TTL | 用途 |
|-----------|-----|-----|------|
| `_rate_store` | `TTLCache(maxsize=10000, ttl=90)` | 90秒 | 分間エントリ格納 |
| `_daily_store` | `TTLCache(maxsize=10000, ttl=86400)` | 24時間 | 日次カウンター |
| `_lock` | `threading.Lock` | — | スレッド排他制御 |

**スレッドセーフ設計**: `try_consume()` と `release()` は `with self._lock:` で保護される。

### 4.5 公開API

| 関数名 | 引数 | 返却値 | 説明 |
|--------|------|--------|------|
| `try_consume_request(ip)` | クライアントIP | `(limited, message, request_id)` | 制限チェック＆予約 |
| `release_request(ip, request_id)` | クライアントIP, リクエストID | なし | 予約取り消し（API失敗時） |
| `get_daily_count(ip)` | クライアントIP | `int` | 日次カウント取得 |
| `get_backend_type()` | なし | `"redis"` or `"in_memory"` | 現在のバックエンド種別 |
| `reset_for_testing()` | なし | なし | テスト用: バックエンドをリセット |

---

## 5. translations.py — 翻訳辞書モジュール

### 5.1 モジュール概要

物体検出で返される英語ラベルを日本語に変換するための辞書を提供する。

### 5.2 定数

| 定数名 | 型 | 説明 |
|--------|-----|------|
| `OBJECT_TRANSLATIONS` | `dict[str, str]` | 英語ラベル（小文字）→ 日本語ラベルのマッピング |

**使用箇所**: `vision_api._parse_object_response()` でラベル変換に使用。

---

## 6. static/script.js — フロントエンド

### 6.1 モジュール概要

カメラ制御、静止検知、画像クロップ、API通信、結果描画を担当するフロントエンドスクリプト。フレームワーク不使用のバニラJavaScriptで実装。

### 6.2 主要機能フロー

#### カメラ起動〜解析の全体フロー

```
[ページ読み込み]
    │
    ▼
[init() — イベントリスナー登録]
    │
    ▼
[startCamera() — getUserMedia() でカメラストリーム取得]
    │
    ▼
[requestAnimationFrame ループ開始]
    │
    ▼
[フレーム間差分で静止検知]──→ 動いている → ループ継続
    │ 静止検出
    ▼
[ターゲットボックス内をクロップ]
    │
    ▼
[Canvas → Base64 変換]
    │
    ▼
[POST /api/analyze へ送信]
    │
    ▼
[レスポンス解析・結果描画]
    │
    ▼
[ループ継続]
```

### 6.3 セキュリティ設計

| 対策 | 実装方法 |
|------|---------|
| XSS防止 | `textContent` / `createTextNode` を使用（`innerHTML` 禁止） |
| CSP準拠 | HTML `onclick` 属性禁止 → `addEventListener` で登録 |
| API使用量管理 | `localStorage` で日次API呼び出し数を追跡 |

### 6.4 イベントハンドラ

すべてのイベントハンドラは `init()` 関数内で `addEventListener` を用いて登録される（CSP `script-src 'self'` に準拠するため、HTML属性でのインラインハンドラは使用しない）。

---

## 7. static/style.css — スタイル設計

### 7.1 デザインシステム

| 項目 | 値 |
|------|-----|
| テーマ | Glassmorphism風ダークテーマ |
| フォント | Noto Sans JP（Google Fonts） |
| デザイントークン管理 | CSS変数（`:root` で定義） |
| 表示制御 | `.hidden` ユーティリティクラス |

---

## 8. templates/index.html — テンプレート設計

### 8.1 Jinja2テンプレート変数

| 変数名 | 型 | 用途 |
|--------|-----|------|
| `{{ csp_nonce }}` | `str` | CSPノンス値（`<style>` タグの `nonce` 属性に使用） |
| `{{ static_hash('script.js') }}` | `str` | 静的ファイルのハッシュ（キャッシュバスティング） |
| `{{ static_hash('style.css') }}` | `str` | 同上 |

---

## 9. リクエスト処理シーケンス（統合フロー）

### 9.1 正常系: テキスト抽出

```
ブラウザ                   app.py                   vision_api.py           Google Cloud
  │                         │                         │                       │
  │  POST /api/analyze      │                         │                       │
  │  {image, mode:"text"}   │                         │                       │
  │────────────────────────>│                         │                       │
  │                         │                         │                       │
  │                   [set_request_context]            │                       │
  │                   [_validate_analyze_request]      │                       │
  │                   [try_consume_request]            │                       │
  │                         │                         │                       │
  │                         │  detect_content()       │                       │
  │                         │────────────────────────>│                       │
  │                         │                         │                       │
  │                         │                   [preprocess_image]            │
  │                         │                   [コントラスト・シャープネス強調]│
  │                         │                         │                       │
  │                         │                         │  POST /v1/images:annotate
  │                         │                         │  x-goog-api-key ヘッダー
  │                         │                         │──────────────────────>│
  │                         │                         │                       │
  │                         │                         │  200 OK               │
  │                         │                         │  {responses: [...]}   │
  │                         │                         │<──────────────────────│
  │                         │                         │                       │
  │                         │                   [_parse_text_response]        │
  │                         │  {ok, data, image_size} │                       │
  │                         │<────────────────────────│                       │
  │                         │                         │                       │
  │                   [add_security_headers]           │                       │
  │  200 {ok:true, data:[...], image_size:[w,h]}      │                       │
  │<────────────────────────│                         │                       │
```

### 9.2 異常系: レート制限

```
ブラウザ                   app.py                rate_limiter.py
  │                         │                         │
  │  POST /api/analyze      │                         │
  │────────────────────────>│                         │
  │                         │  try_consume_request()  │
  │                         │────────────────────────>│
  │                         │                         │
  │                         │  (True, "上限到達", None)│
  │                         │<────────────────────────│
  │                         │                         │
  │  429 {ok:false,         │                         │
  │   error_code:"RATE_LIMITED"} │                    │
  │<────────────────────────│                         │
```

### 9.3 異常系: API失敗時の予約取り消し

```
ブラウザ                   app.py                rate_limiter.py    vision_api.py
  │                         │                         │                 │
  │  POST /api/analyze      │                         │                 │
  │────────────────────────>│                         │                 │
  │                         │  try_consume_request()  │                 │
  │                         │────────────────────────>│                 │
  │                         │  (False, "", req_id)    │                 │
  │                         │<────────────────────────│                 │
  │                         │                         │                 │
  │                         │  detect_content()       │                 │
  │                         │────────────────────────────────────────>│
  │                         │  {ok:false, error_code:"TIMEOUT"}       │
  │                         │<────────────────────────────────────────│
  │                         │                         │                 │
  │                         │  release_request(ip, req_id)             │
  │                         │────────────────────────>│                 │
  │                         │  [予約取り消し完了]       │                 │
  │                         │<────────────────────────│                 │
  │                         │                         │                 │
  │  502 {ok:false,         │                         │                 │
  │   error_code:"TIMEOUT"} │                         │                 │
  │<────────────────────────│                         │                 │
```

---

## 10. エラーコード一覧

| エラーコード | 発生箇所 | HTTPステータス | 説明 |
|-------------|---------|---------------|------|
| `INVALID_FORMAT` | app.py | 400 | JSON形式不正 |
| `MISSING_IMAGE` | app.py | 400 | 画像データ未指定 |
| `INVALID_MODE` | app.py | 400 | 不正なモード値 |
| `INVALID_BASE64` | app.py | 400 | Base64デコード失敗 |
| `IMAGE_TOO_LARGE` | app.py | 400 | 画像サイズ超過（5MB） |
| `INVALID_IMAGE_FORMAT` | app.py | 400 | JPEG/PNG以外の画像 |
| `RATE_LIMITED` | app.py | 429 | レート制限到達 |
| `VALIDATION_ERROR` | app.py | 400 | Vision APIモジュールでのバリデーションエラー |
| `SERVER_ERROR` | app.py | 500 | 予期しない内部エラー |
| `API_{status}` | vision_api.py | 502 | Vision API HTTPエラー |
| `VISION_{code}` | vision_api.py | 502 | Vision API内部エラー（200レスポンス内） |
| `TIMEOUT` | vision_api.py | 502 | APIタイムアウト（15秒） |
| `CONNECTION_ERROR` | vision_api.py | 502 | API接続失敗 |
| `REQUEST_ERROR` | vision_api.py | 502 | その他の通信エラー |

---

## 11. セキュリティ設計まとめ

### 11.1 多層防御の構成

| レイヤー | 対策 | 実装箇所 |
|---------|------|---------|
| 入力検証 | JSON形式チェック、Base64検証、マジックバイト検証、サイズ制限 | `app.py` |
| 認証 | 管理API: ADMIN_SECRET ヘッダー認証 | `app.py` |
| 流量制御 | IP単位の分間/日次レート制限（Redis原子操作） | `rate_limiter.py` |
| 通信セキュリティ | APIキーをヘッダー送信、SSL検証、リトライ制御 | `vision_api.py` |
| レスポンスセキュリティ | CSP（nonce化）、X-Frame-Options、X-Content-Type-Options | `app.py` |
| フロントエンド | textContent使用（innerHTML禁止）、addEventListener（onclick禁止） | `script.js` |
| リソース保護 | 画像ピクセル数上限（画像展開爆弾対策） | `vision_api.py` |

### 11.2 プロキシURL機密保護

プロキシURLに含まれる認証情報（ユーザー名/パスワード）は `_mask_proxy_url()` でマスクされ、ログ出力やAPIレスポンスに平文で露出しない。

```
入力: http://user:password@proxy.example.com:8080
出力: http://***:***@proxy.example.com:8080
```
