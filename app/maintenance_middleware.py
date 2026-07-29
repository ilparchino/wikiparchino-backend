from __future__ import annotations

from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import database
from app.maintenance import MaintenanceState, maintenance_status
from app.security import utcnow


ALLOWED_DURING_MAINTENANCE = {
    "/api/health",
    "/api/maintenance/status",
}


class MaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if path in ALLOWED_DURING_MAINTENANCE:
            await self.app(scope, receive, send)
            return

        with database.SessionLocal() as db:
            current = maintenance_status(db, utcnow())

        blocks_login = (
            current.state == MaintenanceState.SCHEDULED
            and path == "/api/auth/login"
        )
        if current.state == MaintenanceState.ACTIVE or blocks_login:
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": (
                        "Il sistema è temporaneamente non disponibile per manutenzione."
                        if current.state == MaintenanceState.ACTIVE
                        else "Non è possibile accedere mentre è programmata la manutenzione."
                    ),
                    "code": "maintenance",
                    "maintenance": jsonable_encoder(current),
                },
                headers={
                    "Cache-Control": "no-store",
                    "Pragma": "no-cache",
                    "Retry-After": "30",
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
