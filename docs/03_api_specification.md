# API仕様書

Vision AI Scanner が公開するすべてのHTTPエンドポイントの仕様です。

---

## 目次

1. [共通仕様](#共通仕様)
2. [GET / — メインページ](#get--メインページ)
3. [POST /api/analyze — 画像解析](#post-apianalyze--画像解析)
4. [GET /api/config/limits — レート制限設定取得](#get-apiconfiglimits--レート制限設定取得)
5. [GET /api/config/proxy — プロキシ設定取得](#get-apiconfigproxy--プロキシ設定取得)
6. [POST /api/config/proxy — プロキシ設定変更](#post-apiconfigproxy--プロキシ設定変更)
7. [GET /healthz — Livenessチェック](#get-healthz--livenessチェック)
8. [GET /readyz — Readinessチェック](#get-readyz--readinessチェック)
9. [エラーコード一覧](#エラーコード一覧)

---

## 共通仕様

### ベースURL

```
http://localhost:5000
```

### 共通レスポンスヘッダー

すべてのレスポンスに以下のセキュリティヘッダーが付与されます。

| ヘッダー | 値 |
|---------|-----|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Content-Security-Policy` | 後述（CSP設定参照） |
| `Permissions-Policy` | `camera=(self), microphone=(self)` |
| `Cache-Control` | `no-store, no-cache, must-revalidate, max-age=0` |
| `X-Request-Id` | リクエストごとの一意な相関ID（16桁16進数） |

### CORS

`ALLOWED_ORIGINS` 環境変数に設定されたOriginからのリクエストのみ、以下のCORSヘッダーが付与されます。

| ヘッダー | 値 |
|---------|-----|
| `Access-Control-Allow-Origin` | リクエストのOrigin（許可リストに含まれる場合のみ） |
| `Access-Control-Allow-Headers` | `Content-Type` |
| `Access-Control-Allow-Methods` | `GET, POST, OPTIONS` |

未設定時は同一オリジンのみ（CORSヘッダーなし）です。

### 共通エラーレスポンス形式

すべてのAPIエンドポイントは、エラー時に以下の統一JSON形式を返します。

```json
{
  "ok": false,
  "data": [],
  "error_code": "エラーコード文字列",
  "message": "人間が読めるエラーメッセージ"
}
```

### リクエストボディ上限

リクエストボディの最大サイズは **10MB** です。超過時はHTTP 413が返ります。

---

## GET / — メインページ

アプリケーションのメインページ（HTMLテンプレート）を返します。

### リクエスト

```
GET / HTTP/1.1
Host: localhost:5000
```

パラメータなし。

### レスポンス

| ステータスコード | Content-Type | 説明 |
|----------------|-------------|------|
| 200 | `text/html` | メインページHTML（Jinja2テンプレートで描画） |

HTMLテンプレートにはCSPノンス（`csp_nonce`）が埋め込まれます。

### リクエスト例

```bash
curl http://localhost:5000/
```

### レスポンス例

```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <!-- CSPノンスが埋め込まれたstyleタグ等 -->
  ...
</head>
<body>
  ...
</body>
</html>
```

---

## POST /api/analyze — 画像解析

Base64エンコードされた画像をGoogle Cloud Vision APIで解析し、テキスト抽出（OCR）または物体検出の結果を返します。

### リクエスト

| 項目 | 値 |
|------|-----|
| メソッド | `POST` |
| Content-Type | `application/json` |
| 認証 | 不要（レート制限あり） |

### リクエストボディ

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `image` | `string` | はい | Base64エンコードされた画像データ。`data:image/jpeg;base64,...` 形式のプレフィックス付きも受け付けます |
| `mode` | `string` | いいえ | 解析モード。`"text"`（OCR、デフォルト）または `"object"`（物体検出） |

### 入力検証

リクエストは以下の順で検証されます。

1. **JSON形式チェック**: Content-Typeが`application/json`であること
2. **JSONパース**: 正常にパースできること
3. **オブジェクト型チェック**: ボディがJSONオブジェクトであること
4. **画像データ存在チェック**: `image` フィールドが空でない文字列であること
5. **モード検証**: `mode` が `"text"` または `"object"` であること
6. **Base64デコード検証**: 正しいBase64文字列であること
7. **画像サイズ検証**: デコード後のサイズが **5MB以下** であること
8. **MIME magic byte検証**: 先頭バイトがJPEG（`FF D8 FF`）またはPNG（`89 50 4E 47`）であること
9. **レート制限チェック**: 分間・日次の制限を超えていないこと

### レスポンス（成功時）

| ステータスコード | 説明 |
|----------------|------|
| 200 | 解析成功 |

```json
{
  "ok": true,
  "data": [
    {
      "label": "検出されたテキストまたは物体名",
      "bounds": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
    }
  ],
  "image_size": [width, height],
  "error_code": null,
  "message": null
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `ok` | `boolean` | 成功時は`true` |
| `data` | `array` | 検出結果のリスト |
| `data[].label` | `string` | テキストモード: 検出文字列。物体モード: `"Cat（猫）- 95%"` 形式 |
| `data[].bounds` | `array` | バウンディングボックスの4頂点座標。テキストモード: ピクセル座標。物体モード: 正規化座標（0〜1） |
| `image_size` | `array\|null` | テキストモードのみ: `[width, height]`（ピクセル座標の基準サイズ）。物体モードでは`null` |
| `error_code` | `null` | 成功時は`null` |
| `message` | `null` | 成功時は`null` |

### レスポンス（エラー時）

| ステータスコード | error_code | 説明 |
|----------------|-----------|------|
| 400 | `INVALID_FORMAT` | JSON形式でない、またはパース失敗 |
| 400 | `MISSING_IMAGE` | `image` フィールドが空または未指定 |
| 400 | `INVALID_MODE` | 不正な `mode` 値 |
| 400 | `INVALID_BASE64` | Base64デコード失敗 |
| 400 | `IMAGE_TOO_LARGE` | 画像サイズが5MBを超過 |
| 400 | `INVALID_IMAGE_FORMAT` | JPEG/PNG以外の画像形式 |
| 400 | `VALIDATION_ERROR` | その他のバリデーションエラー（APIキー未設定等） |
| 413 | `REQUEST_TOO_LARGE` | リクエストボディが10MBを超過 |
| 429 | `RATE_LIMITED` | レート制限超過 |
| 500 | `SERVER_ERROR` | 内部サーバーエラー |
| 502 | `API_{ステータスコード}` | Vision APIからのHTTPエラー（例: `API_403`） |
| 502 | `VISION_{エラーコード}` | Vision APIのレスポンス内部エラー |
| 502 | `TIMEOUT` | Vision APIへのリクエストがタイムアウト（15秒） |
| 502 | `CONNECTION_ERROR` | Vision APIへの接続失敗 |
| 502 | `REQUEST_ERROR` | Vision APIとの通信中のその他エラー |

### リクエスト例（テキストモード）

```bash
curl -X POST http://localhost:5000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...",
    "mode": "text"
  }'
```

### レスポンス例（テキストモード — 成功）

```json
{
  "ok": true,
  "data": [
    {
      "label": "Hello",
      "bounds": [[10, 20], [100, 20], [100, 60], [10, 60]]
    },
    {
      "label": "World",
      "bounds": [[10, 70], [110, 70], [110, 110], [10, 110]]
    }
  ],
  "image_size": [640, 480],
  "error_code": null,
  "message": null
}
```

### リクエスト例（物体検出モード）

```bash
curl -X POST http://localhost:5000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "image": "/9j/4AAQSkZJRgABAQ...",
    "mode": "object"
  }'
```

### レスポンス例（物体検出モード — 成功）

```json
{
  "ok": true,
  "data": [
    {
      "label": "Cat（猫）- 95%",
      "bounds": [[0.1, 0.2], [0.8, 0.2], [0.8, 0.9], [0.1, 0.9]]
    },
    {
      "label": "Chair - 72%",
      "bounds": [[0.5, 0.3], [0.95, 0.3], [0.95, 0.98], [0.5, 0.98]]
    }
  ],
  "image_size": null,
  "error_code": null,
  "message": null
}
```

### レスポンス例（レート制限超過）

```json
{
  "ok": false,
  "data": [],
  "error_code": "RATE_LIMITED",
  "message": "リクエスト頻度が高すぎます（上限: 20回/分）"
}
```

### レスポンス例（日次制限超過）

```json
{
  "ok": false,
  "data": [],
  "error_code": "RATE_LIMITED",
  "message": "1日あたりのAPI上限(1000回)に達しました"
}
```

### レスポンス例（不正な画像形式）

```json
{
  "ok": false,
  "data": [],
  "error_code": "INVALID_IMAGE_FORMAT",
  "message": "許可されていない画像形式です（JPEG/PNGのみ対応）"
}
```

### レスポンス例（Vision APIエラー）

```json
{
  "ok": false,
  "data": [],
  "image_size": null,
  "error_code": "API_403",
  "message": "Vision APIエラー (ステータス 403)"
}
```

---

## GET /api/config/limits — レート制限設定取得

現在のレート制限設定値（日次上限）をフロントエンドに返します。

### リクエスト

| 項目 | 値 |
|------|-----|
| メソッド | `GET` |
| 認証 | 不要 |

### レスポンス

| ステータスコード | 説明 |
|----------------|------|
| 200 | 設定値返却 |

```json
{
  "daily_limit": 1000
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `daily_limit` | `integer` | 1日あたりのAPI呼び出し上限回数（環境変数 `RATE_LIMIT_DAILY` で設定） |

### リクエスト例

```bash
curl http://localhost:5000/api/config/limits
```

### レスポンス例

```json
{
  "daily_limit": 1000
}
```

---

## GET /api/config/proxy — プロキシ設定取得

現在のプロキシ設定状態を返します。認証の有無によって返却される情報の詳細度が変わります。

### リクエスト

| 項目 | 値 |
|------|-----|
| メソッド | `GET` |
| 認証 | 任意（認証ありで詳細情報を返却） |

### リクエストヘッダー（任意）

| ヘッダー | 説明 |
|---------|------|
| `X-Admin-Secret` | `ADMIN_SECRET` 環境変数と一致する値 |

### レスポンス（認証なし）

| ステータスコード | 説明 |
|----------------|------|
| 200 | ON/OFF情報のみ返却 |

```json
{
  "enabled": true
}
```

### レスポンス（認証あり）

| ステータスコード | 説明 |
|----------------|------|
| 200 | プロキシURLを含む詳細情報を返却 |

```json
{
  "enabled": true,
  "url": "http://***:***@proxy.example.com:8080"
}
```

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `enabled` | `boolean` | プロキシが有効かどうか |
| `url` | `string` | プロキシURL（認証情報はマスク済み）。無効時は空文字列 |

### リクエスト例（認証なし）

```bash
curl http://localhost:5000/api/config/proxy
```

### レスポンス例（認証なし）

```json
{
  "enabled": false
}
```

### リクエスト例（認証あり）

```bash
curl http://localhost:5000/api/config/proxy \
  -H "X-Admin-Secret: your-admin-secret-here"
```

### レスポンス例（認証あり）

```json
{
  "enabled": true,
  "url": "http://***:***@proxy.corp.example.com:3128"
}
```

---

## POST /api/config/proxy — プロキシ設定変更

プロキシの有効/無効を切り替えます。**管理者認証が必須**です。

### リクエスト

| 項目 | 値 |
|------|-----|
| メソッド | `POST` |
| Content-Type | `application/json` |
| 認証 | **必須**（`X-Admin-Secret` ヘッダー） |

### リクエストヘッダー

| ヘッダー | 必須 | 説明 |
|---------|------|------|
| `X-Admin-Secret` | はい | `ADMIN_SECRET` 環境変数と一致する値 |

### リクエストボディ

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `enabled` | `boolean` | はい | `true` でプロキシ有効、`false` で無効 |

### レスポンス（成功時）

| ステータスコード | 説明 |
|----------------|------|
| 200 | 設定変更成功 |

```json
{
  "ok": true,
  "status": {
    "enabled": true,
    "url": "http://***:***@proxy.example.com:8080"
  }
}
```

### レスポンス（エラー時）

| ステータスコード | error_code | 説明 |
|----------------|-----------|------|
| 403 | `UNAUTHORIZED` | 認証失敗（`X-Admin-Secret` が不正、または`ADMIN_SECRET`が未設定） |
| 400 | `INVALID_FORMAT` | `enabled` フィールドを含むJSONオブジェクトでない |
| 400 | `INVALID_TYPE` | `enabled` フィールドが`boolean`型でない |

> **注意**: `ADMIN_SECRET` 環境変数が未設定の場合、このエンドポイントは常に403を返します（安全側のデフォルト動作）。

### リクエスト例

```bash
curl -X POST http://localhost:5000/api/config/proxy \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: your-admin-secret-here" \
  -d '{"enabled": false}'
```

### レスポンス例（成功）

```json
{
  "ok": true,
  "status": {
    "enabled": false,
    "url": ""
  }
}
```

### レスポンス例（認証失敗）

```json
{
  "ok": false,
  "data": [],
  "error_code": "UNAUTHORIZED",
  "message": "管理APIへのアクセス権がありません"
}
```

### レスポンス例（不正なリクエスト形式）

```json
{
  "ok": false,
  "data": [],
  "error_code": "INVALID_FORMAT",
  "message": "enabledフィールドを含むJSONオブジェクトが必要です"
}
```

---

## GET /healthz — Livenessチェック

アプリケーションプロセスが起動しているかを確認します。外部依存のチェックは行いません。
Kubernetes等のオーケストレーターのLivenessプローブとして使用できます。

### リクエスト

| 項目 | 値 |
|------|-----|
| メソッド | `GET` |
| 認証 | 不要 |

### レスポンス

| ステータスコード | 説明 |
|----------------|------|
| 200 | プロセス正常稼働 |

```json
{
  "status": "ok"
}
```

応答がない場合はプロセスが停止していると判断します。

### リクエスト例

```bash
curl http://localhost:5000/healthz
```

### レスポンス例

```json
{
  "status": "ok"
}
```

---

## GET /readyz — Readinessチェック

アプリケーションがリクエストを処理可能な状態かどうかを確認します。APIキーの設定状態やレート制限バックエンドの正常性をチェックします。
Kubernetes等のReadinessプローブとして使用できます。

### リクエスト

| 項目 | 値 |
|------|-----|
| メソッド | `GET` |
| 認証 | 不要 |

### レスポンス（正常時）

| ステータスコード | 説明 |
|----------------|------|
| 200 | 全チェック通過 |

```json
{
  "status": "ok",
  "checks": {
    "api_key_configured": true,
    "rate_limiter_backend": "redis",
    "rate_limiter_ok": true
  }
}
```

### レスポンス（異常時）

| ステータスコード | 説明 |
|----------------|------|
| 503 | いずれかのチェックが失敗 |

```json
{
  "status": "not_ready",
  "checks": {
    "api_key_configured": true,
    "rate_limiter_backend": "in_memory",
    "rate_limiter_ok": false
  },
  "warnings": [
    "REDIS_URL が設定されていますが、Redis接続に失敗しインメモリにフォールバックしています"
  ]
}
```

### checksフィールド詳細

| チェック項目 | 型 | 説明 |
|------------|-----|------|
| `api_key_configured` | `boolean` | `VISION_API_KEY` 環境変数が設定されているか |
| `rate_limiter_backend` | `string` | 現在のレート制限バックエンド（`"redis"` または `"in_memory"`） |
| `rate_limiter_ok` | `boolean` | レート制限バックエンドが期待通りに動作しているか |

### 503を返す条件

以下のいずれかに該当する場合に `503 Service Unavailable` を返します。

1. **`VISION_API_KEY` が未設定**: `api_key_configured` が `false`
2. **Redisフォールバック**: `REDIS_URL` が設定されているにもかかわらず、Redis接続に失敗してインメモリバックエンドにフォールバックしている場合（`rate_limiter_ok` が `false`）

### warningsフィールド

503レスポンスにのみ含まれるオプションフィールドです。Redisフォールバック時に具体的な警告メッセージが配列で返されます。

### リクエスト例

```bash
curl http://localhost:5000/readyz
```

### レスポンス例（全チェック通過）

```json
{
  "status": "ok",
  "checks": {
    "api_key_configured": true,
    "rate_limiter_backend": "redis",
    "rate_limiter_ok": true
  }
}
```

### レスポンス例（APIキー未設定）

```json
{
  "status": "not_ready",
  "checks": {
    "api_key_configured": false,
    "rate_limiter_backend": "in_memory",
    "rate_limiter_ok": true
  }
}
```

---

## エラーコード一覧

アプリケーションが返す全エラーコードの一覧です。

### 入力検証エラー（400）

| error_code | 発生条件 | メッセージ例 |
|-----------|---------|------------|
| `INVALID_FORMAT` | JSON形式でない、パース失敗、オブジェクト型でない | `リクエストはJSON形式である必要があります` |
| `MISSING_IMAGE` | `image` フィールドが空または未指定 | `画像データがありません` |
| `INVALID_MODE` | `mode` が `text`/`object` 以外 | `不正なモード: 'xyz'。許可値: ['text', 'object']` |
| `INVALID_BASE64` | Base64デコード失敗 | `画像データのBase64デコードに失敗しました` |
| `IMAGE_TOO_LARGE` | 画像サイズが5MB超過 | `画像サイズが上限(5MB)を超えています` |
| `INVALID_IMAGE_FORMAT` | JPEG/PNG以外の画像 | `許可されていない画像形式です（JPEG/PNGのみ対応）` |
| `VALIDATION_ERROR` | その他のバリデーションエラー | （エラー内容に応じた動的メッセージ） |
| `BAD_REQUEST` | Flaskが検出した不正リクエスト | `不正なリクエストです` |
| `INVALID_TYPE` | `enabled`フィールドの型不正（proxy設定） | `enabledフィールドはboolean型(true/false)である必要があります` |

### 認証・認可エラー（403）

| error_code | 発生条件 | メッセージ例 |
|-----------|---------|------------|
| `UNAUTHORIZED` | `X-Admin-Secret` 不一致または `ADMIN_SECRET` 未設定 | `管理APIへのアクセス権がありません` |

### レート制限エラー（413, 429）

| error_code | 発生条件 | メッセージ例 |
|-----------|---------|------------|
| `REQUEST_TOO_LARGE` | リクエストボディが10MB超過 | `リクエストサイズが上限(10MB)を超えています` |
| `RATE_LIMITED` | 分間または日次のレート制限超過 | `リクエスト頻度が高すぎます（上限: 20回/分）` |

### サーバーエラー（500, 502）

| error_code | 発生条件 | メッセージ例 |
|-----------|---------|------------|
| `SERVER_ERROR` | 予期しない内部エラー | `内部サーバーエラーが発生しました` |
| `API_{ステータスコード}` | Vision APIのHTTPエラー | `Vision APIエラー (ステータス 403)` |
| `VISION_{エラーコード}` | Vision APIレスポンス内部のエラー | （Vision APIが返すメッセージ） |
| `TIMEOUT` | Vision APIタイムアウト（15秒） | `APIリクエストがタイムアウトしました` |
| `CONNECTION_ERROR` | Vision APIへの接続失敗 | `API接続に失敗しました` |
| `REQUEST_ERROR` | Vision APIとの通信中のその他エラー | （エラー内容に応じた動的メッセージ） |

---

## レート制限の動作仕様

### 制限値

| 種別 | デフォルト値 | 環境変数 |
|------|------------|---------|
| 分間上限 | 20回/分 | `RATE_LIMIT_PER_MINUTE` |
| 日次上限 | 1000回/日 | `RATE_LIMIT_DAILY` |

### 予約・解放メカニズム

1. `/api/analyze` へのリクエスト受信時に**レート枠を予約**（`try_consume_request`）
2. Vision APIの呼び出しが**失敗**した場合、予約した枠を**解放**（`release_request`）
3. 成功した場合は予約枠を消費済みとして保持

このメカニズムにより、API側のエラーでユーザーのレート枠が不必要に消費されることを防ぎます。

### リセットタイミング

| 種別 | リセットタイミング |
|------|------------------|
| 分間カウンタ | 各リクエストから60秒経過で自動期限切れ（スライディングウィンドウ） |
| 日次カウンタ | 毎日0:00（ローカルタイム）にリセット |

---

## 補足: Vision APIモード別の動作

### テキストモード（`mode: "text"`）

- Vision API機能: `DOCUMENT_TEXT_DETECTION`（高精度OCR）
- 画像前処理: コントラスト強調（1.5倍）+ シャープネス強調（1.5倍）
- 言語ヒント: `["en", "ja"]`
- 座標系: ピクセル座標（`image_size` で基準サイズを返却）
- 最大結果数: 10件

### 物体検出モード（`mode: "object"`）

- Vision API機能: `OBJECT_LOCALIZATION`
- 画像前処理: なし
- 座標系: 正規化座標（0〜1、`image_size` は`null`）
- ラベル形式: `"英語名（日本語名）- 信頼度%"`（翻訳辞書に該当がある場合）
- 最大結果数: 10件
