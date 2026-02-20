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

## 既知の制限

- **API上限**: クライアント側 100回/日、サーバー側 20回/分・100回/日（IP単位）
- **対応ブラウザ**: Chrome, Edge, Firefox（カメラアクセスにHTTPSまたはlocalhost必須）
- **言語ヒント**: 英語（`en`）に最適化。日本語テキストの認識精度は限定的
- **PCカメラ**: インカメラのみの場合、文字をカメラに向けて映す必要あり

## 技術スタック

- **バックエンド**: Python / Flask
- **フロントエンド**: HTML / CSS / JavaScript（バニラ）
- **API**: Google Cloud Vision API
- **テスト**: pytest
