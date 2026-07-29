from __future__ import annotations

import asyncio

from fastapi import FastAPI
import httpx
import pytest

from app import database
from app.config import env_root_path, get_settings
from app.database import Base
from app.main import create_app


def app_get(app: FastAPI, path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, root_path=app.root_path)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


@pytest.fixture(autouse=True)
def isolated_database(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'root-path.sqlite'}"
    monkeypatch.setenv("WIKI_PARCHINO_DATABASE_URL", database_url)
    database.configure_database(database_url)
    Base.metadata.create_all(bind=database.engine)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, ""),
        ("", ""),
        ("/", ""),
        (" /wikiparchino/ ", "/wikiparchino"),
        ("/nested/prefix", "/nested/prefix"),
    ],
)
def test_root_path_normalization(
    configured: str | None,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if configured is None:
        monkeypatch.delenv("WIKI_PARCHINO_ROOT_PATH", raising=False)
    else:
        monkeypatch.setenv("WIKI_PARCHINO_ROOT_PATH", configured)
    assert env_root_path("WIKI_PARCHINO_ROOT_PATH") == expected
    assert get_settings().root_path == expected


@pytest.mark.parametrize(
    "configured",
    ["wikiparchino", "https://example.test/wikiparchino", "/prefix?query=1", "/prefix#fragment"],
)
def test_root_path_rejects_values_that_are_not_absolute_url_paths(
    configured: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WIKI_PARCHINO_ROOT_PATH", configured)
    with pytest.raises(ValueError, match="absolute URL path"):
        get_settings()


def test_swagger_uses_the_configured_public_root_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WIKI_PARCHINO_ROOT_PATH", "/wikiparchino/")
    app = create_app()

    docs = app_get(app, "/docs")
    schema = app_get(app, "/openapi.json")

    assert docs.status_code == 200
    assert "url: '/wikiparchino/openapi.json'" in docs.text
    assert "window.location.origin + '/wikiparchino/docs/oauth2-redirect'" in docs.text
    assert schema.status_code == 200
    assert app.root_path == "/wikiparchino"


def test_swagger_keeps_direct_local_urls_without_a_root_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WIKI_PARCHINO_ROOT_PATH", raising=False)
    app = create_app()

    docs = app_get(app, "/docs")

    assert docs.status_code == 200
    assert "url: '/openapi.json'" in docs.text
    assert "window.location.origin + '/docs/oauth2-redirect'" in docs.text
