# アーキテクチャ設計書 - Vision AI Scanner

| 項目 | 内容 |
|------|------|
| ドキュメント名 | アーキテクチャ設計書 |
| プロジェクト名 | Vision AI Scanner |
| バージョン | 1.0 |
| 最終更新日 | 2026-02-20 |

---

## 1. システム構成図

```
┌──────────────────────────────────────────────────────────────────────┐
│                         ブラウザ（クライアント）                        │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐    │
│  │  index.html  │  │  script.js   │  │       style.css         │    │
│  │  (Jinja2     │  │  (カメラ制御  │  │  (MD3ダークテーマ       │    │
│  │   テンプレート)│  │   静止検知    │  │   Glassmorphism)       │    │
│  │              │  │   API通信)    │  │                         │    │
│  └──────────────┘  └──────┬───────┘  └─────────────────────────┘    │
│                           │                                          │
│                   POST /api/analyze                                  │
│                   GET  /api/config/limits                            │
│                   GET  /api/config/proxy                             │
└───────────────────────────┼──────────────────────────────────────────┘
                            │ HTTP (JSON)
                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Flask サーバー (app.py)                         │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ミドルウェア層                                                 │  │
│  │  ・before_request: 相関ID生成、CSPノンス生成                    │  │
│  │  ・after_request:  セキュリティヘッダー付与、CORS制御            │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐   │
│  │   /api/analyze    │  │ rate_limiter.py  │  │ vision_api.py   │   │
│  │  (バリデーション   │──│ (レート制限       │──│ (前処理+API     │   │
│  │   エントリーポイント)│  │  チェック＆予約)  │  │  呼び出し)      │   │
│  └──────────────────┘  └────────┬─────────┘  └────────┬────────┘   │
│                                 │                      │             │
│  ┌──────────────────┐           │            ┌────────┴────────┐   │
│  │ translations.py  │           │            │ Pillow          │   │
│  │ (英日翻訳辞書)    │           │            │ (画像前処理)     │   │
│  └──────────────────┘           │            └─────────────────┘   │
└─────────────────────────────────┼──────────────────┼────────────────┘
                                  │                  │
                          ┌───────┴───────┐          │ HTTPS
                          │               │          │
                    ┌─────┴─────┐  ┌──────┴────┐     ▼
                    │   Redis   │  │ インメモリ  │  ┌──────────────────┐
                    │ (本番推奨) │  │ (フォール   │  │ Google Cloud     │
                    │           │  │  バック)    │  │ Vision API       │
                    └───────────┘  └───────────┘  └──────────────────┘
```

---

## 2. リクエストフロー

### 2.1 画像解析リクエスト（メインフロー）

```
ブラウザ                    Flask (app.py)           rate_limiter.py        vision_api.py          Google Cloud Vision API
  │                            │                         │                      │                         │
  │  POST /api/analyze         │                         │                      │                         │
  │  {image, mode}             │                         │                      │                         │
  │───────────────────────────>│                         │                      │                         │
  │                            │                         │                      │                         │
  │                            │ ① リクエスト検証         │                      │                         │
  │                            │  ・JSON形式チェック      │                      │                         │
  │                            │  ・image存在チェック     │                      │                         │
  │                            │  ・mode列挙チェック      │                      │                         │
  │                            │  ・Base64デコード検証    │                      │                         │
  │                            │  ・サイズ上限チェック     │                      │                         │
  │                            │  ・MIMEマジックバイト検証 │                      │                         │
  │                            │                         │                      │                         │
  │                            │ ② レート制限チェック     │                      │                         │
  │                            │────────────────────────>│                      │                         │
  │                            │                         │ try_consume_request() │                         │
  │                            │                         │  ・分間カウント確認    │                         │
  │                            │                         │  ・日次カウント確認    │                         │
  │                            │                         │  ・予約(原子的)       │                         │
  │                            │<────────────────────────│                      │                         │
  │                            │                         │                      │                         │
  │                            │ ③ Vision API呼び出し    │                      │                         │
  │                            │─────────────────────────────────────────────>│                         │
  │                            │                         │                      │ detect_content()        │
  │                            │                         │                      │  ・テキストモード:       │
  │                            │                         │                      │    画像前処理実行        │
  │                            │                         │                      │                         │
  │                            │                         │                      │  POST images:annotate   │
  │                            │                         │                      │────────────────────────>│
  │                            │                         │                      │                         │
  │                            │                         │                      │<────────────────────────│
  │                            │                         │                      │  レスポンス解析          │
  │                            │<─────────────────────────────────────────────│                         │
  │                            │                         │                      │                         │
  │  200 {ok, data, image_size}│                         │                      │                         │
  │<───────────────────────────│                         │                      │                         │
  │                            │                         │                      │                         │
  │  バウンディングボックス描画  │                         │                      │                         │
  │  結果パネルに追加           │                         │                      │                         │
```

