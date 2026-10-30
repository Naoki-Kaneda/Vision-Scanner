# Vision処理 project overview
- Purpose: Flask-based Vision AI scanner that captures camera/video frames and calls Google Cloud Vision API for OCR and object detection.
- Tech stack: Python (Flask, requests, Pillow), vanilla JS/HTML/CSS frontend, pytest tests, optional Playwright E2E.
- Entry points: `python app.py` for local web server at `http://localhost:5001` (`APP_PORT` で変更可).
- Source of truth for commands and conventions: `CLAUDE.md` (このメモと食い違ったら CLAUDE.md が正しい).
- Core modules: `app.py` (routes, validation, headers), `vision_api.py` (Vision API client + proxy/ssl behavior), `rate_limiter.py` (Redis/in-memory rate limiter), `static/script.js` (camera/stability/UI/api calls), `static/scan_core.js` (状態遷移・画像ハッシュ・再試行などの判断の処理。script.js より先に読み込む), `templates/index.html` (UI), `tests/` (API/unit/E2E).
