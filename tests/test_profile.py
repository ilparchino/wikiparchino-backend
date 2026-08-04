from __future__ import annotations

from pathlib import Path

import httpx

from app.models import UserAccount
from app.security import hash_password


def login_token(client: httpx.Client, username: str = "admin", password: str = "admin") -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def person_payload(alias: str) -> dict:
    return {
        "alias": alias,
        "name": None,
        "surname": None,
        "sex": "unknown",
        "connotation": "unknown",
        "description": None,
        "rarity": 1.0,
    }


def test_profile_returns_the_ten_newest_live_activities(client: httpx.Client) -> None:
    admin_token = login_token(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    created = []
    for index in range(12):
        response = client.post(
            "/api/people",
            json=person_payload(f"Profilo {index}"),
            headers=admin_headers,
        )
        assert response.status_code == 201
        created.append(response.json())

    updated_payload = person_payload("Profilo aggiornato")
    updated = client.put(
        f"/api/people/{created[0]['id']}",
        json=updated_payload,
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert client.delete(
        f"/api/people/{created[-1]['id']}", headers=admin_headers
    ).status_code == 204

    from app.database import SessionLocal

    with SessionLocal() as db:
        db.add(
            UserAccount(
                username="secondo",
                display_name="Secondo utente",
                password_hash=hash_password("password-secondo"),
            )
        )
        db.commit()
    second_token = login_token(client, "secondo", "password-secondo")
    other = client.post(
        "/api/people",
        json=person_payload("Attività altrui"),
        headers={"Authorization": f"Bearer {second_token}"},
    )
    assert other.status_code == 201

    response = client.get("/api/profile", headers=admin_headers)
    assert response.status_code == 200
    profile = response.json()
    assert profile["user"]["username"] == "admin"
    assert profile["user"]["display_name"] == "Admin"
    assert profile["user"]["is_admin"] is True
    assert profile["user"]["is_owner"] is True
    assert len(profile["activity"]["items"]) == 10
    assert profile["activity"]["items"][0] == {
        "entity_type": "person",
        "entity_id": created[0]["id"],
        "title": "Profilo aggiornato",
        "action": "updated",
        "occurred_at": profile["activity"]["items"][0]["occurred_at"],
    }
    activity_ids = {item["entity_id"] for item in profile["activity"]["items"]}
    assert created[-1]["id"] not in activity_ids
    assert other.json()["id"] not in activity_ids


def test_relationship_and_media_changes_are_profile_updates(
    auth_client: httpx.Client,
    tmp_path: Path,
) -> None:
    event = auth_client.get("/api/events").json()["items"][0]
    person = auth_client.get("/api/people").json()["items"][0]
    replaced = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[{"person_id": person["id"], "role": "Guida", "motivation": None}],
    )
    assert replaced.status_code == 200
    activity = auth_client.get("/api/profile").json()["activity"]["items"]
    assert activity[0]["entity_id"] == event["id"]
    assert activity[0]["entity_type"] == "event"
    assert activity[0]["action"] == "updated"

    group = auth_client.get("/api/groups").json()["items"][0]
    replaced_group = auth_client.put(
        f"/api/groups/{group['id']}/people",
        json={"person_ids": [person["id"]]},
    )
    assert replaced_group.status_code == 200
    activity = auth_client.get("/api/profile").json()["activity"]["items"]
    assert activity[0]["entity_id"] == group["id"]
    assert activity[0]["entity_type"] == "group"
    assert activity[0]["action"] == "updated"

    image = tmp_path / "profile.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        upload = auth_client.post(
            "/api/media",
            data={"pullable_id": str(person["id"])},
            files={"file": ("profile.png", handle, "image/png")},
        )
    assert upload.status_code == 201
    activity = auth_client.get("/api/profile").json()["activity"]["items"]
    assert activity[0]["entity_id"] == person["id"]
    assert activity[0]["action"] == "updated"

    assert auth_client.delete(f"/api/media/{upload.json()['id']}").status_code == 204
    activity = auth_client.get("/api/profile").json()["activity"]["items"]
    assert activity[0]["entity_id"] == person["id"]
    assert activity[0]["action"] == "updated"


def test_password_change_preserves_current_session_and_revokes_others(
    client: httpx.Client,
) -> None:
    assert client.put(
        "/api/profile/password",
        json={"current_password": "admin", "new_password": "nuova-password-sicura"},
    ).status_code == 401
    current_token = login_token(client)
    other_token = login_token(client)
    current_headers = {"Authorization": f"Bearer {current_token}"}

    invalid = client.put(
        "/api/profile/password",
        json={"current_password": "admin", "new_password": "short"},
        headers=current_headers,
    )
    assert invalid.status_code == 422
    wrong = client.put(
        "/api/profile/password",
        json={
            "current_password": "incorrect",
            "new_password": "nuova-password-sicura",
        },
        headers=current_headers,
    )
    assert wrong.status_code == 400
    assert client.get("/api/auth/me", headers=current_headers).status_code == 200

    changed = client.put(
        "/api/profile/password",
        json={
            "current_password": "admin",
            "new_password": "nuova password café ☕",
        },
        headers=current_headers,
    )
    assert changed.status_code == 204
    assert client.get("/api/auth/me", headers=current_headers).status_code == 200
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "nuova password café ☕"},
    ).status_code == 200

    same = client.put(
        "/api/profile/password",
        json={
            "current_password": "nuova password café ☕",
            "new_password": "nuova password café ☕",
        },
        headers=current_headers,
    )
    assert same.status_code == 400


