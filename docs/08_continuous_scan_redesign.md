# 08 連続スキャンロジック再設計

## 変更概要

フロントエンドの連続スキャン（連続読み）ロジックを、Gemini-Vision処理プロジェクトと同等の品質に引き上げる。

## 変更動機

| 課題 | 旧実装 | 新実装 |
|------|--------|--------|
| 状態管理の複雑さ | 4つの独立したブーリアンフラグ | 正式な状態機械（ScanState列挙 + 遷移テーブル） |
| スキャンモードの選択肢 | 常に連続スキャン | ワンショット / 連続よみ 切替（localStorage永続化） |
| 同一画像の無駄なAPI送信 | なし | 画像ハッシュ比較（8x8グレースケール、閾値95%） |
| エラー時のリトライ | 固定5秒 | 指数バックオフ + ジッター（5秒〜60秒） |
| レート制限のUX | エラー表示のみ | COOLDOWNカウントダウンUI |
| 安定化検出の応答性 | 30フレーム（約1秒） | 20フレーム（約0.67秒） |
| 次スキャンまでの待機 | 10秒 | 3秒 |
| 重複停止中のCPU負荷 | 毎フレーム処理 | 15フレーム間引き（約2fps） |
| 結果指紋の精度 | 大文字小文字区別あり、確信度含む | lowercase正規化、確信度除去、検出数プレフィックス |

## 状態機械

### 状態一覧

| 状態 | 説明 |
|------|------|
| `IDLE` | 待機中。スタートボタンで`SCANNING`へ遷移 |
| `SCANNING` | フレーム監視中。安定化検出ループが動作 |
| `ANALYZING` | API送信中。ボタン無効化 |
| `PAUSED_ERROR` | エラーによる一時停止。指数バックオフで自動復帰 |
| `PAUSED_DUPLICATE` | 重複検出による一時停止。カメラ動きで自動復帰 |
| `COOLDOWN` | レート制限カウントダウン中。ボタン無効化 |

### 許可される遷移

```
IDLE              → SCANNING
SCANNING          → IDLE, ANALYZING, PAUSED_DUPLICATE
ANALYZING         → IDLE, SCANNING, PAUSED_ERROR, PAUSED_DUPLICATE, COOLDOWN
PAUSED_ERROR      → IDLE, SCANNING
PAUSED_DUPLICATE  → IDLE, SCANNING
COOLDOWN          → IDLE, SCANNING
```

## 連続スキャンフロー

### ワンショットモード
```
IDLE → SCANNING → ANALYZING → IDLE（結果表示）
```

### 連続よみモード
```
IDLE → SCANNING → ANALYZING → SCANNING（3秒インターバル）→ SCANNING → ...
```

### 重複検出時
```
... → ANALYZING → PAUSED_DUPLICATE（カメラ動き待機）→ SCANNING → ...
```

### エラー時
```
... → ANALYZING → PAUSED_ERROR → SCANNING（指数バックオフ後）→ ...
```

### レート制限時
```
... → ANALYZING → COOLDOWN（カウントダウン）→ IDLE or SCANNING
```

## 画像ハッシュ

- **方式**: 8x8ピクセルに縮小し、ITU-R BT.601輝度変換でグレースケール化
- **比較**: 64要素の差分合計から類似度（0.0〜1.0）を算出
- **閾値**: 0.95以上で同一画像と判定、API送信をスキップ

## 指数バックオフ

```
delay = min(BASE_DELAY × 2^(n-1) × jitter, MAX_DELAY)
  BASE_DELAY = 5000ms
  MAX_DELAY  = 60000ms
  jitter     = 0.75 + random() × 0.5
```

連続エラー時: 5秒 → 10秒 → 20秒 → 40秒 → 60秒（上限）

## 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `static/script.js` | 状態機械・画像ハッシュ・連続よみ切替・指数バックオフ・COOLDOWN |
| `templates/index.html` | スキャンモードボタン追加・ヘルプ説明追加 |
| `static/style.css` | cooldown/interval-wait/paused-duplicate/scan-mode-btn CSS追加 |

## バックエンドへの影響

なし。フロントエンドのみの変更。
