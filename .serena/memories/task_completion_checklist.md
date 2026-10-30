# Task completion checklist
- Run `pytest tests/ --ignore=tests/e2e`, and `npm run check` / `npm run lint` / `npm test` when `static/` changed.
- Confirm local app behavior manually (`python app.py` then verify major flows in browser).
- Ensure security-sensitive env vars are not hardcoded or committed.
- Keep changes atomic and aligned to Conventional Commits (`feat`, `fix`, `test`, `refactor`, `docs`, `chore`).
