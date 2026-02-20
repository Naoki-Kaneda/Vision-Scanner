# Vision AI Scanner

カメラ映像からリアルタイムでテキスト抽出（OCR）・物体検出を行うWebアプリケーション。

## 機能

| 機能 | 説明 |
|------|------|
| テキスト抽出 | カメラに映した文字をOCRで読み取り |
| 物体検出 | 映像内の物体を識別（日本語ラベル付き） |
| 静止検知撮影 | カメラが安定したら自動撮影 |
| API使用量管理 | クライアント側+サーバー側のレート制限 |
| レスポンシブUI | PC・モバイル両対応 |

## セットアップ

### 必要なもの
- Python 3.9以上
- Google Cloud Vision APIキー

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/your-username/vision-ai-scanner.git
cd vision-ai-scanner

# 仮想環境の作成と有効化
python -m venv venv
venv\Scripts\Activate.ps1   # Windows (PowerShell)
# source venv/bin/activate  # Mac/Linux

# 依存ライブラリのインストール
pip install -r requirements.txt
```

### 3. 環境変数の設定

`.env.example` をコピーして `.env` ファイルを作成し、APIキーを設定してください。

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**
```bash
cp .env.example .env
```

`.env` ファイルを開き、`VISION_API_KEY` にGoogle Cloud Vision APIのキーを入力してください。

```env
# 必須: Google Cloud Vision APIキー
VISION_API_KEY=your_api_key_here

# オプション: プロキシURL（企業ネットワーク等）
PROXY_URL=

# オプション: SSL検証（デフォルト: true）
VERIFY_SSL=true

# オプション: デバッグモード（デフォルト: false）
FLASK_DEBUG=false
```

### 4. 開発用ツールのインストール（任意）

テストや静的解析を行う場合は追加パッケージをインストールします。

```bash
pip install -r requirements-dev.txt
```

## 🚀 使い方

### アプリケーションの起動

**Windows (PowerShell):**
```powershell
python app.py
```

**macOS / Linux:**
```bash
python3 app.py
```

ブラウザで `http://localhost:5000` にアクセスしてください。

### プロキシ環境下での利用

社内プロキシ等が必要な場合は `.env` の `PROXY_URL` を設定してください。

画面右上の **"Proxy設定: ON/OFF"** バッジは、現在のプロキシ設定状態を表示します（実通信の成否ではありません）。
切替は `.env` の `NO_PROXY_MODE` で行ってください（`true` で無効化）。

### 操作方法

1. **カメラを許可** → 映像が表示されます
2. **「スタート」ボタン**を押す → スキャン開始
3. カメラを文字や物体に向けて**約1秒静止** → 自動撮影
4. 結果が右パネルに表示されます

### モード切替
- **テキスト**: 文字を読み取る（OCR）
- **物体**: 映っている物体を検出

## テスト

```bash
pip install pytest
pytest tests/ -v
```

## 運用ポリシー

### APIキーの読み込み方針

`VISION_API_KEY` は**起動時に1回だけ読み込み**、プロセス終了まで固定です。

- `.env` を変更した場合は**サーバー再起動が必要**です
- `/readyz` エンドポイントは起動時に読み込んだ `API_KEY` の存在を確認します
- 動的な再読込には対応していません（意図的な設計判断です）
- APIキーはヘッダー（`x-goog-api-key`）で送信されます（URLパラメータには含まれません）

### APIキーのローテーション手順

APIキーの漏えいが疑われる場合は、以下の手順で即座に無効化・再発行してください。

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) にアクセス
2. 漏えいしたキーの **「キーを制限」** → **「キーを無効にする」** をクリック
3. **「認証情報を作成」** → **「APIキー」** で新しいキーを発行
4. 新しいキーに **APIの制限**（Cloud Vision API のみ許可）と **IPアドレス制限** を設定
5. `.env` の `VISION_API_KEY` を新しいキーに更新
6. サーバーを再起動して反映

> **重要**: キー制限（許可するAPI + 許可するIP/リファラー）を必ず設定してください。制限なしのキーは不正利用のリスクがあります。

### ADMIN_SECRET の運用

- **未設定時**: 管理API（`POST /api/config/proxy`）は常に403を返します（安全側に倒れる）
- **本番環境**: 32文字以上のランダム値を設定してください
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- シークレットは `X-Admin-Secret` ヘッダーで送信します

### デプロイ前チェックリスト

本番環境にデプロイする前に、以下を必ず確認してください。

