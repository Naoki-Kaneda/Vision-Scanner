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
- Git
- Google Cloud Vision APIキー（[取得方法はこちら](#google-cloud-vision-apiキーの取得方法)）

---

### Ubuntu / Linux の場合

ターミナルを開いて、以下のコマンドを **上から順番にコピペ** してください。

#### ステップ1: システムの準備（初回のみ）

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
```

#### ステップ2: ソースコードの取得

```bash
git clone https://github.com/Naoki-Kaneda/Vision-Scanner.git
cd Vision-Scanner
```

#### ステップ3: Python仮想環境の作成と有効化

```bash
python3 -m venv venv
source venv/bin/activate
```

> 成功すると、ターミナルの先頭に `(venv)` と表示されます。

#### ステップ4: ライブラリのインストール

```bash
pip install -r requirements.txt
```

#### ステップ5: APIキーの設定

```bash
cp .env.example .env
nano .env
```

エディタが開いたら、1行目の `your_api_key_here` を自分のAPIキーに書き換えてください。

```
VISION_API_KEY=ここにAPIキーを貼り付ける
```

書き換えたら `Ctrl + O` → `Enter`（保存） → `Ctrl + X`（終了）で閉じます。

#### ステップ6: 起動

```bash
chmod +x start.sh
./start.sh
```

`[OK] Flask起動中...` と表示されたら成功です。
ブラウザで **http://localhost:5000** を開いてください。

#### 次回以降の起動（2回目から）

```bash
cd Vision-Scanner
source venv/bin/activate
./start.sh
```

---

### Windows の場合

PowerShellを開いて、以下のコマンドを **上から順番にコピペ** してください。

#### ステップ1: ソースコードの取得

```powershell
git clone https://github.com/Naoki-Kaneda/Vision-Scanner.git
cd Vision-Scanner
```

> Git が入っていない場合は https://git-scm.com からインストールしてください。

#### ステップ2: Python仮想環境の作成と有効化

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

> `venv\Scripts\Activate.ps1` でエラーが出る場合:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```
> を実行してから再度お試しください。

#### ステップ3: ライブラリのインストール

```powershell
pip install -r requirements.txt
```

#### ステップ4: APIキーの設定

```powershell
Copy-Item .env.example .env
notepad .env
```

メモ帳が開いたら、1行目の `your_api_key_here` を自分のAPIキーに書き換えて保存してください。

```
VISION_API_KEY=ここにAPIキーを貼り付ける
```

#### ステップ5: 起動

```powershell
start.bat
```

またはダブルクリックでも起動できます。

`[OK] Flask起動中...` と表示されたら成功です。
ブラウザで **http://localhost:5000** を開いてください。

#### 次回以降の起動（2回目から）

```powershell
cd Vision-Scanner
venv\Scripts\Activate.ps1
start.bat
```

---

### Google Cloud Vision APIキーの取得方法

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセスしてログイン
2. プロジェクトを作成（または既存プロジェクトを選択）
3. 左メニュー「APIとサービス」→「ライブラリ」→ **Cloud Vision API** を検索して「有効にする」
4. 左メニュー「APIとサービス」→「認証情報」→「認証情報を作成」→「APIキー」
5. 作成されたAPIキーをコピーして `.env` に貼り付ける

> セキュリティのため、APIキーに「Cloud Vision API のみ許可」の制限を設定することを推奨します。

---

### 開発用ツールのインストール（任意）

テストや静的解析を行う場合は追加パッケージをインストールします。

```bash
pip install -r requirements-dev.txt
```

## 使い方

### アプリケーションの起動

| OS | コマンド |
|---|---|
| Ubuntu / Linux | `./start.sh`（または `python3 app.py`） |
| Windows | `start.bat`（または `python app.py`） |

ブラウザで **http://localhost:5000** にアクセスしてください。

### プロキシ環境下での利用

社内プロキシ等が必要な場合は `.env` の `PROXY_URL` を設定してください。

画面右上の **"Proxy設定: ON/OFF"** バッジは、現在のプロキシ設定状態を表示します（実通信の成否ではありません）。
切替は `.env` の `NO_PROXY_MODE` で行ってください（`true` で無効化）。

### 操作方法

1. **カメラを許可** → 映像が表示されます
2. **「スタート」ボタン**を押す → スキャン開始
3. カメラを文字や物体に向けて**約1秒静止** → 自動撮影
4. 結果が右パネルに表示されます

### 重複スキップ設定

同じ被写体を連続で読み取った際に、自動的にAPI呼び出しを一時停止する機能です。

- **設定場所**: 画面右下の **?（ヘルプ）ボタン** → 「設定」セクション
- **スライダー範囲**: 1〜5回（既定値: 2回）
- **動作**: 指定回数だけ同じ結果が連続したら一時停止。カメラを動かすと自動再開
- **保存**: 設定値はブラウザに保存され、再読込後も維持されます

### モード切替
- **テキスト**: 文字を読み取る（OCR）
- **物体**: 映っている物体を検出
- **ラベル**: ラベル・シールの有無を判定
- **顔検出**: 顔の位置と感情を分析
- **ロゴ**: ブランドロゴを検出
- **分類**: 画像全体をカテゴリ分類
- **Web検索**: Web上の類似画像を検索

### モード別レスポンス仕様

`POST /api/analyze` のレスポンスはモードにより固有フィールドが追加されます。

| モード | `data` 内容 | 固有フィールド | `image_size` |
|--------|-------------|---------------|-------------|
| `text` | `{label, bounds}` テキストブロック | なし | `[w, h]` px |
| `object` | `{label, bounds}` 正規化座標(0-1) | なし | `null` |
| `label` | `{label, bounds}` テキスト検出結果 | `label_detected` (bool), `label_reason` (str) | `[w, h]` or `null` |
| `face` | `{label, bounds, emotions, confidence}` | なし | `[w, h]` px |
| `logo` | `{label, bounds}` ピクセル座標 | なし | `[w, h]` px |
| `classify` | `{label, score}` 座標なし | なし | `null` |
| `web` | `{label}` 推定ラベル | `web_detail` ({best_guess, entities, pages, similar_images}) | `null` |

共通フィールド: `ok` (bool), `data` (list), `error_code` (str\|null), `message` (str\|null)

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

### 公開直前の最終確認

#### 1. APIキーのローテーション完了確認

```bash
# 本番用に新しいキーを発行済みか確認
# Google Cloud Console > APIとサービス > 認証情報 で以下を確認:
#   - 開発中に使用したキーが無効化されている
#   - 本番用キーにAPI制限（Cloud Vision APIのみ）が設定されている
#   - 本番用キーにIPアドレス制限が設定されている

# .env に新しいキーが設定されていることを確認
python -c "from dotenv import load_dotenv; import os; load_dotenv(); k=os.getenv('VISION_API_KEY',''); print(f'キー末尾: ...{k[-4:]}' if len(k)>4 else '未設定')"
```

#### 2. Git履歴を含むシークレット再スキャン

```bash
# 全コミット履歴をスキャン（過去に .env や秘密情報がコミットされていないか）
pip install trufflehog
trufflehog git file://. --only-verified

# trufflehog が使えない場合の代替手段
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

# 検出された場合: git filter-repo で履歴から除去
# pip install git-filter-repo
# git filter-repo --path .env --invert-paths
```

#### 3. GitHubブランチ保護（CI必須）の有効化

1. リポジトリの **Settings** > **Branches** を開く
2. **Add branch protection rule** をクリック
3. **Branch name pattern** に `main` を入力
4. 以下を有効化:
   - **Require a pull request before merging**
   - **Require status checks to pass before merging**
     - 必須チェック: `test (3.11)`, `test (3.12)`, `test (3.13)`
   - **Require branches to be up to date before merging**
5. **Create** をクリック

#### デプロイ前チェックリスト

上記3点の完了後、以下も併せて確認してください。

- [ ] `VISION_API_KEY` の旧キー無効化 + 新キーにAPI制限・IP制限を設定済み
- [ ] Git履歴にシークレットが残っていない（trufflehog スキャン済み）
- [ ] GitHubブランチ保護ルールが有効（CI必須）
- [ ] `ADMIN_SECRET` が `secrets.token_urlsafe(32)` で生成した高エントロピー値
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

## トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| カメラ映像が表示されない | HTTPSでないとカメラAPIがブロックされる | `localhost` または HTTPS環境で実行する |
| 「APIキーが未設定です」と表示される | `.env` に `VISION_API_KEY` が未設定 | `.env.example` をコピーし、APIキーを設定してサーバー再起動 |
| 「リクエスト頻度が高すぎます」と表示される | 分間レート制限に到達 | 1分待つか、`RATE_LIMIT_PER_MINUTE` を環境変数で変更 |
| 「1日あたりのAPI上限に達しました」と表示される | 日次レート制限に到達 | 翌日0時にリセット、または `RATE_LIMIT_DAILY` を変更 |
| `/readyz` が 503 を返す | APIキー未設定 or Redis接続失敗 | `/readyz` のレスポンスボディで `checks` を確認 |
| スキャンボタンを押しても反応がない | JavaScriptのコンソールエラー | ブラウザDevTools → Console でエラーを確認 |
| 「Vision APIエラー (ステータス 403)」 | APIキーの制限またはCloud Vision API未有効化 | Google Cloud Console で APIキーの制限とAPI有効化状態を確認 |
| プロキシ環境で接続できない | `PROXY_URL` が未設定 | `.env` に `PROXY_URL=http://proxy:port` を設定してサーバー再起動 |
| 重複スキップが解除されない | localStorageの設定値が不正 | ブラウザDevTools → Console で下記コマンドを実行 |

### localStorageキーとリセット手順

フロントエンドはブラウザの `localStorage` に以下のキーでデータを保存します。

| キー名 | 内容 | 既定値 |
|--------|------|--------|
| `visionApiUsage` | 日次API使用量（`{date, count}`） | 日替わりで自動リセット |
| `duplicateSkipCount` | 重複スキップ回数設定（1〜5） | `2` |

**全設定を初期化する手順:**

ブラウザのDevTools（F12）→ Console で以下を実行してください。

```javascript
// 個別リセット
localStorage.removeItem('duplicateSkipCount');  // 重複スキップ設定
localStorage.removeItem('visionApiUsage');      // API使用量カウンター

// 全設定を一括リセット（Vision AI Scanner の全データ）
localStorage.clear();
```

リセット後、ページを再読込（F5）すると既定値に戻ります。

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
