from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    auth,
    entities,
    maintenance,
    media,
    profile,
    pullables,
    pulls,
    relationships,
    search,
)
from app.config import get_settings
from app.development_delay_middleware import DevelopmentDelayMiddleware
from app.maintenance_middleware import MaintenanceMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Wiki Parchino API",
        version="0.1.0",
        root_path=settings.root_path,
    )
    app.add_middleware(MaintenanceMiddleware)
    app.add_middleware(
        DevelopmentDelayMiddleware,
        delay_ms=settings.development_api_delay_ms,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(maintenance.router, prefix="/api")
    # Static collection search routes must precede routes such as /people/{id}.
    app.include_router(search.router, prefix="/api")
    app.include_router(pullables.router, prefix="/api")
    app.include_router(entities.router, prefix="/api")
    app.include_router(relationships.router, prefix="/api")
    app.include_router(media.router, prefix="/api")
    app.include_router(profile.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(pulls.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
