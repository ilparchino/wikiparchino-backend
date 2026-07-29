from __future__ import annotations

from datetime import timedelta

import httpx

from app import database
from app.maintenance import maintenance_status
from app.manage_maintenance import end_maintenance, schedule_maintenance
from app.models import MaintenanceWindow, UserSession
from app.security import utcnow


def login(client: httpx.Client) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_scheduled_maintenance_blocks_login_but_keeps_existing_api_available(
    client: httpx.Client,
) -> None:
    token = login(client)
    now = utcnow()
    with database.SessionLocal() as db:
        window = schedule_maintenance(
            db,
            minutes=15,
            message="Aggiornamento programmato",
            now=now,
        )

    status = client.get("/api/maintenance/status")
    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json() == {
        "state": "scheduled",
        "server_time": status.json()["server_time"],
        "announced_at": now.isoformat().replace("+00:00", "Z"),
        "starts_at": window.starts_at.isoformat().replace("+00:00", "Z"),
        "message": "Aggiornamento programmato",
        "login_allowed": False,
        "api_available": True,
    }

    blocked = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert blocked.status_code == 503
    assert blocked.json()["code"] == "maintenance"
    assert blocked.json()["maintenance"]["state"] == "scheduled"
    assert blocked.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert blocked.headers["retry-after"] == "30"
    assert client.get("/api/me", headers=bearer(token)).status_code == 200


def test_active_maintenance_revokes_sessions_once_and_blocks_all_but_status_health_and_options(
    client: httpx.Client,
) -> None:
    first = login(client)
    second = login(client)
    now = utcnow()
    with database.SessionLocal() as db:
        db.add(
            MaintenanceWindow(
                open_slot=1,
                announced_at=now - timedelta(minutes=10),
                starts_at=now - timedelta(minutes=1),
                message=None,
            )
        )
        db.commit()
        assert db.query(UserSession).count() == 2

    for method, path in [
        ("GET", "/api/people"),
        ("GET", "/api/admin/summary"),
        ("POST", "/api/auth/logout"),
        ("GET", "/docs"),
        ("GET", "/openapi.json"),
    ]:
        response = client.request(method, path, headers=bearer(first))
        assert response.status_code == 503
        assert response.json()["maintenance"]["state"] == "active"

    assert client.get("/api/health").status_code == 200
    status = client.get("/api/maintenance/status")
    assert status.status_code == 200
    assert status.json()["state"] == "active"
    preflight = client.options(
        "/api/people",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    with database.SessionLocal() as db:
        window = db.query(MaintenanceWindow).one()
        assert window.sessions_revoked_at is not None
        assert window.sessions_revoked_count == 2
        assert db.query(UserSession).count() == 0
        first_revocation = window.sessions_revoked_at
        repeated = maintenance_status(db, utcnow())
        db.refresh(window)
        assert repeated.state == "active"
        assert window.sessions_revoked_at == first_revocation
        assert window.sessions_revoked_count == 2

        ended, cancelled = end_maintenance(db, utcnow())
        assert cancelled is False
        assert ended.open_slot is None

    assert client.get("/api/people", headers=bearer(second)).status_code == 401
    assert login(client)


def test_pending_maintenance_can_be_cancelled_without_revoking_sessions(
    client: httpx.Client,
) -> None:
    token = login(client)
    now = utcnow()
    with database.SessionLocal() as db:
        schedule_maintenance(db, 30, None, now)
        window, cancelled = end_maintenance(db, now + timedelta(minutes=1))
        assert cancelled is True
        assert window.sessions_revoked_at is None
        assert window.sessions_revoked_count is None
        assert window.open_slot is None

    assert client.get("/api/me", headers=bearer(token)).status_code == 200
    assert client.get("/api/maintenance/status").json()["state"] == "available"