def test_media_previews_and_file_cache_policy(
    auth_client: httpx.Client,
    tmp_path: Path,
) -> None:
    people = auth_client.get("/api/people").json()["items"]
    first_person = people[0]
    second_person = people[1]
    uploaded = []
    for filename in ("first.png", "second.png"):
        image = tmp_path / filename
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + filename.encode())
        with image.open("rb") as handle:
            response = auth_client.post(
                "/api/media",
                data={"pullable_id": str(first_person["id"])},
                files={"file": (filename, handle, "image/png")},
            )
        assert response.status_code == 201
        uploaded.append(response.json())

    previews = auth_client.get(
        "/api/media/previews",
        params=[
            ("pullable_id", first_person["id"]),
            ("pullable_id", second_person["id"]),
            ("pullable_id", first_person["id"]),
        ],
    )
    assert previews.status_code == 200
    assert [item["id"] for item in previews.json()] == [uploaded[-1]["id"]]

    media = auth_client.get(f"/api/media/{uploaded[-1]['id']}?version=test")
    assert media.status_code == 200
    assert media.headers["cache-control"] == "private, no-store"
    assert media.headers["pragma"] == "no-cache"

    assert auth_client.get(
        "/api/media/previews", params={"pullable_id": 0}
    ).status_code == 422
    too_many = [("pullable_id", value) for value in range(1, 202)]
    assert auth_client.get("/api/media/previews", params=too_many).status_code == 422


def test_logged_operations_share_the_exact_operation_timestamp(
    auth_client: httpx.Client,
    tmp_path: Path,
) -> None:
    from app.database import SessionLocal
    from app.models import ActivityLog, Event, MediaAsset, Person, PersonEvent, PersonPlace, Place, Pullable

    created = auth_client.post(
        "/api/places",
        json={"name": "Luogo temporale", "description": None, "rarity": 1.0},
    )
    assert created.status_code == 201
    place_id = created.json()["id"]
    with SessionLocal() as db:
        pullable = db.get(Pullable, place_id)
        activity = (
            db.query(ActivityLog)
            .filter_by(entity_type="place", entity_id=place_id, action="create")
            .one()
        )
        assert pullable.created_at == pullable.updated_at == activity.occurred_at

    updated = auth_client.put(
        f"/api/places/{place_id}",
        json={"name": "Luogo temporale aggiornato", "description": None, "rarity": 1.0},
    )
    assert updated.status_code == 200
    with SessionLocal() as db:
        pullable = db.get(Pullable, place_id)
        activity = (
            db.query(ActivityLog)
            .filter_by(entity_type="place", entity_id=place_id, action="update")
            .one()
        )
        assert pullable.updated_at == activity.occurred_at

    event = auth_client.get("/api/events").json()["items"][0]
    people = auth_client.get("/api/people").json()["items"][:2]
    replaced = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[
            {"person_id": person["id"], "role": None, "motivation": None}
            for person in people
        ],
    )
    assert replaced.status_code == 200
    with SessionLocal() as db:
        pullable = db.get(Event, event["id"]).pullable
        activity = (
            db.query(ActivityLog)
            .filter_by(
                entity_type="event",
                entity_id=event["id"],
                action="replace_participants",
            )
            .order_by(ActivityLog.id.desc())
            .first()
        )
        links = db.query(PersonEvent).filter_by(event_id=event["id"]).all()
        assert links
        assert all(
            link.created_at == link.updated_at == activity.occurred_at
            for link in links
        )
        assert pullable.updated_at == activity.occurred_at

    linked = auth_client.put(
        f"/api/people/{people[0]['id']}/places",
        json=[{"place_id": place_id, "motivation": "Stesso istante"}],
    )
    assert linked.status_code == 200
    with SessionLocal() as db:
        pullable = db.get(Person, people[0]["id"]).pullable
        activity = (
            db.query(ActivityLog)
            .filter_by(
                entity_type="person",
                entity_id=people[0]["id"],
                action="replace_places",
            )
            .order_by(ActivityLog.id.desc())
            .first()
        )
        link = db.query(PersonPlace).filter_by(
            person_id=people[0]["id"], place_id=place_id
        ).one()
        assert link.created_at == link.updated_at == activity.occurred_at
        assert pullable.updated_at == activity.occurred_at

    image = tmp_path / "timestamp.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        uploaded = auth_client.post(
            "/api/media",
            data={"pullable_id": str(place_id)},
            files={"file": ("timestamp.png", handle, "image/png")},
        )
    assert uploaded.status_code == 201
    media_id = uploaded.json()["id"]
    with SessionLocal() as db:
        pullable = db.get(Place, place_id).pullable
        media = db.get(MediaAsset, media_id)
        activity = (
            db.query(ActivityLog)
            .filter_by(entity_type="place", entity_id=place_id, action="upload_media")
            .one()
        )
        assert media.created_at == pullable.updated_at == activity.occurred_at

    deleted = auth_client.delete(f"/api/media/{media_id}")
    assert deleted.status_code == 204
    with SessionLocal() as db:
        pullable = db.get(Place, place_id).pullable
        activity = (
            db.query(ActivityLog)
            .filter_by(entity_type="place", entity_id=place_id, action="delete_media")
            .one()
        )
        assert db.get(MediaAsset, media_id) is None
        assert pullable.updated_at == activity.occurred_at
