# 運用マニュアル

Vision AI Scanner の本番運用に必要な監視・メンテナンス・障害対応の手順を解説します。

---

## 目次

1. [ヘルスチェック監視](#1-ヘルスチェック監視)
2. [ログ監視ポイント](#2-ログ監視ポイント)
3. [API キーローテーション手順](#3-api-キーローテーション手順)
4. [ADMIN_SECRET の生成・更新手順](#4-admin_secret-の生成更新手順)
5. [レート制限の調整方法](#5-レート制限の調整方法)
6. [シークレット定期スキャン](#6-シークレット定期スキャン)
7. [障害対応フロー](#7-障害対応フロー)
8. [デプロイ前チェックリスト](#8-デプロイ前チェックリスト)
9. [公開直前の最終確認 3 点](#9-公開直前の最終確認-3-点)

---

## 1. ヘルスチェック監視

### 1-1. エンドポイント一覧

本アプリケーションは 2 つのヘルスチェックエンドポイントを提供します。

| エンドポイント | 用途 | HTTP メソッド | 認証 |
|---------------|------|--------------|------|
| `GET /healthz` | Liveness（プロセス生存確認） | GET | 不要 |
| `GET /readyz` | Readiness（処理可能確認） | GET | 不要 |

### 1-2. `/healthz` — Liveness チェック

アプリケーションプロセスが起動しているかどうかを確認します。外部依存（API キー、Redis 等）の状態は検査しません。

**正常時のレスポンス（200 OK）:**

```json
{
  "status": "ok"
}
```

**異常時:** レスポンスが返らない（タイムアウト）場合、プロセスが停止しています。

**監視設定の例:**
- 監視間隔: 30 秒〜1 分
- タイムアウト: 5 秒
- アラート条件: 3 回連続でタイムアウトした場合

### 1-3. `/readyz` — Readiness チェック

アプリケーションがリクエストを処理可能な状態にあるかを確認します。以下の項目を検査します:

| 検査項目 | キー | 正常値 | 異常値 |
|---------|------|--------|--------|
| API キー設定 | `api_key_configured` | `true` | `false` |
| レート制限バックエンド | `rate_limiter_backend` | `"redis"` または `"in_memory"` | — |
| レート制限の正常性 | `rate_limiter_ok` | `true` | `false` |

**正常時のレスポンス（200 OK）:**

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

**異常時のレスポンス（503 Service Unavailable）:**

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

**`/readyz` が 503 を返す条件:**

| 条件 | 説明 |
|------|------|
| `VISION_API_KEY` が未設定 | API キーが環境変数に設定されていない |
| Redis フォールバック検知 | `REDIS_URL` が設定されているにもかかわらず、Redis への接続に失敗しインメモリにフォールバックしている |

**監視設定の例:**
- 監視間隔: 1 分
- アラート条件: ステータスコードが `503` の場合に即時通知
- 推奨アクション: `checks` オブジェクトの各フィールドを確認し、原因を特定

### 1-4. Redis フォールバック検知の詳細

`REDIS_URL` を設定してマルチプロセス運用（gunicorn）している場合、Redis への接続が失敗するとインメモリバックエンドにフォールバックします。この状態では以下の問題が発生します:

| 問題 | 影響 |
|------|------|
| レート制限がプロセス間で共有されない | gunicorn のワーカー間でカウンターが分離し、実質的に制限が `ワーカー数 x 設定値` になる |
| プロセス再起動でカウンターがリセット | スリープ復帰やデプロイ時に制限がリセットされる |

**検知方法:**

```bash
# readyz で確認
curl -s https://your-app.onrender.com/readyz | python -m json.tool

# rate_limiter_backend が "in_memory" かつ rate_limiter_ok が false の場合、フォールバック中
```

**対処:**
1. Redis サーバーの稼働状態を確認
2. `REDIS_URL` の接続文字列が正しいか確認
3. ネットワーク接続（ファイアウォール、セキュリティグループ等）を確認
4. Redis を復旧後、アプリケーションを再起動

---

## 2. ログ監視ポイント

### 2-1. ログ設定

| 項目 | 設定値 |
|------|--------|
| ログレベル | `INFO`（デフォルト）。`FLASK_DEBUG=true` で `DEBUG` |
| マスキング対象 | プロキシ URL 内の認証情報（`user:pass` → `***:***`） |
| API レスポンス最大文字数 | エラー時 500 文字に制限 |
| 相関 ID | 全リクエストに `request_id` を付与（`X-Request-Id` ヘッダー + ログ） |

### 2-2. 起動時に確認すべき WARNING

アプリケーション起動時に以下の WARNING が出力される場合は、設定を見直してください。

| 警告メッセージ | 原因 | 深刻度 | 対処 |
|---------------|------|--------|------|
| `ADMIN_SECRET が未設定です。管理API（プロキシ設定変更）は常に403を返します。` | `ADMIN_SECRET` が空 | 中 | 管理 API を使わない場合は無視可。使う場合は設定必須 |
| `ADMIN_SECRET が短すぎます（16文字以上を推奨）。` | 16 文字未満 | 高 | `secrets.token_urlsafe(32)` で再生成 |
| `ADMIN_SECRET のエントロピーが低い可能性があります` | 文字種が 3 種類未満 | 高 | ランダム生成したシークレットに変更 |
| `Redis接続失敗、インメモリにフォールバック: ...` | Redis に接続できない | 高（本番） | Redis の接続情報・稼働状態を確認 |

### 2-3. 運用中に監視すべきログイベント

構造化ログの `event` フィールドで以下のイベントを監視してください。

| イベント | ログレベル | 意味 | 対処 |
|---------|-----------|------|------|
| `api_success` | INFO | API 呼び出し成功 | 正常。件数の推移を監視 |
| `api_failure` | WARNING | Vision API からエラーが返された | `error_code` を確認。`API_KEY_INVALID` なら即座にキーを確認 |
| `rate_limited` | INFO | レート制限に到達 | 頻発する場合は上限値の調整を検討 |
| `validation_error` | WARNING | リクエストのバリデーション失敗 | 通常は不正なリクエスト。攻撃の可能性も考慮 |
| `server_error` | ERROR | 予期しないサーバーエラー | スタックトレースを確認して修正 |

### 2-4. 相関 ID によるトレース

全リクエストには `request_id`（16 桁の 16 進数文字列）が付与されます。

- **リクエスト側**: レスポンスヘッダー `X-Request-Id` で確認
- **サーバーログ側**: ログ内の `request_id=...` で検索

```bash
# 特定リクエストのログを追跡
grep "request_id=abc12345def67890" /var/log/app.log
```

---

## 3. API キーローテーション手順

API キーの漏えいが疑われる場合、または定期的なセキュリティ対策として、以下の手順でキーをローテーションします。

### 3-1. 旧キーの無効化（Google Cloud Console）

1. [Google Cloud Console の認証情報ページ](https://console.cloud.google.com/apis/credentials) にアクセス
2. 対象の API キーをクリック
3. **「キーを制限」** ページで **「キーを無効にする」** をクリック
4. 確認ダイアログで **「無効にする」** をクリック

> 漏えいが疑われる場合は、新キー発行前に旧キーを即座に無効化してください。サービスの一時停止よりもセキュリティを優先します。

### 3-2. 新キーの発行

1. 同じ認証情報ページで **「認証情報を作成」** > **「API キー」** をクリック
2. 新しいキーが自動生成されます
3. キーの値をコピー（この画面を閉じると再表示できません）

### 3-3. キーの制限設定（必須）

新しいキーに以下の制限を設定してください。制限なしのキーは不正利用のリスクがあります。

1. 作成されたキーの **「キーを制限」** をクリック
2. **API の制限**:
   - 「キーを制限」を選択
   - 「Cloud Vision API」のみにチェック
3. **アプリケーションの制限**:
   - 「IP アドレス」を選択
   - サーバーの IP アドレスを追加
4. **「保存」** をクリック

### 3-4. 環境変数の更新

**ローカル環境の場合:**

`.env` ファイルの `VISION_API_KEY` を新しいキーに書き換えます。

```env
VISION_API_KEY=新しいAPIキーの値
```

**Render の場合:**

1. Render ダッシュボードで対象サービスを開く
2. **「Environment」** をクリック
3. `VISION_API_KEY` の値を新しいキーに更新
4. **「Save Changes」** をクリック

### 3-5. サーバーの再起動

`VISION_API_KEY` は起動時に 1 回だけ読み込まれるため、**サーバーの再起動が必須** です。

**ローカル:**

```bash
# 実行中のサーバーを Ctrl+C で停止し、再起動
python app.py
```

**Render:**

- 環境変数の変更後、Render は自動的に再デプロイを実行します
- 手動で再デプロイする場合: **「Manual Deploy」** > **「Deploy latest commit」**

### 3-6. 更新後の確認

```bash
# readyz でキーの設定確認
curl -s https://your-app.onrender.com/readyz | python -m json.tool

# api_key_configured が true であることを確認
```

---

## 4. ADMIN_SECRET の生成・更新手順

`ADMIN_SECRET` は管理 API（`POST /api/config/proxy`）の認証に使用されます。

### 4-1. シークレットの生成

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

出力例: `aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE9f`

以下の要件を満たす値を使用してください:

| 要件 | 詳細 |
|------|------|
| 最低文字数 | 16 文字以上（32 文字以上を推奨） |
| 文字種 | 大文字・小文字・数字・記号のうち 3 種類以上 |
| ランダム性 | `secrets.token_urlsafe(32)` で生成したものを推奨 |

### 4-2. 環境変数への設定

**ローカル:**

`.env` ファイルの `ADMIN_SECRET` に値を設定します。

```env
ADMIN_SECRET=生成したランダム文字列
```

**Render:**

1. ダッシュボードの **「Environment」** で `ADMIN_SECRET` を更新
2. **「Save Changes」** をクリック

### 4-3. 更新後のサーバー再起動

`ADMIN_SECRET` も起動時に読み込まれるため、変更後はサーバーの再起動が必要です。

### 4-4. 動作確認

```bash
# 認証なしでアクセス（403 が返れば正常）
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://your-app.onrender.com/api/config/proxy \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
# 期待: 403

# 正しいシークレットでアクセス（200 が返れば正常）
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://your-app.onrender.com/api/config/proxy \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: 設定したシークレット" \
  -d '{"enabled": true}'
# 期待: 200
```

---

## 5. レート制限の調整方法

### 5-1. 現在の設定値

| 環境変数 | デフォルト値 | 説明 |
|---------|-------------|------|
| `RATE_LIMIT_PER_MINUTE` | 20 | IP あたりの分間リクエスト上限 |
| `RATE_LIMIT_DAILY` | 1000 | IP あたりの日次リクエスト上限 |

### 5-2. 調整手順

1. `.env`（ローカル）または Render ダッシュボード（本番）で環境変数を変更
2. サーバーを再起動

```env
# 例: 分間 10 回、日次 500 回に制限を厳しくする
RATE_LIMIT_PER_MINUTE=10
RATE_LIMIT_DAILY=500
```

### 5-3. フロントエンドへの反映

フロントエンドの日次上限表示は `/api/config/limits` エンドポイントからサーバーの `RATE_LIMIT_DAILY` を動的に取得しています。環境変数を変更してサーバーを再起動すれば、フロントエンドにも自動的に反映されます。

### 5-4. バックエンドの選択

| バックエンド | 条件 | 特性 |
|-------------|------|------|
| Redis | `REDIS_URL` が設定済みかつ接続成功 | マルチプロセス安全。Lua スクリプトで原子的操作 |
| インメモリ | `REDIS_URL` が未設定または接続失敗 | シングルプロセスのみ。再起動でカウンターリセット |

本番環境で gunicorn（複数ワーカー）を使用する場合は、必ず Redis を設定してください。

---

## 6. シークレット定期スキャン

### 6-1. 自動スキャン（GitHub Actions）

`.github/workflows/secrets-scan.yml` により、毎週月曜 9:00（JST）に自動でシークレットスキャンが実行されます。

**仕組み:**

1. `detect-secrets` でリポジトリ全体をスキャン
2. シークレット候補が検出された場合、`security` ラベル付きの Issue を自動作成
3. Issue にはファイル名・行番号・シークレットの種別が記載される

**除外対象:**
- `.lock` ファイル
- `.secrets-baseline` ファイル
- `venv/` ディレクトリ
- `.venv/` ディレクトリ

### 6-2. 手動スキャンの実行

GitHub Actions の画面から手動でスキャンを実行することもできます。

1. リポジトリの **Actions** タブを開く
2. 左メニューから **「シークレット定期スキャン」** を選択
3. **「Run workflow」** > **「Run workflow」** をクリック

### 6-3. 検出時の対応手順

Issue が作成された場合、以下の手順で対応します。

1. **判定**: 検出されたシークレットが本物か誤検知かを確認
2. **本物の場合**:
   - 該当のシークレットを即座にローテーション（[API キーローテーション手順](#3-api-キーローテーション手順) を参照）
   - コードから削除し、環境変数に移行
   - Git 履歴にシークレットが残っている場合は `git filter-repo` で除去
3. **誤検知の場合**:
   - ベースラインを更新して今後の検出から除外
   ```bash
   detect-secrets scan --update .secrets.baseline
   ```

### 6-4. pre-commit との連携

コミット前にもシークレット検出が走ります（`.pre-commit-config.yaml` で設定済み）。CI とコミット前の二重チェックにより、シークレットの漏えいリスクを最小化しています。

---

## 7. 障害対応フロー

### 7-1. API キー漏えい時の対応

**緊急度: 最高**

```
検知 → 旧キー無効化 → 新キー発行 → 環境変数更新 → 再起動 → 確認
```

| 手順 | 所要時間目安 | 詳細 |
|------|-------------|------|
| 1. 旧キーの即時無効化 | 2 分 | Google Cloud Console で対象キーを無効化。**サービス停止よりセキュリティ優先** |
| 2. 被害範囲の確認 | 5 分 | Google Cloud Console の API 使用量レポートで不正利用の有無を確認 |
| 3. 新キーの発行 | 3 分 | API 制限 + IP 制限を必ず設定 |
| 4. 環境変数の更新 | 2 分 | `.env`（ローカル）/ Render ダッシュボード（本番） |
| 5. サーバーの再起動 | 1〜3 分 | Render は環境変数変更で自動再デプロイ |
| 6. 動作確認 | 2 分 | `/readyz` で確認 |
| 7. Git 履歴のスキャン | 10 分 | `trufflehog` で Git 履歴全体をスキャン |
| 8. 履歴からの除去（該当する場合） | 15 分 | `git filter-repo` で該当ファイルを履歴から除去 |

**Git 履歴のスキャンコマンド:**

```bash
# trufflehog による全履歴スキャン
pip install trufflehog
trufflehog git file://. --only-verified

# 代替: パターンマッチによるスキャン
git log --all -p | python -c "
import sys, re
patterns = [
    (r'AIza[0-9A-Za-z\-_]{35}', 'Google APIキー'),
    (r'VISION_API_KEY\s*=\s*[A-Za-z0-9]', 'Vision APIキー代入'),
    (r'ADMIN_SECRET\s*=\s*[A-Za-z0-9]', 'Admin Secret代入'),
]
for i, line in enumerate(sys.stdin):
    for pat, label in patterns:
        if re.search(pat, line):
            print(f'検出 [{label}]: {line.rstrip()[:120]}')
" 2>/dev/null
```

**Git 履歴からの除去:**

```bash
pip install git-filter-repo
git filter-repo --path .env --invert-paths
```

### 7-2. Redis 障害時の対応

**緊急度: 中**

```
検知 → 影響確認 → Redis 復旧 → アプリ再起動 → 確認
```

| 手順 | 詳細 |
|------|------|
| 1. 検知 | `/readyz` が 503 を返す。`rate_limiter_backend: "in_memory"` かつ `rate_limiter_ok: false` |
| 2. 影響の確認 | インメモリフォールバック中もサービスは稼働を継続する。ただしレート制限がプロセス間で共有されない |
| 3. Redis 復旧 | Redis サーバーの状態を確認。接続 URL・ネットワーク設定を確認 |
| 4. アプリケーション再起動 | Redis 復旧後、アプリケーションを再起動してバックエンドを Redis に切り替え |
| 5. 確認 | `/readyz` で `rate_limiter_backend: "redis"` かつ `rate_limiter_ok: true` を確認 |

> インメモリフォールバック中、サービス自体は停止しません。ただし、gunicorn のワーカー間でレート制限カウンターが共有されないため、実質的な制限値が緩くなります。

### 7-3. Vision API のエラーが頻発する場合

| エラーコード | 原因 | 対処 |
|-------------|------|------|
| `API_KEY_INVALID` | API キーが無効 | キーの有効性を確認。ローテーション実施 |
| `QUOTA_EXCEEDED` | Google Cloud の API 割り当て超過 | Google Cloud Console で割り当てを確認・引き上げ |
| `API_ERROR` | Vision API 側の一時的障害 | 自動リトライ（3 回、指数バックオフ）を待つ。長時間続く場合は Google Cloud Status を確認 |
| `TIMEOUT` | タイムアウト | ネットワーク接続を確認。画像サイズが大きすぎないか確認 |

---

## 8. デプロイ前チェックリスト

本番環境へのデプロイ前に、以下の項目をすべて確認してください。

### セキュリティ

- [ ] `VISION_API_KEY` の旧キーが無効化されている
- [ ] 新しい `VISION_API_KEY` に API 制限（Cloud Vision API のみ）が設定されている
- [ ] 新しい `VISION_API_KEY` に IP アドレス制限が設定されている
- [ ] Git 履歴にシークレットが残っていない（trufflehog スキャン済み）
- [ ] `ADMIN_SECRET` が `secrets.token_urlsafe(32)` で生成した高エントロピー値
- [ ] `.env` が Git にコミットされていない（`git status` で確認）

### アプリケーション設定

- [ ] `FLASK_DEBUG=false` になっている
- [ ] `VERIFY_SSL=true` になっている（企業プロキシ環境を除く）
- [ ] `REDIS_URL` が設定されている（マルチプロセス運用時は必須）
- [ ] `ALLOWED_ORIGINS` が適切に設定されている（必要な場合）
- [ ] `RATE_LIMIT_PER_MINUTE` と `RATE_LIMIT_DAILY` が適切な値になっている

### インフラ

- [ ] GitHub ブランチ保護ルールが有効（CI 必須）
- [ ] CI の全ステータスチェックが通過している
- [ ] 起動ログに `WARNING` が出ていない

---

## 9. 公開直前の最終確認 3 点

本番公開の直前に、以下の 3 点を必ず確認してください。

### 確認 1: API キーのローテーション完了確認

開発中に使用した API キーをそのまま本番で使わないでください。

```bash
# 本番用に新しいキーを発行済みか確認
# Google Cloud Console > APIとサービス > 認証情報 で以下を確認:
#   - 開発中に使用したキーが無効化されている
#   - 本番用キーに API 制限（Cloud Vision API のみ）が設定されている
#   - 本番用キーに IP アドレス制限が設定されている

# .env に新しいキーが設定されていることを確認
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
k = os.getenv('VISION_API_KEY', '')
print(f'キー末尾: ...{k[-4:]}' if len(k) > 4 else '未設定')
"
```

### 確認 2: Git 履歴を含むシークレット再スキャン

過去のコミットにシークレットが含まれていないか、全履歴をスキャンします。

```bash
# trufflehog による全履歴スキャン
pip install trufflehog
trufflehog git file://. --only-verified
```

検出された場合は `git filter-repo` で履歴から除去してください。

```bash
pip install git-filter-repo
git filter-repo --path .env --invert-paths
```

### 確認 3: GitHub ブランチ保護（CI 必須）の有効化

1. リポジトリの **Settings** > **Branches** を開く
2. **Add branch protection rule** をクリック
3. **Branch name pattern** に `main` を入力
4. 以下を有効化:
   - **Require a pull request before merging**（マージ前に PR 必須）
   - **Require status checks to pass before merging**（ステータスチェック必須）
     - 必須チェック: `test (3.11)`, `test (3.12)`, `test (3.13)`
   - **Require branches to be up to date before merging**（ブランチを最新に）
5. **Create** をクリック

---

## 付録: 監視ダッシュボードの推奨構成

外部の監視サービスを使う場合、以下のチェックを設定することを推奨します。

| チェック項目 | エンドポイント | 間隔 | アラート条件 |
|-------------|--------------|------|-------------|
| プロセス生存確認 | `GET /healthz` | 30 秒 | 3 回連続タイムアウト |
| 処理可能確認 | `GET /readyz` | 1 分 | ステータスコード 503 |
| SSL 証明書有効期限 | — | 1 日 | 残り 14 日以下 |
| レスポンスタイム | `GET /healthz` | 1 分 | 5 秒超 |