### 2.2 エラー時のフロー

```
[API呼び出し失敗時]
  app.py ──→ release_request(client_ip, request_id)  ※予約済みカウントを取り消し
         ──→ エラーレスポンス返却（502 / 500）

[レート制限到達時]
  app.py ──→ エラーレスポンス返却（429）
  script.js ──→ scheduleRetry() ──→ 5秒後に自動再試行

[フロントエンド通信エラー時]
  script.js ──→ scheduleRetry() ──→ 5秒後に自動再試行
```

---

## 3. バックエンド構成

### 3.1 app.py - Flask エントリーポイント

| 責務 | 詳細 |
|------|------|
| **ルーティング** | `GET /`、`POST /api/analyze`、`GET /api/config/limits`、`GET/POST /api/config/proxy`、`GET /healthz`、`GET /readyz` |
| **リクエストバリデーション** | JSON形式チェック、image/mode検証、Base64デコード、サイズ上限、MIMEマジックバイト検証 |
| **レート制限呼び出し** | `try_consume_request()` でチェック＆予約、失敗時 `release_request()` で取り消し |
| **セキュリティヘッダー** | `after_request` で全レスポンスにCSP、X-Frame-Options等を付与 |
| **相関ID / CSPノンス** | `before_request` でリクエストごとに生成 |
| **エラーハンドリング** | 400/413のカスタムハンドラー、統一JSON形式レスポンス |
| **構造化ログ** | `_log()` ヘルパーで `event=xxx request_id=xxx` 形式のログ出力 |
| **静的ファイルハッシュ** | `_static_file_hash()` によるキャッシュバスティング（MD5先頭8文字） |
| **管理API** | `ADMIN_SECRET` による認証付きプロキシ設定変更 |

**主要定数:**

```python
MAX_IMAGE_SIZE = 5 * 1024 * 1024          # 5MB（Base64デコード後）
MAX_REQUEST_BODY = 10 * 1024 * 1024       # 10MB（Base64 + JSONオーバーヘッド）
```

**APIレスポンス形式（統一）:**

```json
{
  "ok": true,
  "data": [{"label": "検出テキスト", "bounds": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]}],
  "image_size": [width, height],
  "error_code": null,
  "message": null
}
```

### 3.2 vision_api.py - Vision API クライアント

| 責務 | 詳細 |
|------|------|
| **API呼び出し** | `detect_content()` が単一エントリーポイント。テキストモード / 物体検出モードを切り替え |
| **画像前処理** | `preprocess_image()` でコントラスト1.5倍 + シャープネス1.5倍（テキストモードのみ） |
| **HTTPセッション管理** | `requests.Session` をモジュールレベルで共有（接続プール再利用） |
| **リトライ戦略** | 3回リトライ、指数バックオフ（0.5秒基準）、429/500/502/503で再試行 |
| **レスポンス解析** | `_parse_text_response()` と `_parse_object_response()` で結果を統一形式に変換 |
| **プロキシ管理** | `get_proxy_status()` / `set_proxy_enabled()` によるスレッド安全な動的切替 |
| **安全対策** | 画像展開爆弾対策（2000万ピクセル上限）、APIキーヘッダー送信 |

**主要定数:**

