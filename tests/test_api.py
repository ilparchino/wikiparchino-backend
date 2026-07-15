from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_auth_session_flow(client: httpx.Client) -> None:
    assert client.get("/api/me").status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["username"] == "admin"
    client.headers["Authorization"] = f"Bearer {payload['access_token']}"
    assert client.get("/api/me").status_code == 200


def test_crud_hard_delete_and_search(auth_client: httpx.Client) -> None:
    created = auth_client.post(
        "/api/people",
        json={
            "alias": "Testimone",
            "name": "T",
            "surname": None,
            "sex": "unknown",
            "connotation": "positive",
            "description": "Parola chiave unica",
            "rarity": 2.0,
        },
    )
    assert created.status_code == 201
    payload = created.json()
    person_id = payload["id"]
    assert payload["rarity"] == 2.0

    search = auth_client.get("/api/search", params={"q": "unica"})
    assert search.status_code == 200
    assert any(item["id"] == person_id and item["entity_type"] == "person" for item in search.json())

    deleted = auth_client.delete(f"/api/people/{person_id}")
    assert deleted.status_code == 204
    assert auth_client.get(f"/api/people/{person_id}").status_code == 404


def test_entity_metadata_is_flattened_from_pullable_and_touched_on_update(
    auth_client: httpx.Client,
) -> None:
    user = auth_client.get("/api/me").json()
    seeded_person = auth_client.get("/api/people").json()[0]
    assert seeded_person["created_by"] == user["id"]
    assert seeded_person["updated_by"] == user["id"]
    assert seeded_person["created_at"] == seeded_person["updated_at"]

    request_payload = {
        "alias": "Metadati",
        "name": None,
        "surname": None,
        "sex": "unknown",
        "connotation": "neutral",
        "description": "Verifica dei metadati condivisi",
        "rarity": 1.0,
    }
    created = auth_client.post("/api/people", json=request_payload)
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["created_by"] == user["id"]
    assert created_payload["updated_by"] == user["id"]
    assert created_payload["created_at"] == created_payload["updated_at"]
    assert "created_by_id" not in created_payload
    assert "updated_by_id" not in created_payload

    updated = auth_client.put(
        f"/api/people/{created_payload['id']}", json=request_payload
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["created_at"] == created_payload["created_at"]
    assert updated_payload["created_by"] == created_payload["created_by"]
    assert updated_payload["updated_by"] == user["id"]
    assert parse_timestamp(updated_payload["updated_at"]) > parse_timestamp(
        created_payload["updated_at"]
    )


def test_related_content_changes_touch_only_the_endpoint_owner(
    auth_client: httpx.Client, tmp_path: Path
) -> None:
    user = auth_client.get("/api/me").json()
    people = auth_client.get("/api/people").json()
    places = auth_client.get("/api/places").json()
    event = auth_client.get("/api/events").json()[0]

    person_before_participants = auth_client.get(
        f"/api/people/{people[0]['id']}"
    ).json()
    participants = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[{"person_id": people[0]["id"], "role": "Guida", "motivation": None}],
    )
    assert participants.status_code == 200
    event_after_participants = auth_client.get(f"/api/events/{event['id']}").json()
    person_after_participants = auth_client.get(
        f"/api/people/{people[0]['id']}"
    ).json()
    assert parse_timestamp(event_after_participants["updated_at"]) > parse_timestamp(
        event["updated_at"]
    )
    assert event_after_participants["updated_by"] == user["id"]
    assert (
        person_after_participants["updated_at"]
        == person_before_participants["updated_at"]
    )

    person_before_places = person_after_participants
    place_before_link = auth_client.get(f"/api/places/{places[0]['id']}").json()
    linked = auth_client.put(
        f"/api/people/{people[0]['id']}/places",
        json=[{"place_id": places[0]["id"], "motivation": "Luogo collegato"}],
    )
    assert linked.status_code == 200
    person_after_places = auth_client.get(f"/api/people/{people[0]['id']}").json()
    place_after_link = auth_client.get(f"/api/places/{places[0]['id']}").json()
    assert parse_timestamp(person_after_places["updated_at"]) > parse_timestamp(
        person_before_places["updated_at"]
    )
    assert person_after_places["updated_by"] == user["id"]
    assert place_after_link["updated_at"] == place_before_link["updated_at"]

    event_before_media = event_after_participants
    image = tmp_path / "metadata.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        uploaded = auth_client.post(
            "/api/media",
            data={"pullable_id": str(event["id"])},
            files={"file": ("metadata.png", handle, "image/png")},
        )
    assert uploaded.status_code == 201
    event_after_media = auth_client.get(f"/api/events/{event['id']}").json()
    assert parse_timestamp(event_after_media["updated_at"]) > parse_timestamp(
        event_before_media["updated_at"]
    )
    assert event_after_media["updated_by"] == user["id"]


def test_delete_restricts_places_and_epochs_used_by_events(auth_client: httpx.Client) -> None:
    event = auth_client.get("/api/events").json()[0]
    assert auth_client.delete(f"/api/places/{event['place_id']}").status_code == 409
    assert auth_client.delete(f"/api/epochs/{event['epoch_id']}").status_code == 409


