# Repository Guidelines

## Project Structure & Module Organization
- `app.py`: Flaskエントリーポイント。APIルート（`/api/analyze`）、入力バリデーション、サーバー側レート制限。
- `vision_api.py`: Google Cloud Vision APIクライアント。画像前処理、レスポンス解析。
- `translations.py`: 物体検出ラベルの英日翻訳辞書。
- `templates/index.html`: メインUIテンプレート。
- `static/script.js`: フロントエンドロジック（カメラ制御、安定化検出、API通信）。
- `static/style.css`: スタイルシート（レスポンシブ対応）。
- `tests/test_api.py`: APIエンドポイントのテスト（pytest）。
- `requirements.txt`: Python依存ライブラリ。
- `.env.example`: 環境変数の設定例。
- `venv/` と `__pycache__/` はローカル成果物であり、コミットに含めないこと。

## Build, Test, and Development Commands
- `python -m venv venv`: 仮想環境の作成。
- `venv\Scripts\Activate.ps1`: PowerShellでvenvを有効化。
- `pip install -r requirements.txt`: 依存ライブラリのインストール。
- `python app.py`: ローカルサーバーを `http://localhost:5000` で起動。
- `pytest tests/ -v`: テストスイートの実行。

## Coding Style & Naming Conventions
- Python: PEP 8、4スペースインデント、`snake_case`（関数/変数）、`UPPER_SNAKE_CASE`（定数）。
- JavaScript: 定数は`UPPER_SNAKE_CASE`、関数は`camelCase`、小さな単一責務関数を推奨。
- `app.py`のルートハンドラは薄く保ち、API・解析ロジックは`vision_api.py`に配置。
- コメントは日本語で、意図が明らかでない箇所にのみ記述。

## Testing Guidelines
- テストは `tests/` ディレクトリに `pytest` を使用。
- ファイル名: `test_<module>.py`、テスト名: `test_<動作>()` （日本語テスト名可）。
- 4系統のカバレッジ: 正常OCR / 正常物体検出 / 不正入力 / API障害時。
- PR前の最低基準: テスト全通過 + ローカル動作確認。

## Commit & Pull Request Guidelines
- **Conventional Commits** 形式を採用:
  - `feat:` 新機能（例: `feat: 物体検出モードの追加`）
  - `fix:` バグ修正（例: `fix: ミラー反転時のOCR誤認識を修正`）
  - `test:` テスト追加・修正（例: `test: 入力バリデーションのテスト追加`）
  - `refactor:` リファクタリング（例: `refactor: 翻訳辞書をモジュール分離`）
  - `docs:` ドキュメント変更（例: `docs: README.mdの追加`）
  - `chore:` その他（例: `chore: .gitignoreの更新`）
- コミットは原子的で、単一の変更に焦点を当てる。

## Security & Configuration
- 秘密情報は `.env` に格納（`VISION_API_KEY`, `PROXY_URL`）。ハードコードやコミットは厳禁。
- TLS検証はデフォルト有効。企業プロキシ環境でのみ `VERIFY_SSL=false` を設定。
- Flaskデバッグモードはデフォルト無効。開発時のみ `FLASK_DEBUG=true` を設定。
- APIリクエストにはBase64検証、サイズ制限（5MB）、モード列挙チェックを適用。
