"""
rate_limiter のバックエンド選択のテスト。
"""

import logging
import types
from unittest.mock import patch

import rate_limiter


class TestRedisFallbackLog:
    """Redis 接続失敗時のログのテスト。"""

    def test_接続失敗のログでRedisの認証情報を伏せる(self, monkeypatch, caplog):
        url = "redis://user:s3cret-pass@redis.example.com:6379/0"  # pragma: allowlist secret  # pragma: allowlist secret
        monkeypatch.setattr(rate_limiter, "REDIS_URL", url)
        monkeypatch.setattr(rate_limiter, "_backend", None)
        # redis の例外メッセージに接続 URL がそのまま入る場合を再現する。
        # 本物の redis が入っていない環境でも走るよう、偽のモジュールを差し込む
        fake_redis = types.ModuleType("redis")

        def failing_from_url(*_args, **_kwargs):
            raise ConnectionError(f"Error connecting to {url}")

        fake_redis.from_url = failing_from_url  # type: ignore[attr-defined]

        with patch.dict("sys.modules", {"redis": fake_redis}), caplog.at_level(logging.WARNING):
            backend = rate_limiter._get_backend()

        assert isinstance(backend, rate_limiter.InMemoryRateLimiter)
        assert "s3cret-pass" not in caplog.text
        assert "redis://***@redis.example.com:6379/0" in caplog.text