def test_delete_cascades_media_and_relationship_rows(auth_client: httpx.Client, tmp_path: Path) -> None:
    person = auth_client.post(
        "/api/people",
        json={
            "alias": "Cancellabile",
            "sex": "other",
            "connotation": "unknown",
            "description": None,
            "rarity": 1.0,
        },
    ).json()
    place = auth_client.get("/api/places").json()[0]
    linked = auth_client.put(
        f"/api/people/{person['id']}/places",
        json=[{"place_id": place["id"], "motivation": "Test cascade"}],
    )
    assert linked.status_code == 200

    image = tmp_path / "tiny.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        uploaded = auth_client.post(
            "/api/media",
            data={"pullable_id": str(person["id"])},
            files={"file": ("tiny.png", handle, "image/png")},
        )
    assert uploaded.status_code == 201
    media_id = uploaded.json()["id"]

    assert auth_client.delete(f"/api/people/{person['id']}").status_code == 204
    assert auth_client.get(f"/api/media/{media_id}").status_code == 404
    reverse_links = auth_client.get(f"/api/places/{place['id']}/people")
    assert reverse_links.status_code == 200
    assert all(item["person_id"] != person["id"] for item in reverse_links.json())


def test_event_requires_existing_place_and_epoch(auth_client: httpx.Client) -> None:
    response = auth_client.post(
        "/api/events",
        json={"title": "Evento impossibile", "place_id": 9999, "epoch_id": 9999, "year": 2025, "rarity": 1.0},
    )
    assert response.status_code == 422


def test_date_and_enum_validation(auth_client: httpx.Client) -> None:
    invalid_person = auth_client.post(
        "/api/people",
        json={"alias": "Enum errata", "sex": "robot", "connotation": "unknown", "rarity": 1.0},
    )
    assert invalid_person.status_code == 422

    places = auth_client.get("/api/places").json()
    epochs = auth_client.get("/api/epochs").json()
    invalid_date = auth_client.post(
        "/api/events",
        json={
            "title": "Evento con mese senza anno",
            "place_id": places[0]["id"],
            "epoch_id": epochs[0]["id"],
            "month": 5,
            "rarity": 1.0,
        },
    )
    assert invalid_date.status_code == 422


def test_event_allows_empty_and_partial_date(auth_client: httpx.Client) -> None:
    places = auth_client.get("/api/places").json()
    epochs = auth_client.get("/api/epochs").json()
    response = auth_client.post(
        "/api/events",
        json={
            "title": "Evento con anno solo",
            "place_id": places[0]["id"],
            "epoch_id": epochs[0]["id"],
            "year": 2025,
            "month": None,
            "day": None,
            "rarity": 1.0,
        },
    )
    assert response.status_code == 201
    assert response.json()["year"] == 2025
    assert response.json()["month"] is None

    empty = auth_client.post(
        "/api/events",
        json={
            "title": "Evento senza data",
            "place_id": places[0]["id"],
            "epoch_id": epochs[0]["id"],
            "year": None,
            "month": None,
            "day": None,
            "rarity": 1.0,
        },
    )
    assert empty.status_code == 201
    assert empty.json()["year"] is None


def test_relationships_and_pulls(auth_client: httpx.Client) -> None:
    people = auth_client.get("/api/people").json()
    events = auth_client.get("/api/events").json()
    response = auth_client.put(
        f"/api/events/{events[0]['id']}/participants",
        json=[{"person_id": people[0]["id"], "role": "Guida", "motivation": "Test"}],
    )
    assert response.status_code == 200
    assert response.json()[0]["person_id"] == people[0]["id"]
    assert auth_client.get(f"/api/people/{people[0]['id']}/events").status_code == 200

    random_pull = auth_client.get("/api/pulls/random")
    daily_pull = auth_client.get("/api/pulls/daily")
    assert random_pull.status_code == 200
    assert daily_pull.status_code == 200
    assert daily_pull.json()["mode"] == "daily"


def test_participant_roles_are_optional_free_form_strings(auth_client: httpx.Client) -> None:
    people = auth_client.get("/api/people").json()
    event = auth_client.get("/api/events").json()[0]

    response = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[
            {"person_id": people[0]["id"], "role": "  Leader  ", "motivation": None},
            {"person_id": people[1]["id"], "role": "   ", "motivation": None},
            {"person_id": people[2]["id"], "motivation": None},
        ],
    )
    assert response.status_code == 200
    roles = {item["person_id"]: item["role"] for item in response.json()}
    assert roles[people[0]["id"]] == "Leader"
    assert roles[people[1]["id"]] is None
    assert roles[people[2]["id"]] is None

    person_events = auth_client.get(f"/api/people/{people[0]['id']}/events")
    assert person_events.status_code == 200
    assert next(item for item in person_events.json() if item["event_id"] == event["id"])["role"] == "Leader"

    explicit_null = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[{"person_id": people[0]["id"], "role": None, "motivation": None}],
    )
    assert explicit_null.status_code == 200
    assert explicit_null.json()[0]["role"] is None

    max_length = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[{"person_id": people[0]["id"], "role": f"  {'x' * 255}  ", "motivation": None}],
    )
    assert max_length.status_code == 200
    assert max_length.json()[0]["role"] == "x" * 255

    too_long = auth_client.put(
        f"/api/events/{event['id']}/participants",
        json=[{"person_id": people[0]["id"], "role": "x" * 256, "motivation": None}],
    )
    assert too_long.status_code == 422


def test_media_upload_and_list(auth_client: httpx.Client, tmp_path: Path) -> None:
    event = auth_client.get("/api/events").json()[0]
    image = tmp_path / "tiny.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        response = auth_client.post(
            "/api/media",
            data={"pullable_id": str(event["id"])},
            files={"file": ("tiny.png", handle, "image/png")},
        )
    assert response.status_code == 201
    media_id = response.json()["id"]
    listed = auth_client.get("/api/media", params={"pullable_id": event["id"]})
    assert listed.status_code == 200
    assert any(item["id"] == media_id for item in listed.json())
    assert auth_client.get(f"/api/media/{media_id}").status_code == 200
