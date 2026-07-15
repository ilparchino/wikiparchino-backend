from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path
import socket
import subprocess
import time

import httpx
import pytest

from app import database
from app.database import Base, configure_database
from app.seed import seed_demo_data


@pytest.fixture()
def client(tmp_path: Path) -> Generator[httpx.Client, None, None]:
    db_path = tmp_path / "test.sqlite"
    database_url = f"sqlite:///{db_path}"
    os.environ["WIKI_PARCHINO_DATABASE_URL"] = database_url
    os.environ["WIKI_PARCHINO_MEDIA_DIR"] = str(tmp_path / "media")
    configure_database(database_url)
    Base.metadata.create_all(bind=database.engine)
    from app.database import SessionLocal

    with SessionLocal() as db:
        seed_demo_data(db)

    from app.api.auth import login_attempts

    login_attempts.clear()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    env = os.environ.copy()
    process = subprocess.Popen(
        [".venv/bin/uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as http_client:
            for _ in range(60):
                try:
                    if http_client.get("/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Uvicorn test server did not start")
            yield http_client
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture()
def auth_client(client: httpx.Client) -> httpx.Client:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
    return client
