from __future__ import annotations

from datetime import timedelta

import httpx

from app.models import SecurityEventLog, SecurityEventType, UserAccount
from app.security import utcnow, verify_password


def login(client: httpx.Client, username: str = "admin", password: str = "admin") -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_user(
    client: httpx.Client,
    token: str,
    username: str = "utente",
    *,
    is_admin: bool = False,
) -> dict:
    response = client.post(
        "/api/admin/users",
        headers=headers(token),
        json={
            "username": username,
            "display_name": "Utente Gestito",
            "password": "password-sicura",
            "is_admin": is_admin,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_endpoints_require_an_administrator(client: httpx.Client) -> None:
    admin_token = login(client)
    managed = create_user(client, admin_token, "regolare")
    regular_token = login(client, "regolare", "password-sicura")
    account_update = {
        "display_name": managed["display_name"],
        "is_admin": False,
        "is_active": True,
    }
    requests = [
        ("GET", "/api/admin/summary", None),
        ("GET", "/api/admin/users", None),
        ("GET", f"/api/admin/users/{managed['id']}", None),
        ("GET", "/api/admin/activity", None),
        (
            "POST",
            "/api/admin/users",
            {
                "username": "vietato",
                "display_name": "Vietato",
                "password": "password-sicura",
                "is_admin": False,
            },
        ),
        ("PUT", f"/api/admin/users/{managed['id']}", account_update),
        (
            "PUT",
            f"/api/admin/users/{managed['id']}/password",
            {"new_password": "password-alternativa"},
        ),
        ("POST", f"/api/admin/users/{managed['id']}/sessions/revoke", None),
    ]
    for method, path, payload in requests:
        unauthenticated = client.request(method, path, json=payload)
        assert unauthenticated.status_code == 401, (path, unauthenticated.text)
        response = client.request(method, path, headers=headers(regular_token), json=payload)
        assert response.status_code == 403, (path, response.text)


def test_user_creation_normalization_and_duplicate_validation(client: httpx.Client) -> None:
    admin_token = login(client)
    created = create_user(client, admin_token, "  Nuovo  ")
    assert created["username"] == "nuovo"
    assert created["is_active"] is True
    assert created["is_owner"] is False
    duplicate = client.post(
        "/api/admin/users",
        headers=headers(admin_token),
        json={
            "username": "NUOVO",
            "display_name": "Duplicato",
            "password": "password-sicura",
            "is_admin": False,
        },
    )
    assert duplicate.status_code == 409

    from app.database import SessionLocal

    with SessionLocal() as db:
        stored = db.get(UserAccount, created["id"])
        event = (
            db.query(SecurityEventLog)
            .filter_by(target_user_id=created["id"], event_type=SecurityEventType.USER_CREATED.value)
            .one()
        )
        assert verify_password("password-sicura", stored.password_hash)
        assert stored.created_at == stored.updated_at == event.occurred_at
        assert event.source_ip == "127.0.0.1"

    activity = client.get(
        "/api/admin/activity",
        headers=headers(admin_token),
        params={"source": "account", "action": "user_created"},
    ).json()
    assert activity["items"][0]["source_ip"] == "127.0.0.1"


def test_deactivation_preserves_account_and_revokes_sessions(client: httpx.Client) -> None:
    admin_token = login(client)
    managed = create_user(client, admin_token, "disattiva")
    first = login(client, "disattiva", "password-sicura")
    second = login(client, "disattiva", "password-sicura")
    detail = client.get(f"/api/admin/users/{managed['id']}", headers=headers(admin_token)).json()
    assert detail["user"]["active_session_count"] == 2

    deactivated = client.put(
        f"/api/admin/users/{managed['id']}",
        headers=headers(admin_token),
        json={"display_name": "Nome aggiornato", "is_admin": False, "is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert client.get("/api/me", headers=headers(first)).status_code == 401
    assert client.get("/api/me", headers=headers(second)).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "disattiva", "password": "password-sicura"}
    ).status_code == 401

    reactivated = client.put(
        f"/api/admin/users/{managed['id']}",
        headers=headers(admin_token),
        json={"display_name": "Nome aggiornato", "is_admin": False, "is_active": True},
    )
    assert reactivated.status_code == 200
    assert login(client, "disattiva", "password-sicura")

    from app.database import SessionLocal

    with SessionLocal() as db:
        stored = db.get(UserAccount, managed["id"])
        assert stored is not None
        event = (
            db.query(SecurityEventLog)
            .filter_by(target_user_id=managed["id"], event_type=SecurityEventType.USER_ACTIVATED.value)
            .one()
        )
        assert stored.updated_at == event.occurred_at


def test_self_safety_password_reset_and_session_revocation(client: httpx.Client) -> None:
    admin_token = login(client)
    admin = client.get("/api/me", headers=headers(admin_token)).json()
    for payload in (
        {"display_name": admin["display_name"], "is_admin": False, "is_active": True},
        {"display_name": admin["display_name"], "is_admin": True, "is_active": False},
    ):
        response = client.put(f"/api/admin/users/{admin['id']}", headers=headers(admin_token), json=payload)
        assert response.status_code == 409

    assert client.put(
        f"/api/admin/users/{admin['id']}/password",
        headers=headers(admin_token),
        json={"new_password": "password-amministratore"},
    ).status_code == 409

    target = create_user(client, admin_token, "reset")
    old_token = login(client, "reset", "password-sicura")
    detail_before = client.get(
        f"/api/admin/users/{target['id']}",
        headers=headers(admin_token),
    ).json()
    reset_events_before = sum(
        item["action"] == "password_reset"
        for item in detail_before["account_activity"]
    )
    reused = client.put(
        f"/api/admin/users/{target['id']}/password",
        headers=headers(admin_token),
        json={"new_password": "password-sicura"},
    )
    assert reused.status_code == 400
    assert client.get("/api/me", headers=headers(old_token)).status_code == 200
    detail_after = client.get(
        f"/api/admin/users/{target['id']}",
        headers=headers(admin_token),
    ).json()
    assert sum(
        item["action"] == "password_reset"
        for item in detail_after["account_activity"]
    ) == reset_events_before

    invalid = client.put(
        f"/api/admin/users/{target['id']}/password",
        headers=headers(admin_token),
        json={"new_password": " password-sicura"},
    )
    assert invalid.status_code == 422
    assert client.get("/api/me", headers=headers(old_token)).status_code == 200

    assert client.put(
        f"/api/admin/users/{target['id']}/password",
        headers=headers(admin_token),
        json={"new_password": "password nuova café ☕"},
    ).status_code == 204
    assert client.get("/api/me", headers=headers(old_token)).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"username": "reset", "password": "password nuova café ☕ "},
    ).status_code == 401
    new_token = login(client, "reset", "password nuova café ☕")

    revoked = client.post(
        f"/api/admin/users/{target['id']}/sessions/revoke",
        headers=headers(admin_token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_count"] == 1
    assert client.get("/api/me", headers=headers(new_token)).status_code == 401

    current = client.post(
        f"/api/admin/users/{admin['id']}/sessions/revoke",
        headers=headers(admin_token),
    )
    assert current.status_code == 200
    assert client.get("/api/me", headers=headers(admin_token)).status_code == 200


def test_owner_is_protected_from_other_administrators(client: httpx.Client) -> None:
    owner_token = login(client)
    owner = client.get("/api/me", headers=headers(owner_token)).json()
    assert owner["is_owner"] is True

    other_admin = create_user(client, owner_token, "altro-admin", is_admin=True)
    other_token = login(client, "altro-admin", "password-sicura")
    owner_detail = client.get(
        f"/api/admin/users/{owner['id']}",
        headers=headers(other_token),
    )
    assert owner_detail.status_code == 200
    assert owner_detail.json()["user"]["is_owner"] is True

    protected_requests = [
        (
            "PUT",
            f"/api/admin/users/{owner['id']}",
            {
                "display_name": "Nome compromesso",
                "is_admin": True,
                "is_active": True,
            },
        ),
        (
            "PUT",
            f"/api/admin/users/{owner['id']}/password",
            {"new_password": "password-proprietario-nuova"},
        ),
        (
            "POST",
            f"/api/admin/users/{owner['id']}/sessions/revoke",
            None,
        ),
    ]
    for method, path, payload in protected_requests:
        response = client.request(method, path, headers=headers(other_token), json=payload)
        assert response.status_code == 403, (path, response.text)
        assert client.get("/api/me", headers=headers(other_token)).status_code == 200

    unchanged = client.get(
        f"/api/admin/users/{owner['id']}",
        headers=headers(owner_token),
    ).json()["user"]
    assert unchanged["display_name"] == owner["display_name"]
    assert unchanged["is_owner"] is True
    assert unchanged["is_admin"] is True
    assert unchanged["is_active"] is True

    owner_update = client.put(
        f"/api/admin/users/{other_admin['id']}",
        headers=headers(owner_token),
        json={
            "display_name": "Admin aggiornato dal Proprietario",
            "is_admin": True,
            "is_active": True,
        },
    )
    assert owner_update.status_code == 200
    assert owner_update.json()["display_name"] == "Admin aggiornato dal Proprietario"


def test_activity_summary_filters_and_deleted_content_title(client: httpx.Client) -> None:
    admin_token = login(client)
    managed = create_user(client, admin_token, "attivita")
    user_token = login(client, "attivita", "password-sicura")
    person = client.post(
        "/api/people",
        headers=headers(user_token),
        json={
            "alias": "Elemento cancellato",
            "name": None,
            "surname": None,
            "sex": "unknown",
            "connotation": "unknown",
            "description": None,
            "rarity": 1.0,
        },
    ).json()
    assert client.delete(f"/api/people/{person['id']}", headers=headers(user_token)).status_code == 204

    content = client.get(
        "/api/admin/activity",
        headers=headers(admin_token),
        params={
            "source": "content",
            "actor_user_id": managed["id"],
            "action": "delete",
            "page_size": 1,
        },
    )
    assert content.status_code == 200, content.text
    assert content.json()["total"] == 1
    assert content.json()["items"][0]["title"] == "Elemento cancellato"
    assert content.json()["items"][0]["linkable"] is False

    authentication = client.get(
        "/api/admin/activity",
        headers=headers(admin_token),
        params={"source": "authentication", "action": "login_succeeded"},
    )
    assert authentication.status_code == 200
    assert authentication.json()["total"] >= 2

    summary = client.get("/api/admin/summary", headers=headers(admin_token)).json()
    assert summary["total_users"] == 2
    assert summary["activity_last_24h"] > 0

    detail = client.get(f"/api/admin/users/{managed['id']}", headers=headers(admin_token)).json()
    assert any(item["action"] == "delete" for item in detail["content_activity"])
    assert any(item["action"] == "login_succeeded" for item in detail["account_activity"])


def test_authentication_retention_and_rate_limit_deduplication(client: httpx.Client) -> None:
    from app.database import SessionLocal

    with SessionLocal() as db:
        db.add(
            SecurityEventLog(
                event_type=SecurityEventType.LOGIN_FAILED.value,
                attempted_username="old",
                source_ip="127.0.0.1",
                occurred_at=utcnow() - timedelta(days=91),
            )
        )
        db.commit()

    for _ in range(5):
        assert client.post(
            "/api/auth/login", json={"username": "missing", "password": "incorrect"}
        ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "missing", "password": "incorrect"}
    ).status_code == 429
    assert client.post(
        "/api/auth/login", json={"username": "missing", "password": "incorrect"}
    ).status_code == 429

    with SessionLocal() as db:
        assert db.query(SecurityEventLog).filter_by(attempted_username="old").count() == 0
        assert (
            db.query(SecurityEventLog)
            .filter_by(event_type=SecurityEventType.LOGIN_RATE_LIMITED.value, attempted_username="missing")
            .count()
            == 1
        )
