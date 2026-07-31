from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.config import get_settings
from app.development_delay_middleware import DevelopmentDelayMiddleware


def invoke_middleware(delay_ms: int, method: str, path: str) -> tuple[AsyncMock, int]:
    downstream_calls = 0

    async def downstream(scope, receive, send) -> None:
        nonlocal downstream_calls
        downstream_calls += 1

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:
        return None

    scope = {
        "type": "http",
        "method": method,
        "path": path,
    }
    middleware = DevelopmentDelayMiddleware(downstream, delay_ms=delay_ms)
    sleep = AsyncMock()
    with patch("app.development_delay_middleware.asyncio.sleep", sleep):
        asyncio.run(middleware(scope, receive, send))
    return sleep, downstream_calls


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/people"),
        ("POST", "/api/auth/login"),
        ("PUT", "/api/events/1"),
        ("DELETE", "/api/media/1"),
    ],
)
def test_development_delay_waits_before_api_dispatch(method: str, path: str) -> None:
    sleep, downstream_calls = invoke_middleware(1_500, method, path)

    sleep.assert_awaited_once_with(1.5)
    assert downstream_calls == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/health"),
        ("OPTIONS", "/api/people"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
    ],
)
def test_development_delay_excludes_health_preflight_and_non_api_routes(
    method: str,
    path: str,
) -> None:
    sleep, downstream_calls = invoke_middleware(1_500, method, path)

    sleep.assert_not_awaited()
    assert downstream_calls == 1


def test_development_delay_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_PARCHINO_DEVELOPMENT_API_DELAY_MS", raising=False)
    assert get_settings().development_api_delay_ms == 0

    sleep, downstream_calls = invoke_middleware(0, "GET", "/api/people")
    sleep.assert_not_awaited()
    assert downstream_calls == 1


@pytest.mark.parametrize("value", ["-1", "60001", "1.5", "slow"])
def test_development_delay_rejects_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("WIKI_PARCHINO_DEVELOPMENT_API_DELAY_MS", value)

    with pytest.raises(ValueError, match="WIKI_PARCHINO_DEVELOPMENT_API_DELAY_MS"):
        get_settings()
