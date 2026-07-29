from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    frontend_origins: tuple[str, ...]
    frontend_url: str
    session_days: int
    media_dir: Path
    root_path: str
    telegram_bot_token: str | None = field(repr=False)
    telegram_chat_id: str | None


def env_path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser().resolve()


def env_origins(name: str, default: str) -> tuple[str, ...]:
    origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv(name, default).split(",")
        if origin.strip()
    )
    if not origins:
        raise ValueError(f"{name} must contain at least one origin")
    return origins


def env_root_path(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value == "/":
        return ""
    if not value.startswith("/") or "://" in value or "?" in value or "#" in value:
        raise ValueError(f"{name} must be an absolute URL path such as /wikiparchino")
    return value.rstrip("/")


def env_optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def get_settings() -> Settings:
    frontend_origins = env_origins(
        "WIKI_PARCHINO_FRONTEND_ORIGINS", "http://127.0.0.1:5173"
    )
    return Settings(
        database_url=os.getenv(
            "WIKI_PARCHINO_DATABASE_URL",
            f"sqlite:///{BACKEND_DIR / 'wiki_parchino.db'}",
        ),
        frontend_origins=frontend_origins,
        frontend_url=os.getenv(
            "WIKI_PARCHINO_FRONTEND_URL", frontend_origins[0]
        ).strip().rstrip("/"),
        session_days=int(os.getenv("WIKI_PARCHINO_SESSION_DAYS", "14")),
        media_dir=env_path("WIKI_PARCHINO_MEDIA_DIR", BACKEND_DIR / "media"),
        root_path=env_root_path("WIKI_PARCHINO_ROOT_PATH"),
        telegram_bot_token=env_optional("WIKI_PARCHINO_TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=env_optional("WIKI_PARCHINO_TELEGRAM_CHAT_ID"),
    )