```python
FEATURE_TYPES = {
    "text": "DOCUMENT_TEXT_DETECTION",    # 高精度テキスト検出
    "object": "OBJECT_LOCALIZATION",      # 座標付き物体検出
}
MAX_RESULTS = 10                          # API最大結果数
LANGUAGE_HINTS = ["en", "ja"]             # OCR言語ヒント
API_TIMEOUT_SECONDS = 15                  # タイムアウト
CONTRAST_FACTOR = 1.5                     # コントラスト強調係数
SHARPNESS_FACTOR = 1.5                    # シャープネス強調係数
JPEG_QUALITY = 95                         # JPEG保存品質
MAX_IMAGE_PIXELS = 20_000_000             # 画像展開爆弾対策
```

**テキスト検出レスポンス解析の流れ:**

```
Vision API レスポンス
  └─ responses[0]
       ├─ error → 部分エラー処理
       ├─ textAnnotations[0] → 全文テキスト（ログ出力用）
       ├─ textAnnotations[1:] → 個別単語/ブロック（座標付き）
       └─ fullTextAnnotation.pages[0] → 画像サイズ（width, height）
                                          └─ フォールバック: textAnnotations[0].boundingPoly から推定
```

**物体検出レスポンス解析の流れ:**

```
Vision API レスポンス
  └─ responses[0]
       └─ localizedObjectAnnotations[] → 各物体
            ├─ name → OBJECT_TRANSLATIONS で日本語翻訳
            ├─ score → 信頼度スコア（%表示）
            └─ boundingPoly.normalizedVertices → 正規化座標（0〜1）
```

### 3.3 rate_limiter.py - レート制限モジュール

| 責務 | 詳細 |
|------|------|
| **バックエンド自動選択** | `REDIS_URL` 設定時はRedis、未設定または接続失敗時はインメモリ |
| **原子的操作** | Redis: Luaスクリプトによるチェック＆予約の原子的実行 |
| **スレッド安全** | インメモリ: `threading.Lock` による排他制御 |
| **予約取り消し** | `release_request()` でAPI呼び出し失敗時にカウントを回収 |
| **遅延初期化** | `_get_backend()` で初回アクセス時にバックエンドを初期化 |

**二重制限構造:**

```
リクエスト受信
  │
  ├─ 分間制限チェック（Sorted Set / リスト、60秒TTL）
  │   └─ 超過 → "リクエスト頻度が高すぎます（上限: 20回/分）"
  │
  └─ 日次制限チェック（カウンター、日付境界TTL）
      └─ 超過 → "1日あたりのAPI上限(1000回)に達しました"
```

**Redisキー設計:**

| キー | データ型 | TTL | 用途 |
|------|---------|-----|------|
| `rate:minute:{ip}` | Sorted Set（スコア=タイムスタンプ） | 90秒 | 分間リクエスト追跡 |
| `rate:daily:{ip}:{date}` | String（カウンター） | 翌日0時まで | 日次リクエストカウント |

**公開API:**

| 関数 | 説明 |
|------|------|
| `try_consume_request(client_ip)` | 制限チェック＆予約。戻り値: `(制限中か, メッセージ, request_id)` |
| `release_request(client_ip, request_id)` | 指定IDの予約を取り消し（API失敗時の回収） |
| `get_daily_count(client_ip)` | 日次カウント取得（監視・テスト用） |
| `get_backend_type()` | 現在のバックエンド種別（`"redis"` or `"in_memory"`） |
| `reset_for_testing()` | テスト用: インメモリにリセット |

### 3.4 translations.py - 英日翻訳辞書

| 責務 | 詳細 |
|------|------|
| **翻訳対象** | Google Cloud Vision API の物体検出ラベル（英語 → 日本語） |
| **登録語数** | 約120語 |
| **カテゴリ** | 人物・身体、衣類、家具・室内、電子機器、食べ物・飲み物、乗り物、動物、自然、道具・物品、産業・工場、複合語ラベル |
| **参照方法** | `OBJECT_TRANSLATIONS.get(en_name.lower(), "")` で小文字キーで検索 |
| **未登録ラベル** | 英語名がそのまま表示される |

---

## 4. フロントエンド構成

### 4.1 script.js - フロントエンドスクリプト

