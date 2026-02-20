# デプロイガイド

Vision AI Scanner のローカル開発環境セットアップからクラウドデプロイまでの手順を解説します。

> **本番URL**: https://vision-scanner.onrender.com/

---

## 目次

1. [ローカル開発環境セットアップ](#1-ローカル開発環境セットアップ)
2. [環境変数の設定](#2-環境変数の設定)
3. [ローカル起動手順](#3-ローカル起動手順)
4. [Render へのデプロイ手順](#4-render-へのデプロイ手順)
5. [CI/CD パイプライン](#5-cicd-パイプライン)
6. [pre-commit フックの設定](#6-pre-commit-フックの設定)

---

## 1. ローカル開発環境セットアップ

### 前提条件

| 項目 | バージョン |
|------|-----------|
| Python | 3.12.0（`runtime.txt` で指定） |
| pip | 最新版を推奨 |
| Git | 2.x 以上 |
| Google Cloud Vision API キー | 必須（取得手順は後述） |

### 1-1. リポジトリのクローン

```bash
git clone https://github.com/your-username/vision-ai-scanner.git
cd vision-ai-scanner
```

### 1-2. Python 仮想環境の作成

仮想環境を使うことで、システムの Python 環境を汚さずにプロジェクト固有の依存関係を管理できます。

**Windows（PowerShell）:**

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

> 仮想環境が有効になると、プロンプトの先頭に `(venv)` と表示されます。

### 1-3. 依存ライブラリのインストール

本番用の依存関係をインストールします。

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**依存ライブラリ一覧（`requirements.txt`）:**

| ライブラリ | バージョン | 用途 |
|-----------|-----------|------|
| Flask | 3.1.3 | Web フレームワーク |
| requests | 2.32.5 | HTTP クライアント（Vision API 呼び出し） |
| python-dotenv | 1.2.1 | `.env` ファイルの環境変数読み込み |
| Pillow | 12.1.1 | 画像前処理（コントラスト・シャープネス強調） |
| cachetools | 5.5.2 | インメモリレート制限のTTLキャッシュ |
| redis | 5.2.1 | Redis バックエンドレート制限 |
| gunicorn | 23.0.0 | 本番用 WSGI サーバー |

### 1-4. 開発用ツールのインストール（任意）

テスト・リント・セキュリティスキャンを行う場合は、開発用パッケージも追加します。

```bash
pip install -r requirements-dev.txt
```

開発用パッケージには以下が含まれます:
- **pytest** : テスト実行
- **ruff** : Python リンター
- **bandit** : セキュリティ静的解析
- **pip-audit** : 依存関係の脆弱性チェック
- **detect-secrets** : シークレット検出

---

## 2. 環境変数の設定

### 2-1. `.env` ファイルの作成

`.env.example` をコピーして `.env` を作成します。

**Windows（PowerShell）:**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

### 2-2. 環境変数一覧

`.env` ファイルで設定可能な全変数の一覧です。

| 変数名 | 必須 | デフォルト値 | 説明 |
|--------|------|-------------|------|
| `VISION_API_KEY` | **必須** | なし | Google Cloud Vision API キー。起動時に1回だけ読み込まれ、プロセス終了まで固定。変更時はサーバー再起動が必要 |
| `PROXY_URL` | 任意 | 空文字 | 企業プロキシの URL。社内ネットワーク経由で外部 API に接続する場合に設定 |
| `VERIFY_SSL` | 任意 | `true` | SSL 証明書検証の有効/無効。企業プロキシ環境でのみ `false` に設定 |
| `NO_PROXY_MODE` | 任意 | `false` | `true` にすると `PROXY_URL` の設定を無視して直接接続 |
| `TRUST_PROXY` | 任意 | `false` | リバースプロキシ（nginx 等）の背後で動作する場合に `true`。`X-Forwarded-For` ヘッダーからクライアント IP を取得 |
| `FLASK_DEBUG` | 任意 | `false` | Flask のデバッグモード。**本番環境では必ず `false`** |
| `ADMIN_SECRET` | 任意 | 空文字 | 管理 API（プロキシ設定変更）の認証シークレット。未設定時は管理 API が常に 403 を返す（安全側）。本番では 32 文字以上のランダム値を推奨 |
| `REDIS_URL` | 任意 | 空文字 | Redis の接続 URL。マルチプロセス（gunicorn 等）でのレート制限に必須。未設定時はインメモリフォールバック |
| `ALLOWED_ORIGINS` | 任意 | 空文字 | CORS で許可する Origin（カンマ区切り）。未設定時は同一オリジンのみ許可 |
| `RATE_LIMIT_PER_MINUTE` | 任意 | `20` | IP あたりの分間リクエスト上限 |
| `RATE_LIMIT_DAILY` | 任意 | `1000` | IP あたりの日次リクエスト上限 |

### 2-3. Google Cloud Vision API キーの取得

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. プロジェクトを作成（または既存のプロジェクトを選択）
3. **API とサービス** > **ライブラリ** で「Cloud Vision API」を検索し、**有効化**
4. **API とサービス** > **認証情報** > **認証情報を作成** > **API キー**
5. 作成されたキーに以下の制限を設定（推奨）:
   - **API の制限**: 「Cloud Vision API」のみ許可
   - **アプリケーションの制限**: IP アドレス制限（サーバーの IP）
6. キーを `.env` の `VISION_API_KEY` に設定

### 2-4. ADMIN_SECRET の生成

本番環境では、以下のコマンドで安全なランダム値を生成してください。

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

出力されたランダム文字列を `.env` の `ADMIN_SECRET` に設定します。

---

## 3. ローカル起動手順

### 3-1. 開発サーバーの起動

```bash
python app.py
```

ブラウザで `http://localhost:5000` にアクセスすると、アプリケーションが表示されます。

### 3-2. 起動確認

起動後、以下のエンドポイントで正常動作を確認できます。

```bash
# Liveness（プロセス生存確認）
curl http://localhost:5000/healthz
# 期待レスポンス: {"status":"ok"}

# Readiness（処理可能確認）
curl http://localhost:5000/readyz
# 期待レスポンス: {"status":"ok","checks":{...}}
```

### 3-3. 起動ログの確認

正常起動時は以下のようなログが出力されます。

```
2026-02-20 10:00:00 [INFO] rate_limiter: レート制限: インメモリバックエンド（シングルプロセスのみ）
2026-02-20 10:00:00 [INFO] werkzeug:  * Running on http://127.0.0.1:5000
```

起動ログに `WARNING` が出ている場合は、設定を見直してください。確認すべき警告は以下の通りです:

| 警告内容 | 原因 | 対処 |
|---------|------|------|
| `ADMIN_SECRET が未設定です` | `ADMIN_SECRET` が空 | 開発環境では無視可。本番では必ず設定 |
| `ADMIN_SECRET が短すぎます` | 16 文字未満 | より長いランダム値を設定 |
| `ADMIN_SECRET のエントロピーが低い` | 文字種が3種類未満 | `secrets.token_urlsafe(32)` で再生成 |
| `Redis接続失敗、インメモリにフォールバック` | `REDIS_URL` が無効 | Redis の接続情報を確認。ローカル開発では無視可 |

---

## 4. Render へのデプロイ手順

[Render](https://render.com/) は、GitHub リポジトリと連携して自動デプロイを行えるクラウドプラットフォームです。

### 4-1. Render アカウントの作成

1. [Render のサインアップページ](https://dashboard.render.com/register) にアクセス
2. **GitHub アカウント** でサインアップ（推奨）、またはメールアドレスで登録
3. メールアドレスの確認を完了

### 4-2. GitHub リポジトリの接続

1. Render ダッシュボードで **「New +」** ボタンをクリック
2. **「Web Service」** を選択
3. **「Connect a repository」** セクションで GitHub を選択
4. リポジトリの一覧から **vision-ai-scanner** を選択
5. 「Connect」をクリック

> 初回接続時は GitHub の認可画面が表示されます。「Authorize Render」をクリックしてアクセスを許可してください。

### 4-3. ビルド設定

リポジトリに `render.yaml` が含まれているため、基本設定は自動で反映されます。手動で設定する場合は以下の通りです。

| 設定項目 | 値 |
|---------|-----|
| **Name** | `vision-scanner` |
| **Region** | お好みのリージョン（例: Oregon (US West)、Singapore） |
| **Branch** | `main` |
| **Runtime** | Python |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 30` |

**`render.yaml` の内容:**

```yaml
services:
  - type: web
    name: vision-scanner
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 30
    envVars:
      - key: VISION_API_KEY
        sync: false  # Render ダッシュボードで手動設定
      - key: ADMIN_SECRET
        sync: false
      - key: FLASK_DEBUG
        value: "false"
      - key: VERIFY_SSL
        value: "true"
      - key: NO_PROXY_MODE
        value: "true"
      - key: PYTHON_VERSION
        value: "3.12.0"
```

> `sync: false` のマークが付いた変数（`VISION_API_KEY`, `ADMIN_SECRET`）は、`render.yaml` にはシークレット値を書かず、Render のダッシュボードから手動で設定します。

### 4-4. 環境変数の設定（Render ダッシュボード）

デプロイ前に、Render ダッシュボードでシークレットを設定します。

1. 作成した Web Service のページを開く
2. 左メニューの **「Environment」** をクリック
3. **「Add Environment Variable」** で以下を追加:

| キー | 値 | 備考 |
|-----|-----|------|
| `VISION_API_KEY` | 本番用 API キー | Google Cloud Console で発行したキー |
| `ADMIN_SECRET` | ランダム生成した文字列 | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

> 以下の変数は `render.yaml` で自動設定されるため、手動設定は不要です:
> - `FLASK_DEBUG` = `false`
> - `VERIFY_SSL` = `true`
> - `NO_PROXY_MODE` = `true`
> - `PYTHON_VERSION` = `3.12.0`

4. 必要に応じて以下も追加:

| キー | 値 | 備考 |
|-----|-----|------|
| `REDIS_URL` | Redis の接続 URL | Render の Redis アドオンを使う場合は自動注入 |
| `ALLOWED_ORIGINS` | 許可する Origin | 例: `https://your-app.onrender.com` |
| `RATE_LIMIT_PER_MINUTE` | 分間上限 | デフォルト 20 |
| `RATE_LIMIT_DAILY` | 日次上限 | デフォルト 1000 |

5. **「Save Changes」** をクリック

### 4-5. デプロイの実行

1. 環境変数の設定が完了したら、**「Manual Deploy」** > **「Deploy latest commit」** をクリック
2. ビルドログがリアルタイムで表示されます
3. デプロイが成功すると、`https://vision-scanner.onrender.com`（サービス名に依存）の URL が割り当てられます

### 4-6. デプロイ後の確認

```bash
# Liveness チェック
curl https://vision-scanner.onrender.com/healthz

# Readiness チェック
curl https://vision-scanner.onrender.com/readyz
```

`/readyz` のレスポンスで `"status": "ok"` が返れば、正常にデプロイされています。

### 4-7. 自動デプロイ

Render はデフォルトで **main ブランチへの push 時に自動デプロイ** を実行します。

- GitHub で Pull Request をマージすると、自動的にビルド・デプロイが開始されます
- ダッシュボードの **「Settings」** > **「Auto-Deploy」** で有効/無効を切り替え可能

### 4-8. 無料枠の制限事項

Render の無料プラン（Free Instance Type）には以下の制限があります。

| 制限項目 | 詳細 |
|---------|------|
| **15 分スリープ** | 15 分間リクエストがないとインスタンスがスリープ状態になる。次のリクエスト時にコールドスタート（約 30〜60 秒の遅延）が発生 |
| **月間稼働時間** | 無料枠には月あたりの稼働時間制限がある |
| **ビルド時間** | 月間のビルド時間に制限あり |
| **インメモリデータの消失** | スリープ・再起動時にインメモリのレート制限カウンターがリセットされる。本番運用では Redis の利用を強く推奨 |
| **カスタムドメイン** | 無料枠でもカスタムドメインの設定は可能 |
| **帯域幅** | 月間の帯域幅に上限あり |

> **対策**: スリープを回避したい場合は、外部の監視サービス（UptimeRobot 等）から `/healthz` に定期的にリクエストを送る方法があります。ただし、Render の利用規約に従ってください。

---

## 5. CI/CD パイプライン

GitHub Actions を使った自動テスト・セキュリティチェックの仕組みです。

### 5-1. CI ワークフロー（`.github/workflows/ci.yml`）

`main` ブランチへの push および Pull Request 時に自動実行されます。

**実行マトリクス**: Python 3.11 / 3.12 / 3.13 の 3 バージョンで並列実行

**実行ステップ:**

| ステップ | 説明 | 失敗時の影響 |
|---------|------|-------------|
| 1. リポジトリのチェックアウト | `actions/checkout@v4` | ワークフロー全体が失敗 |
| 2. Python セットアップ | `actions/setup-python@v5` | ワークフロー全体が失敗 |
| 3. 依存関係インストール | `requirements-lock.txt` + `requirements-dev.txt` | 後続ステップが失敗 |
| 4. シークレット検出 | `detect-secrets scan` でコード内のシークレット候補を検出 | 警告のみ（ワークフローは続行） |
| 5. Ruff リントチェック | コードスタイル・品質チェック | PR マージがブロックされる |
| 6. Bandit セキュリティスキャン | Python コードのセキュリティ脆弱性を静的解析 | PR マージがブロックされる |
| 7. pip-audit 脆弱性チェック | 依存ライブラリの既知の脆弱性を検出 | PR マージがブロックされる |
| 8. pytest テスト実行 | 単体テストの実行（`VISION_API_KEY` はダミー値） | PR マージがブロックされる |

### 5-2. シークレット定期スキャン（`.github/workflows/secrets-scan.yml`）

毎週月曜 9:00（JST）に自動実行されるセキュリティスキャンです。

- **実行タイミング**: 毎週月曜 9:00 JST（cron: `0 0 * * 1` UTC）
- **手動実行**: GitHub の Actions タブから `workflow_dispatch` で手動実行も可能
- **スキャン対象**: リポジトリ全体（`.lock` ファイル、`.secrets-baseline` ファイル、`venv/` ディレクトリは除外）
- **検出時のアクション**: シークレット候補が見つかった場合、`security` ラベル付きの Issue を自動作成

### 5-3. ブランチ保護ルールの推奨設定

CI を有効に機能させるため、GitHub のブランチ保護ルールを設定してください。

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

## 6. pre-commit フックの設定

コミット前にリント・シークレット検出を自動実行する仕組みです。

### 6-1. pre-commit のインストール

```bash
pip install pre-commit
```

### 6-2. フックのインストール

```bash
pre-commit install
```

これにより、`git commit` 実行時に自動でフックが走ります。

### 6-3. フックの内容（`.pre-commit-config.yaml`）

| フック | リポジトリ | バージョン | 説明 |
|--------|-----------|-----------|------|
| `detect-secrets` | Yelp/detect-secrets | v1.5.0 | API キー・パスワード等のシークレットがコードに含まれていないか検出。`.secrets.baseline` をベースラインとして使用 |
| `ruff` | astral-sh/ruff-pre-commit | v0.9.6 | Python のリント + 自動修正（`--fix` オプション付き） |

### 6-4. ベースラインの初期化（初回のみ）

`detect-secrets` はベースラインファイルを使って誤検知を管理します。

```bash
# ベースラインファイルを生成
detect-secrets scan --exclude-files '\.lock$' > .secrets.baseline

# ベースラインの確認・更新
detect-secrets audit .secrets.baseline
```

### 6-5. 手動でのフック実行

コミットせずにフックだけ実行したい場合:

```bash
# 全ファイルに対して実行
pre-commit run --all-files

# 特定のフックのみ実行
pre-commit run detect-secrets --all-files
pre-commit run ruff --all-files
```

### 6-6. フックのスキップ（緊急時のみ）

```bash
# フックを一時的にスキップ（推奨しません）
git commit --no-verify -m "fix: 緊急修正"
```

> フックをスキップした場合でも、CI のステータスチェックで検出されます。

---

## 補足: Python バージョンの管理

- `runtime.txt` にはデプロイ先で使用する Python バージョン（`python-3.12.0`）が記載されています
- `render.yaml` の `PYTHON_VERSION` 環境変数でも同じバージョンを指定しています
- ローカル開発でも Python 3.12 を使用することを推奨します
- CI では Python 3.11 / 3.12 / 3.13 の 3 バージョンでテストを実行し、互換性を確認しています
