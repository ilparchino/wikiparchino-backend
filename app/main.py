from __future__ import annotations

from fastapi import FastAPI
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, entities, media, profile, pulls, relationships, search
from app.api.deps import current_user
from app.config import get_settings
from app.models import UserAccount
from app.schemas import UserOut


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Wiki Parchino API",
        version="0.1.0",
        root_path=settings.root_path,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth.router, prefix="/api")
    app.include_router(entities.router, prefix="/api")
    app.include_router(relationships.router, prefix="/api")
    app.include_router(media.router, prefix="/api")
    app.include_router(profile.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(pulls.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/me", response_model=UserOut)
    def me(user: UserAccount = Depends(current_user)) -> UserAccount:
        return user

    return app


app = create_app()