| 責務 | 詳細 |
|------|------|
| **カメラ制御** | `navigator.mediaDevices.getUserMedia` によるHD映像取得、デバイス切替、ストリーム管理 |
| **静止検知** | `requestAnimationFrame` ループでフレーム間差分を計算、安定フレーム数でトリガー |
| **画像キャプチャ** | ターゲットボックス内のみCanvasにクロップ → JPEG Base64化 |
| **API通信** | `fetch()` による `/api/analyze` へのPOST（タイムアウト15秒、AbortSignal使用） |
| **バウンディングボックス描画** | オーバーレイCanvas上にテキスト/物体の検出枠を描画 |
| **結果表示** | DOM API（`textContent`/`createTextNode`）による安全なテキスト挿入 |
| **API使用量管理** | `localStorage` で日次カウント管理、サーバーから上限値を動的取得 |
| **エラーリカバリ** | `scheduleRetry()` で5秒後に自動再試行、チャタリング防止（800msガード） |
| **初期化** | `DOMContentLoaded` で `init()` を実行、全イベントリスナーを登録 |

**主要定数:**

```javascript
API_DAILY_LIMIT = 1000           // サーバーから動的取得で上書き
TARGET_BOX_RATIO = 0.6           // ターゲットボックスの映像比率（60%）
STABILITY_THRESHOLD = 30         // 安定判定フレーム数（約1秒@30fps）
MOTION_THRESHOLD = 30            // フレーム間差分の閾値
MOTION_CANVAS_WIDTH = 64         // モーション検出用キャンバス幅
MOTION_CANVAS_HEIGHT = 48        // モーション検出用キャンバス高さ
CAMERA_WIDTH = 1280              // カメラ解像度（幅）
CAMERA_HEIGHT = 720              // カメラ解像度（高さ）
JPEG_QUALITY = 0.95              // キャプチャ画質
RETRY_DELAY_MS = 5000            // エラー後の再試行待機時間
FETCH_TIMEOUT_MS = 10000         // fetchタイムアウト
```

**状態管理（グローバル変数）:**

| 変数 | 型 | 説明 |
|------|----|------|
| `isScanning` | boolean | スキャン中フラグ |
| `currentSource` | string | 入力ソース（`'camera'` / `'file'`） |
| `currentMode` | string | 検出モード（`'text'` / `'object'`） |
| `isMirrored` | boolean | ミラー反転状態 |
| `isPausedByError` | boolean | エラーによる一時停止状態 |
| `isAnalyzing` | boolean | API呼び出し中フラグ（並行呼び出し防止） |
| `apiCallCount` | number | 本日のAPI呼び出し回数 |
| `stabilityCounter` | number | 連続安定フレーム数 |
| `lastFrameData` | Uint8ClampedArray | 前フレームのピクセルデータ |

### 4.2 index.html - HTMLテンプレート

| 責務 | 詳細 |
|------|------|
| **テンプレートエンジン** | Jinja2（Flask標準） |
| **CSPノンス** | `{{ csp_nonce }}` でサーバーから受け取り、style要素に適用 |
| **静的ファイルバージョン** | `{{ static_hash('style.css') }}` でMD5ハッシュによるキャッシュバスティング |
| **言語設定** | `<html lang="ja">` |
| **ビューポート** | `width=device-width, initial-scale=1.0`（レスポンシブ対応） |
| **フォント** | Google Fonts（Noto Sans JP + Inter） |

**レイアウト構造:**

```
body
  └─ .container
       ├─ header
       │    ├─ h1 "Vision AI Scanner"
       │    └─ .status-indicator
       │         ├─ #btn-proxy（プロキシ設定バッジ）
       │         ├─ #api-counter（API使用量カウンター）
       │         ├─ #status-dot（スキャン状態インジケーター）
       │         └─ #status-text（ステータステキスト）
       │
       └─ .main-grid
            ├─ .video-panel（左パネル: 映像ソース）
            │    ├─ .panel-header
            │    │    └─ .controls（カメラ / 切替 / ファイル ボタン）
            │    ├─ .video-container
            │    │    ├─ video#video-feed（映像表示）
            │    │    ├─ canvas#overlay-canvas（バウンディングボックス描画）
            │    │    ├─ .scan-overlay（スキャン中のオーバーレイ効果）
            │    │    ├─ .target-box（ターゲットボックス表示）
            │    │    ├─ #stability-bar-container（安定化プログレスバー）
            │    │    └─ .video-tools（反転ボタン + モード切替）
            │    ├─ .action-bar
            │    │    └─ #btn-scan（スタート/ストップボタン）
            │    └─ canvas#capture-canvas（キャプチャ用非表示キャンバス）
            │
            └─ .result-panel（右パネル: 検出結果）
                 ├─ .panel-header
                 │    ├─ h2 "検出結果"
                 │    └─ #btn-clear（クリアボタン）
                 └─ #result-list（結果一覧）
```