- [ ] `VISION_API_KEY` にAPI制限（Cloud Vision APIのみ + IP制限）が設定されている
- [ ] `ADMIN_SECRET` が `secrets.token_urlsafe(32)` 等で生成された高エントロピー値である
- [ ] `ADMIN_SECRET` が16文字以上かつ、大文字・小文字・数字・記号のうち3種以上を含む
- [ ] `FLASK_DEBUG=false` になっている
- [ ] `VERIFY_SSL=true` になっている（企業プロキシ環境を除く）
- [ ] `REDIS_URL` が設定されている（マルチプロセス運用時は必須）
- [ ] `.env` がGitにコミットされていない（`git status` で確認）
- [ ] 起動ログに `WARNING` が出ていない

### ログポリシー

| 項目 | 設定 |
|------|------|
| ログレベル | `INFO`（デフォルト）。`FLASK_DEBUG=true` で `DEBUG` |
| マスキング対象 | プロキシURL内の認証情報（`user:pass` → `***:***`） |
| APIレスポンス最大文字数 | エラー時 500文字に制限 |
| 相関ID | 全リクエストに `request_id` を付与（`X-Request-Id` ヘッダー + ログ） |
| 秘密情報 | `VISION_API_KEY` はログに出力されません（URLパラメータのため） |

### ブランチ保護（CI必須化）

`main` ブランチへのマージ前にCIの全チェックを必須にすることで、壊れたコードの混入を防止します。

**GitHub UIでの設定手順:**

1. リポジトリの **Settings** > **Branches** を開く
2. **Add branch protection rule** をクリック
3. **Branch name pattern** に `main` を入力
4. 以下を有効化:
   - **Require a pull request before merging**（直接pushを禁止）
   - **Require status checks to pass before merging**
     - 必須チェックとして `test (3.11)`, `test (3.12)`, `test (3.13)` を追加
   - **Require branches to be up to date before merging**（ベースブランチとの最新同期を強制）
5. **Create** または **Save changes** をクリック

> **注意**: GitHub Free（パブリックリポジトリ）またはTeam以上のプランで利用可能です。

### 運用監視ポイント

| リスク | 検知方法 | 対処 |
|--------|----------|------|
| **秘密情報の漏えい** | `detect-secrets`（pre-commit + CI）、`.env` は `.gitignore` 対象 | `.env.example` のみコミット。git履歴に漏れた場合は `git filter-repo` で除去 |
| **レート制限のインメモリフォールバック** | 起動ログ `"Redis接続..."` の有無、`/readyz` の拡張で検知可能 | `REDIS_URL` 未設定 or Redis停止時にフォールバック。マルチプロセス（gunicorn等）では**必ず Redis を使用**すること |

### ヘルスチェック

| エンドポイント | 用途 | 正常時 | 異常時 |
|---------------|------|--------|--------|
| `GET /healthz` | Liveness（プロセス生存確認） | `200 {"status": "ok"}` | 応答なし |
| `GET /readyz` | Readiness（処理可能確認） | `200 {"status": "ok"}` | `503 {"status": "not_ready"}` |

`/readyz` は以下の条件で `503` を返します:
- `VISION_API_KEY` が未設定
- `REDIS_URL` が設定されているが Redis接続に失敗しインメモリにフォールバックしている

フォールバック時のレスポンス例:
```json
{
  "status": "not_ready",
  "checks": {
    "api_key_configured": true,
    "rate_limiter_backend": "in_memory",
    "rate_limiter_ok": false
  },
  "warnings": ["REDIS_URL が設定されていますが、Redis接続に失敗しインメモリにフォールバックしています"]
}
```

## 既知の制限

- **API上限**: サーバー側 20回/分・1000回/日（IP単位、環境変数で変更可能）。フロントはサーバーから動的取得
- **対応ブラウザ**: Chrome, Edge, Firefox（カメラアクセスにHTTPSまたはlocalhost必須）
- **言語ヒント**: 英語（`en`）に最適化。日本語テキストの認識精度は限定的
- **PCカメラ**: インカメラのみの場合、文字をカメラに向けて映す必要あり
- **レート制限**: Redis未接続時はインメモリフォールバック（プロセス再起動でリセット）

## 技術スタック

- **バックエンド**: Python / Flask
- **フロントエンド**: HTML / CSS / JavaScript（バニラ）
- **API**: Google Cloud Vision API
- **テスト**: pytest / Playwright（E2E）
- **CI**: GitHub Actions（pytest + ruff + bandit + pip-audit + detect-secrets）
- **依存管理**: Dependabot（pip + GitHub Actions 週次チェック）
