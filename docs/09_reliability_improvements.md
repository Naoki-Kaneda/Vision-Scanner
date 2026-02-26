# 09 信頼性・堅牢性向上（3件）

## 変更概要

フロントエンド・バックエンドの信頼性を向上させる3つの改善を実施する。

## 改善一覧

| # | 改善内容 | 対象 | 重要度 |
|---|---------|------|--------|
| 1 | 429応答にRetry-Afterヘッダー追加 | バックエンド + フロントエンド | 中〜高 |
| 2 | AbortControllerによるfetchレースコンディション防止 | フロントエンド | 中 |
| 3 | 構造化ログ + PIIマスキング | バックエンド | 中 |

---

## 改善1: Retry-After ヘッダー

### 問題
バックエンドの429レスポンスに`Retry-After`ヘッダーが含まれていない。フロントエンドはデフォルト10秒を使用しているが、実際のレート制限ウィンドウと乖離している。

### 解決策

**バックエンド（`app.py`）:**
- `_error_response()`に`headers`引数を追加
- 分間制限: `Retry-After: 60`（60秒ウィンドウ）
- 日次制限: `Retry-After: <翌日0時までの秒数>`
- JSON本文にも `retry_after` フィールドを追加
- 管理APIブロック: `Retry-After: <ブロック残り秒数>`

**フロントエンド（`script.js`）:**
- 既存コードで対応済み（`result.retry_after || response.headers.get('Retry-After') || '10'`）
- `limit_type: 'daily'` で日次上限の自動停止処理を改善

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `app.py` | `_error_response()`にheaders対応、429応答にRetry-After付与 |
| `rate_limiter.py` | `try_consume()`の返却値にlimit_type追加 |

---

## 改善2: AbortController によるレースコンディション防止

### 問題
API解析中にモードを切り替えると、前のリクエストの結果が新しいモードの画面に表示されるレースコンディションが発生する可能性がある。

### 解決策

**フロントエンド（`script.js`）:**
- モジュールレベルに `analyzeAbortController` 変数を追加
- `captureAndAnalyze()`: 新規AbortControllerを作成し、タイムアウトと組み合わせてfetchに使用
- `setMode()`: 進行中のfetchをabort
- `stopScanning()`: 進行中のfetchをabort
- AbortErrorの分類: タイムアウト vs ユーザーキャンセルを区別

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `static/script.js` | `analyzeAbortController`追加、fetchシグナル変更、setMode/stopScanning改修 |

---

## 改善3: 構造化ログ + PIIマスキング

### 問題
OCR結果に含まれる可能性がある個人情報（電話番号、メールアドレス等）がデバッグログに記録される可能性がある。

### 解決策

**バックエンド:**
- `_mask_pii(text)` ユーティリティ関数を追加
  - 電話番号パターン: 日本形式 `090-1234-5678` → `090-****-****`
  - メールアドレス: `user@example.com` → `u***@example.com`
  - クレジットカード風の数字列: `1234-5678-9012-3456` → `****-****-****-3456`
- `_log()` の値にPIIマスキングを自動適用
- `vision_api.py` のテキスト結果ログにもマスキングを適用

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `app.py` | `_mask_pii()`追加、`_log()`改修 |
| `vision_api.py` | テキスト結果のログにPIIマスキング適用 |

---

## バックエンドへの影響

- `_error_response()` のシグネチャ変更（後方互換: `headers`はオプション引数）
- `rate_limiter.py` の返却タプルに `limit_type` を追加（後方互換: 既存テストのアサーション位置に影響なし）
- ログ出力形式の変更（構造は同一、値がマスクされる場合がある）
