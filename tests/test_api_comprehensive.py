from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import httpx

from app.models import UserAccount, UserSession
from app.security import hash_session_token, utcnow


def assert_status(response, expected: int) -> None:
    assert response.status_code == expected, response.text


def login(client: httpx.Client) -> dict[str, Any]:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert_status(response, 200)
    payload = response.json()
    client.headers["Authorization"] = f"Bearer {payload['access_token']}"
    return payload["user"]


def first(items: Iterable[dict[str, Any]], label: str) -> dict[str, Any]:
    values = list(items)
    assert values, f"Expected at least one {label}"
    return values[0]


def test_cors_bearer_login_and_session_reuse(client: httpx.Client) -> None:
    origin = "http://127.0.0.1:5173"
    preflight = client.options(
        "/api/me",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert_status(preflight, 200)
    assert preflight.headers["access-control-allow-origin"] == origin
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in preflight.headers

    unauthenticated = client.get("/api/me")
    assert_status(unauthenticated, 401)
    assert unauthenticated.headers["www-authenticate"] == "Bearer"
    login_response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
        headers={"Origin": origin},
    )
    assert_status(login_response, 200)
    payload = login_response.json()
    assert login_response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in login_response.headers
    assert "set-cookie" not in login_response.headers
    assert login_response.headers["cache-control"] == "no-store"
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["expires_at"]
    assert payload["user"]["username"] == "admin"

    client.headers["Authorization"] = f"Bearer {payload['access_token']}"

    me = client.get("/api/me")
    assert_status(me, 200)
    assert me.json()["username"] == "admin"

    logout = client.post("/api/auth/logout")
    assert_status(logout, 204)
    revoked = client.get("/api/me")
    assert_status(revoked, 401)
    assert revoked.headers["www-authenticate"] == "Bearer"


def test_bearer_validation_expiry_and_inactive_accounts(client: httpx.Client) -> None:
    for authorization in ["Basic abc", "Bearer", "Bearer invalid-token"]:
        response = client.get("/api/me", headers={"Authorization": authorization})
        assert_status(response, 401)
        assert response.headers["www-authenticate"] == "Bearer"

    login_response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    token = login_response.json()["access_token"]

    from app.database import SessionLocal

    with SessionLocal() as db:
        session = (
            db.query(UserSession)
            .filter(UserSession.token_hash == hash_session_token(token))
            .one()
        )
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    expired = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert_status(expired, 401)
    assert expired.json()["detail"] == "Session expired"

    active_login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).json()
    with SessionLocal() as db:
        user = db.query(UserAccount).filter(UserAccount.username == "admin").one()
        user.is_active = False
        db.commit()

    inactive = client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {active_login['access_token']}"},
    )
    assert_status(inactive, 401)
    assert inactive.json()["detail"] == "Inactive account"


def test_logout_revokes_only_the_presented_session(client: httpx.Client) -> None:
    first_token = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).json()["access_token"]
    second_token = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    ).json()["access_token"]

    assert_status(
        client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {first_token}"},
        ),
        204,
    )
    assert_status(
        client.get("/api/me", headers={"Authorization": f"Bearer {first_token}"}),
        401,
    )
    assert_status(
        client.get("/api/me", headers={"Authorization": f"Bearer {second_token}"}),
        200,
    )


def test_login_throttling(client: httpx.Client) -> None:
    for _ in range(5):
        assert_status(
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong"},
            ),
            401,
        )
    assert_status(
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        ),
        429,
    )


def test_protected_api_routes_reject_unauthenticated_requests(client: httpx.Client) -> None:
    protected_gets = [
        "/api/me",
        "/api/auth/me",
        "/api/people",
        "/api/people/1",
        "/api/places",
        "/api/places/3",
        "/api/epochs",
        "/api/epochs/5",
        "/api/events",
        "/api/events/6",
        "/api/events/6/participants",
        "/api/people/1/events",
        "/api/people/1/places",
        "/api/places/3/people",
        "/api/places/3/events",
        "/api/epochs/5/events",
        "/api/search?q=parchino",
        "/api/pulls/random",
        "/api/pulls/daily?day=2026-07-11",
        "/api/media",
        "/api/media/1",
    ]
    for path in protected_gets:
        assert_status(client.get(path), 401)

    assert_status(client.post("/api/auth/logout"), 401)
    assert_status(client.post("/api/people", json={"alias": "No auth", "rarity": 1.0}), 401)
    assert_status(client.put("/api/people/1/places", json=[]), 401)


