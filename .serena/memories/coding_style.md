# Coding style and conventions
- Python: PEP 8, 4-space indent, snake_case for vars/functions, UPPER_SNAKE_CASE for constants.
- JS: camelCase for functions, UPPER_SNAKE_CASE for constants, small single-responsibility functions.
- Comments: Japanese comments only when intent is not obvious.
- Architectural rule: keep Flask route handlers thin in `app.py`; place API/analysis logic in `vision_api.py`.
- Security conventions: env vars for secrets (`VISION_API_KEY`, `PROXY_URL`), base64 validation, image size limit, mode whitelist.