### 4.3 style.css - スタイルシート

| 責務 | 詳細 |
|------|------|
| **デザインシステム** | Material Design 3 ダークテーマ |
| **視覚効果** | Glassmorphism風の半透明パネル |
| **CSS変数** | デザイントークン管理（カラー、エレベーション、トランジション、角丸） |
| **フォント** | `Noto Sans JP`（日本語）+ `Inter`（英数字） |
| **ユーティリティ** | `.hidden` クラスで表示/非表示制御 |
| **レスポンシブ** | グリッドレイアウトによるPC/モバイル対応 |

---

## 5. データフロー

### 5.1 画像キャプチャから結果表示までの全体フロー

```
① カメラ映像取得
   navigator.mediaDevices.getUserMedia()
   → video要素にストリームを設定
   → HD解像度（1280x720）で映像取得

② フレーム間差分による静止検知
   requestAnimationFrame ループ
   → motionCanvas（64x48）にフレーム描画
   → 前フレームとのRGBピクセル差分を計算
   → 平均差分 < MOTION_THRESHOLD(30) なら安定カウント加算
   → 安定化プログレスバーを更新

③ 安定判定（30フレーム連続安定）
   stabilityCounter >= STABILITY_THRESHOLD
   → captureAndAnalyze() を呼び出し

④ ターゲットボックス内クロップ
   video映像の中央60%領域をCanvasに描画
   → canvas.toDataURL('image/jpeg', 0.95)
   → Base64文字列を生成

⑤ APIリクエスト送信
   fetch('/api/analyze', {
     method: 'POST',
     body: JSON.stringify({ image: base64Data, mode: 'text'|'object' })
   })

⑥ サーバー側バリデーション（app.py）
   JSON形式チェック → image存在チェック → mode列挙チェック
   → data:image/...;base64, プレフィックス除去
   → Base64デコード検証 → サイズ上限チェック（5MB）
   → MIMEマジックバイト検証（JPEG/PNGのみ）

⑦ レート制限チェック（rate_limiter.py）
   try_consume_request(client_ip)
   → 分間/日次カウントを原子的にチェック＆予約
   → 超過時: HTTP 429 を返却

⑧ 画像前処理（vision_api.py - テキストモードのみ）
   Base64デコード → Pillow で画像オープン
   → ピクセル数チェック（2000万ピクセル上限）
   → RGB変換 → コントラスト1.5倍 → シャープネス1.5倍
   → JPEG 95%品質で再エンコード → Base64化

⑨ Google Cloud Vision API 呼び出し
   POST https://vision.googleapis.com/v1/images:annotate
   ヘッダー: x-goog-api-key: {API_KEY}
   ペイロード: {
     requests: [{
       image: { content: base64 },
       features: [{ type: "DOCUMENT_TEXT_DETECTION"|"OBJECT_LOCALIZATION", maxResults: 10 }],
       imageContext: { languageHints: ["en", "ja"] }
     }]
   }

⑩ レスポンス解析
   テキストモード:
     textAnnotations[1:] → [{label, bounds(ピクセル座標)}]
     fullTextAnnotation.pages[0] → image_size [width, height]
   物体モード:
     localizedObjectAnnotations → [{label(英名+日本語名+スコア), bounds(正規化座標)}]

⑪ フロントエンド表示
   バウンディングボックス描画:
     座標変換（ピクセル/正規化 → Canvas座標）
     → ミラー反転考慮
     → overlayCanvas に矩形描画
   結果パネル更新:
     フィルター適用（最小文字数、URL除外）
     → DOM APIでタイムスタンプ付きテキスト挿入
   API使用量更新:
     apiCallCount++ → localStorage保存 → カウンター表示更新
```

