"""
テスト共通フィクスチャ。
pytestフィクスチャのみを定義する。ヘルパー関数は tests/helpers.py を参照。
"""

import pytest

from app import app
from rate_limiter import reset_for_testing


# ─── 共有フィクスチャ ──────────────────────────────
@pytest.fixture
def client():
    """Flaskテストクライアントを作成する。テスト間でレート制限ステートをリセット。"""
    reset_for_testing()

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
