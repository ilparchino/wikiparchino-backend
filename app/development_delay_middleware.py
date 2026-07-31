from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Receive, Scope, Send


class DevelopmentDelayMiddleware:
    def __init__(self, app: ASGIApp, delay_ms: int = 0) -> None:
        self.app = app
        self.delay_seconds = delay_ms / 1000

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._should_delay(scope):
            await asyncio.sleep(self.delay_seconds)
        await self.app(scope, receive, send)

    def _should_delay(self, scope: Scope) -> bool:
        return (
            self.delay_seconds > 0
            and scope["type"] == "http"
            and scope["method"] != "OPTIONS"
            and scope["path"].startswith("/api/")
            and scope["path"] != "/api/health"
        )