### 5.2 座標変換の詳細

```
テキストモード（ピクセル座標）:
  Vision API 座標 (px) → 正規化 (0〜1) → Canvas座標
  [x, y] → [x/imageWidth, y/imageHeight] → [targetX + nx*targetW, targetY + ny*targetH]

物体モード（正規化座標）:
  Vision API 座標 (0〜1) → そのまま使用 → Canvas座標
  [nx, ny] → [targetX + nx*targetW, targetY + ny*targetH]

ミラー反転時:
  正規化X座標を反転: nx → 1 - nx
```

---

## 6. 技術スタック一覧

### 6.1 バックエンド

| カテゴリ | 技術 | バージョン/備考 |
|---------|------|----------------|
| 言語 | Python | 3.9以上 |
| Webフレームワーク | Flask | WSGI、テンプレートエンジン Jinja2 |
| 画像処理 | Pillow (PIL) | コントラスト・シャープネス強調 |
| HTTP クライアント | requests | 接続プール、リトライ戦略 |
| 環境変数管理 | python-dotenv | `.env` ファイル読み込み |
| キャッシュ | cachetools (TTLCache) | インメモリレート制限用 |
| データストア（任意） | Redis | レート制限のマルチプロセス対応 |
| プロキシ対応 | werkzeug ProxyFix | X-Forwarded-For 対応 |

### 6.2 フロントエンド

| カテゴリ | 技術 | 備考 |
|---------|------|------|
| 言語 | JavaScript（バニラ） | フレームワーク不使用 |
| マークアップ | HTML5 | Jinja2テンプレート |
| スタイル | CSS3 | CSS変数、Glassmorphism、MD3デザイントークン |
| フォント | Google Fonts | Noto Sans JP + Inter |
| カメラAPI | MediaDevices.getUserMedia | WebRTC |
| 画像処理 | Canvas API | フレーム差分計算、画像クロップ |
| データ永続化 | localStorage | API使用量の日次管理 |

### 6.3 外部サービス

| サービス | 用途 | 備考 |
|---------|------|------|
| Google Cloud Vision API | テキスト抽出 + 物体検出 | `DOCUMENT_TEXT_DETECTION` + `OBJECT_LOCALIZATION` |
| Google Fonts | Webフォント配信 | Noto Sans JP + Inter |

### 6.4 開発・CI/CD ツール

| カテゴリ | ツール | 用途 |
|---------|-------|------|
| テスト | pytest | 単体テスト + APIテスト |
| E2Eテスト | Playwright | ブラウザ自動テスト |
| リンター | ruff | Pythonコードスタイルチェック |
| セキュリティスキャン | bandit | Python静的セキュリティ解析 |
| 依存関係監査 | pip-audit | 脆弱性チェック |
| シークレット検出 | detect-secrets | pre-commit + CI |
| CI/CD | GitHub Actions | 自動テスト + 品質チェック |
| 依存管理 | Dependabot | pip依存 + GitHub Actions 週次チェック |
| バージョン管理 | Git + GitHub | ブランチ保護、コンベンショナルコミット |

### 6.5 セキュリティ構成まとめ

| レイヤー | 対策 |
|---------|------|
| **トランスポート** | HTTPS必須（本番）、SSL検証設定（`VERIFY_SSL`） |
| **認証** | APIキーヘッダー送信、管理APIシークレット認証 |
| **入力検証** | Base64検証、MIMEマジックバイト検証、サイズ上限、モード列挙チェック |
| **出力エスケープ** | CSP nonce、DOM API（innerHTML禁止）、X-Content-Type-Options |
| **アクセス制御** | CORS Origin制限、IP単位レート制限、Permissions-Policy |
| **ヘッダー保護** | CSP、X-Frame-Options、Referrer-Policy、Cache-Control |
| **ログ安全** | プロキシURL認証情報マスク、APIレスポンス文字数制限 |
| **運用** | 相関ID（X-Request-Id）、ヘルスチェック（/healthz, /readyz） |