def test_comprehensive_authenticated_api_scenario(client: httpx.Client) -> None:
    user = login(client)
    assert user["display_name"] == "Admin"

    people = client.get("/api/people")
    places = client.get("/api/places")
    epochs = client.get("/api/epochs")
    events = client.get("/api/events")
    for response in [people, places, epochs, events]:
        assert_status(response, 200)

    seeded_person = first(people.json(), "person")
    seeded_place = first(places.json(), "place")
    seeded_epoch = first(epochs.json(), "epoch")
    seeded_event = first(events.json(), "event")

    assert_status(client.get(f"/api/people/{seeded_person['id']}"), 200)
    assert_status(client.get(f"/api/places/{seeded_place['id']}"), 200)
    assert_status(client.get(f"/api/epochs/{seeded_epoch['id']}"), 200)
    event_detail = client.get(f"/api/events/{seeded_event['id']}")
    assert_status(event_detail, 200)
    assert event_detail.json()["place"]["id"] == seeded_event["place_id"]
    assert event_detail.json()["epoch"]["id"] == seeded_event["epoch_id"]

    search = client.get("/api/search", params={"q": seeded_event["title"]})
    assert_status(search, 200)
    assert any(item["entity_type"] == "event" and item["id"] == seeded_event["id"] for item in search.json())

    daily_a = client.get("/api/pulls/daily", params={"day": "2026-07-11"})
    daily_b = client.get("/api/pulls/daily", params={"day": "2026-07-11"})
    random_person = client.get("/api/pulls/random", params={"entity_type": "person"})
    assert_status(daily_a, 200)
    assert_status(daily_b, 200)
    assert_status(random_person, 200)
    assert daily_a.json() == daily_b.json()
    assert random_person.json()["entity_type"] == "person"

    created_person = client.post(
        "/api/people",
        json={
            "alias": "Collaudatore",
            "name": "Test",
            "surname": "API",
            "sex": "other",
            "connotation": "positive",
            "description": "Creato dalla suite completa",
            "rarity": 2.5,
        },
    )
    assert_status(created_person, 201)
    person = created_person.json()
    assert person["rarity"] == 2.5

    updated_person = client.put(
        f"/api/people/{person['id']}",
        json={
            "alias": "Collaudatore Senior",
            "name": "Test",
            "surname": "API",
            "sex": "other",
            "connotation": "neutral",
            "description": "Aggiornato dalla suite completa",
            "rarity": 3.0,
        },
    )
    assert_status(updated_person, 200)
    assert updated_person.json()["alias"] == "Collaudatore Senior"
    assert updated_person.json()["rarity"] == 3.0

    created_place = client.post(
        "/api/places",
        json={"name": "Laboratorio API", "description": "Luogo creato dai test", "rarity": 1.2},
    )
    created_epoch = client.post(
        "/api/epochs",
        json={"name": "Epoca dei Test", "description": "Epoca creata dai test", "rarity": 1.1},
    )
    assert_status(created_place, 201)
    assert_status(created_epoch, 201)
    place = created_place.json()
    epoch = created_epoch.json()

    linked_places = client.put(
        f"/api/people/{person['id']}/places",
        json=[{"place_id": place["id"], "motivation": "Verifica link persona-luogo"}],
    )
    assert_status(linked_places, 200)
    assert linked_places.json()[0]["place_id"] == place["id"]
    reverse_people = client.get(f"/api/places/{place['id']}/people")
    assert_status(reverse_people, 200)
    assert any(item["person_id"] == person["id"] for item in reverse_people.json())

    created_event = client.post(
        "/api/events",
        json={
            "title": "Evento API completo",
            "description": "Evento creato dalla suite completa",
            "place_id": place["id"],
            "epoch_id": epoch["id"],
            "year": 2026,
            "month": 7,
            "day": 11,
            "rarity": 4.0,
        },
    )
    assert_status(created_event, 201)
    event = created_event.json()
    assert event["rarity"] == 4.0
    assert event["place"]["id"] == place["id"]
    assert event["epoch"]["id"] == epoch["id"]

    participants = client.put(
        f"/api/events/{event['id']}/participants",
        json=[{"person_id": person["id"], "role": "Testimone", "motivation": "Protagonista del test"}],
    )
    assert_status(participants, 200)
    assert participants.json()[0]["person"]["id"] == person["id"]
    assert participants.json()[0]["role"] == "Testimone"
    person_events = client.get(f"/api/people/{person['id']}/events")
    assert_status(person_events, 200)
    assert any(item["event_id"] == event["id"] for item in person_events.json())

    listed_place_events = client.get(f"/api/places/{place['id']}/events")
    listed_epoch_events = client.get(f"/api/epochs/{epoch['id']}/events")
    assert_status(listed_place_events, 200)
    assert_status(listed_epoch_events, 200)
    assert [item["id"] for item in listed_place_events.json()] == [event["id"]]
    assert [item["id"] for item in listed_epoch_events.json()] == [event["id"]]

    uploaded = client.post(
        "/api/media",
        data={"pullable_id": str(event["id"])},
        files={"file": ("tiny.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert_status(uploaded, 201)
    media = uploaded.json()
    media_list = client.get("/api/media", params={"pullable_id": event["id"]})
    assert_status(media_list, 200)
    assert any(item["id"] == media["id"] for item in media_list.json())
    media_file = client.get(f"/api/media/{media['id']}")
    assert_status(media_file, 200)
    assert media_file.headers["content-type"].startswith("image/png")

    invalid_person = client.post("/api/people", json={"alias": "Robot", "sex": "robot", "rarity": 1.0})
    invalid_event = client.post(
        "/api/events",
        json={"title": "Data errata", "place_id": place["id"], "epoch_id": epoch["id"], "month": 7, "rarity": 1.0},
    )
    invalid_media = client.post(
        "/api/media",
        data={"pullable_id": str(event["id"])},
        files={"file": ("note.txt", b"not an image", "text/plain")},
    )
    assert_status(invalid_person, 422)
    assert_status(invalid_event, 422)
    assert_status(invalid_media, 415)

    assert_status(client.delete(f"/api/places/{place['id']}"), 409)
    assert_status(client.delete(f"/api/epochs/{epoch['id']}"), 409)

    assert_status(client.delete(f"/api/events/{event['id']}"), 204)
    assert_status(client.get(f"/api/events/{event['id']}"), 404)
    assert_status(client.get(f"/api/media/{media['id']}"), 404)
    person_events_after_delete = client.get(f"/api/people/{person['id']}/events")
    assert_status(person_events_after_delete, 200)
    assert all(item["event_id"] != event["id"] for item in person_events_after_delete.json())

    assert_status(client.delete(f"/api/places/{place['id']}"), 204)
    assert_status(client.delete(f"/api/epochs/{epoch['id']}"), 204)
    assert_status(client.delete(f"/api/people/{person['id']}"), 204)
    assert_status(client.get(f"/api/people/{person['id']}"), 404)
