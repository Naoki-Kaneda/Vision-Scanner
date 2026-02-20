# Repository Guidelines

## Project Structure & Module Organization
- `app.py`: Flask entry point and API route (`/api/analyze`).
- `vision_api.py`: Google Cloud Vision API client, image preprocessing, and response parsing.
- `translations.py`: English-to-Japanese label dictionary for object detection output.
- `templates/index.html`: Main UI template.
- `static/script.js` and `static/style.css`: Frontend behavior and styles.
- `requirements.txt`: Python dependencies.
- `venv/` and `__pycache__/` are local artifacts; do not include them in commits.

## Build, Test, and Development Commands
- `python -m venv venv`: Create virtual environment.
- `venv\Scripts\Activate.ps1`: Activate venv in PowerShell.
- `pip install -r requirements.txt`: Install dependencies.
- `python app.py`: Start local server at `http://localhost:5000`.
- `flask run --debug --port 5000`: Alternative debug run (after setting `FLASK_APP=app.py`).

## Coding Style & Naming Conventions
- Python: PEP 8, 4-space indentation, `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for constants.
- JavaScript: keep constants in `UPPER_SNAKE_CASE`, functions in `camelCase`, and prefer small single-purpose functions.
- Keep route handlers thin in `app.py`; move API and parsing logic into `vision_api.py`.
- Use clear Japanese or English comments only where intent is not obvious.

## Testing Guidelines
- No automated test suite is currently present. Add tests under `tests/` using `pytest`.
- Test files: `test_<module>.py`; test names: `test_<behavior>()`.
- Minimum baseline before PR: run the app locally and verify
  1) camera/file input works, 2) text mode returns OCR lines, 3) object mode returns labels/translations, 4) API error handling returns JSON errors.

## Commit & Pull Request Guidelines
- Git history is not available in this workspace, so use this standard:
  - Commit format: `type(scope): summary` (for example, `fix(api): handle missing image payload`).
  - Keep commits focused and atomic.
- PRs should include:
  - Purpose and user-visible impact.
  - Linked issue/task ID.
  - Screenshots or short video for UI changes (`templates/`, `static/`).
  - Manual verification steps and environment notes (`VISION_API_KEY`, proxy usage).

## Security & Configuration Tips
- Store secrets in `.env` (`VISION_API_KEY`, optional `PROXY_URL`); never hardcode or commit secrets.
- Keep TLS verification enabled unless a controlled corporate proxy requires otherwise.
