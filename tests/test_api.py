from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_auth_session_flow(client: httpx.Client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["username"] == "admin"
    client.headers["Authorization"] = f"Bearer {payload['access_token']}"
    assert client.get("/api/auth/me").status_code == 200


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
    assert any(item["id"] == person_id and item["entity_type"] == "person" for item in search.json()["items"])

    deleted = auth_client.delete(f"/api/people/{person_id}")
    assert deleted.status_code == 204
    assert auth_client.get(f"/api/people/{person_id}").status_code == 404


def test_collection_search_routes_are_typed_limited_and_ordered(
    auth_client: httpx.Client,
) -> None:
    cases = (
        ("people", "Persona", "Persona #1"),
        ("places", "Dimostrativa", "Luogo #1"),
        ("epochs", "Epoca", "Epoca #1"),
        ("events", "Evento", "Evento #1"),
        ("groups", "Cerchia", "Cerchia #1"),
    )
    for collection, query, expected_title in cases:
        response = auth_client.get(
            f"/api/{collection}/search",
            params={"q": query, "limit": 20},
        )
        assert response.status_code == 200
        assert response.json()[0]["title"] == expected_title
        assert set(response.json()[0]) == {"id", "title", "subtitle"}

    limited = auth_client.get(
        "/api/people/search",
        params={"q": "Persona", "limit": 2},
    )
    assert limited.status_code == 200
    assert [item["title"] for item in limited.json()] == ["Persona #1", "Persona #2"]
    assert auth_client.get("/api/people/search", params={"q": "   "}).status_code == 422
    assert auth_client.get("/api/people/search", params={"q": "Persona", "limit": 51}).status_code == 422
    assert auth_client.get("/api/people/search", params={"q": "Persona"}).status_code == 200

    global_search = auth_client.get("/api/search", params={"q": "Persona #1"})
    assert global_search.status_code == 200
    assert any(item["entity_type"] == "person" for item in global_search.json()["items"])


def test_place_address_normalization_validation_and_search(
    auth_client: httpx.Client,
) -> None:
    created = auth_client.post(
        "/api/places",
        json={
            "name": "Luogo con indirizzo",
            "address": "  Via del Caffè 10, Città  ",
            "description": "Descrizione non usata come sottotitolo",
            "rarity": 1.0,
        },
    )
    assert created.status_code == 201
    place = created.json()
    assert place["address"] == "Via del Caffè 10, Città"

    found = auth_client.get("/api/search", params={"q": "Caffè"})
    assert found.status_code == 200
    result = next(item for item in found.json()["items"] if item["id"] == place["id"])
    assert result["entity_type"] == "place"
    assert result["subtitle"] == "Via del Caffè 10, Città"

    max_length = auth_client.put(
        f"/api/places/{place['id']}",
        json={
            "name": place["name"],
            "address": f"  {'x' * 500}  ",
            "description": place["description"],
            "rarity": place["rarity"],
        },
    )
    assert max_length.status_code == 200
    assert max_length.json()["address"] == "x" * 500

    too_long = auth_client.put(
        f"/api/places/{place['id']}",
        json={
            "name": place["name"],
            "address": "x" * 501,
            "description": place["description"],
            "rarity": place["rarity"],
        },
    )
    assert too_long.status_code == 422

    for invalid in ("Via uno\nVia due", "Via\tTab", "Via\x00Null"):
        rejected = auth_client.put(
            f"/api/places/{place['id']}",
            json={
                "name": place["name"],
                "address": invalid,
                "description": place["description"],
                "rarity": place["rarity"],
            },
        )
        assert rejected.status_code == 422

    cleared = auth_client.put(
        f"/api/places/{place['id']}",
        json={
            "name": place["name"],
            "address": "   ",
            "description": place["description"],
            "rarity": place["rarity"],
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["address"] is None


def test_group_crud_relationships_search_pulls_and_activity(
    auth_client: httpx.Client,
) -> None:
    seeded = auth_client.get("/api/groups")
    assert seeded.status_code == 200
    assert [(item["people_count"], item["epoch_count"]) for item in seeded.json()["items"]] == [
        (1, 1),
        (0, 0),
    ]

    created = auth_client.post(
        "/api/groups",
        json={
            "name": "Cerchia di verifica",
            "description": "Descrizione ricercabile della cerchia",
            "rarity": 2.5,
        },
    )
    assert created.status_code == 201
    group = created.json()
    group_id = group["id"]
    assert group["rarity"] == 2.5
    assert group["created_at"] == group["updated_at"]

    search = auth_client.get("/api/search", params={"q": "ricercabile"})
    assert search.status_code == 200
    assert any(
        item["entity_type"] == "group" and item["id"] == group_id
        for item in search.json()["items"]
    )
    pull = auth_client.get("/api/pulls/random", params={"entity_type": "group"})
    assert pull.status_code == 200
    assert pull.json()["entity_type"] == "group"

    people = auth_client.get("/api/people").json()["items"]
    epochs = auth_client.get("/api/epochs").json()["items"]
    person_ids = [people[0]["id"], people[1]["id"]]
    epoch_ids = [epochs[0]["id"]]
    person_updated_at = people[0]["updated_at"]
    epoch_updated_at = epochs[0]["updated_at"]

    replaced_people = auth_client.put(
        f"/api/groups/{group_id}/people",
        json={"person_ids": person_ids},
    )
    assert replaced_people.status_code == 200
    assert [person["id"] for person in replaced_people.json()] == person_ids
    replaced_epochs = auth_client.put(
        f"/api/groups/{group_id}/epochs",
        json={"epoch_ids": epoch_ids},
    )
    assert replaced_epochs.status_code == 200
    assert [epoch["id"] for epoch in replaced_epochs.json()] == epoch_ids

    duplicate = auth_client.put(
        f"/api/groups/{group_id}/people",
        json={"person_ids": [person_ids[0], person_ids[0]]},
    )
    assert duplicate.status_code == 422
    missing = auth_client.put(
        f"/api/groups/{group_id}/epochs",
        json={"epoch_ids": [999999]},
    )
    assert missing.status_code == 422
    assert [person["id"] for person in auth_client.get(f"/api/groups/{group_id}/people").json()] == person_ids
    assert [epoch["id"] for epoch in auth_client.get(f"/api/groups/{group_id}/epochs").json()] == epoch_ids

    reciprocal_people = auth_client.get(f"/api/people/{person_ids[0]}/groups")
    reciprocal_epochs = auth_client.get(f"/api/epochs/{epoch_ids[0]}/groups")
    assert any(item["id"] == group_id for item in reciprocal_people.json())
    assert any(item["id"] == group_id for item in reciprocal_epochs.json())
    assert auth_client.get(f"/api/people/{person_ids[0]}").json()["updated_at"] == person_updated_at
    assert auth_client.get(f"/api/epochs/{epoch_ids[0]}").json()["updated_at"] == epoch_updated_at

    from app.database import SessionLocal
    from app.models import ActivityAction, ActivityLog, Pullable, SocialGroupEpoch, SocialGroupPerson

    with SessionLocal() as db:
        assert db.get(Pullable, group_id) is not None
        people_log = (
            db.query(ActivityLog)
            .filter_by(
                entity_id=group_id,
                action=ActivityAction.REPLACE_GROUP_PEOPLE.value,
            )
            .one()
        )
        epoch_log = (
            db.query(ActivityLog)
            .filter_by(
                entity_id=group_id,
                action=ActivityAction.REPLACE_GROUP_EPOCHS.value,
            )
            .one()
        )
        assert all(
            link.created_at == link.updated_at == people_log.occurred_at
            for link in db.query(SocialGroupPerson).filter_by(group_id=group_id)
        )
        assert all(
            link.created_at == link.updated_at == epoch_log.occurred_at
            for link in db.query(SocialGroupEpoch).filter_by(group_id=group_id)
        )

    deleted = auth_client.delete(f"/api/groups/{group_id}")
    assert deleted.status_code == 204
    assert auth_client.get(f"/api/groups/{group_id}").status_code == 404
    with SessionLocal() as db:
        assert db.get(Pullable, group_id) is None
        assert db.query(SocialGroupPerson).filter_by(group_id=group_id).count() == 0
        assert db.query(SocialGroupEpoch).filter_by(group_id=group_id).count() == 0


def test_entity_metadata_is_flattened_from_pullable_and_touched_on_update(
    auth_client: httpx.Client,
) -> None:
    user = auth_client.get("/api/auth/me").json()
    seeded_person = auth_client.get("/api/people").json()["items"][0]
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


def test_related_content_changes_touch_expected_entities(
    auth_client: httpx.Client, tmp_path: Path
) -> None:
    user = auth_client.get("/api/auth/me").json()
    people = auth_client.get("/api/people").json()["items"]
    places = auth_client.get("/api/places").json()["items"]
    event = auth_client.get("/api/events").json()["items"][0]

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
    assert parse_timestamp(place_after_link["updated_at"]) > parse_timestamp(
        place_before_link["updated_at"]
    )

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


def test_person_place_replacement_from_both_sides_tracks_changed_counterparts(
    auth_client: httpx.Client,
) -> None:
    people = auth_client.get("/api/people").json()["items"]
    places = auth_client.get("/api/places").json()["items"]
    person_one, person_two = people[:2]
    place_one, place_two = places[:2]

    added = auth_client.put(
        f"/api/people/{person_one['id']}/places",
        json=[{"place_id": place_one["id"], "motivation": "Prima motivazione"}],
    )
    assert added.status_code == 200
    first_person_update = auth_client.get(f"/api/people/{person_one['id']}").json()["updated_at"]
    first_place_update = auth_client.get(f"/api/places/{place_one['id']}").json()["updated_at"]
    untouched_place_update = auth_client.get(f"/api/places/{place_two['id']}").json()["updated_at"]

    unchanged = auth_client.put(
        f"/api/people/{person_one['id']}/places",
        json=[{"place_id": place_one["id"], "motivation": "Prima motivazione"}],
    )
    assert unchanged.status_code == 200
    assert parse_timestamp(auth_client.get(f"/api/people/{person_one['id']}").json()["updated_at"]) > parse_timestamp(first_person_update)
    assert auth_client.get(f"/api/places/{place_one['id']}").json()["updated_at"] == first_place_update
    assert auth_client.get(f"/api/places/{place_two['id']}").json()["updated_at"] == untouched_place_update

    replaced = auth_client.put(
        f"/api/places/{place_one['id']}/people",
        json=[{"person_id": person_two["id"], "motivation": "Nuovo collegamento"}],
    )
    assert replaced.status_code == 200
    assert replaced.json()[0]["person_id"] == person_two["id"]
    assert replaced.json()[0]["motivation"] == "Nuovo collegamento"

    duplicate = auth_client.put(
        f"/api/places/{place_one['id']}/people",
        json=[
            {"person_id": person_two["id"], "motivation": None},
            {"person_id": person_two["id"], "motivation": None},
        ],
    )
    assert duplicate.status_code == 422
    missing = auth_client.put(
        f"/api/places/{place_one['id']}/people",
        json=[{"person_id": 999999, "motivation": None}],
    )
    assert missing.status_code == 422

    from app.database import SessionLocal
    from app.models import ActivityAction, ActivityLog, PersonPlace, Pullable

    with SessionLocal() as db:
        link = db.query(PersonPlace).filter_by(place_id=place_one["id"]).one()
        place_log = (
            db.query(ActivityLog)
            .filter_by(entity_id=place_one["id"], action=ActivityAction.REPLACE_PEOPLE.value)
            .order_by(ActivityLog.id.desc())
            .first()
        )
        removed_person_log = (
            db.query(ActivityLog)
            .filter_by(entity_id=person_one["id"], action=ActivityAction.REPLACE_PLACES.value)
            .order_by(ActivityLog.id.desc())
            .first()
        )
        added_person_log = (
            db.query(ActivityLog)
            .filter_by(entity_id=person_two["id"], action=ActivityAction.REPLACE_PLACES.value)
            .order_by(ActivityLog.id.desc())
            .first()
        )
        assert place_log is not None
        assert removed_person_log is not None
        assert added_person_log is not None
        assert link.created_at == link.updated_at == place_log.occurred_at
        assert removed_person_log.occurred_at == place_log.occurred_at
        assert added_person_log.occurred_at == place_log.occurred_at
        assert db.get(Pullable, place_one["id"]).updated_at == place_log.occurred_at
        assert db.get(Pullable, person_one["id"]).updated_at == place_log.occurred_at
        assert db.get(Pullable, person_two["id"]).updated_at == place_log.occurred_at


def test_delete_restricts_places_and_epochs_used_by_events(auth_client: httpx.Client) -> None:
    event = auth_client.get("/api/events").json()["items"][0]
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
    place = auth_client.get("/api/places").json()["items"][0]
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
    from app.database import SessionLocal
    from app.models import MediaAsset

    with SessionLocal() as db:
        stored_path = Path(db.get(MediaAsset, media_id).disk_path)
    assert stored_path.exists()

    assert auth_client.delete(f"/api/people/{person['id']}").status_code == 204
    assert not stored_path.exists()
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

    places = auth_client.get("/api/places").json()["items"]
    epochs = auth_client.get("/api/epochs").json()["items"]
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
    places = auth_client.get("/api/places").json()["items"]
    epochs = auth_client.get("/api/epochs").json()["items"]
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


def test_epoch_partial_dates_and_gregorian_validation(
    auth_client: httpx.Client,
) -> None:
    ambiguous = auth_client.post(
        "/api/epochs",
        json={
            "name": "Epoca parziale",
            "description": None,
            "start_year": 2025,
            "start_month": None,
            "start_day": None,
            "end_year": 2025,
            "end_month": 3,
            "end_day": None,
            "rarity": 1.0,
        },
    )
    assert ambiguous.status_code == 201
    assert ambiguous.json()["start_year"] == 2025
    assert ambiguous.json()["end_month"] == 3

    inverted = auth_client.post(
        "/api/epochs",
        json={
            "name": "Epoca invertita",
            "start_year": 2025,
            "start_month": 4,
            "end_year": 2025,
            "end_month": 3,
            "rarity": 1.0,
        },
    )
    assert inverted.status_code == 422

    invalid_epoch_day = auth_client.post(
        "/api/epochs",
        json={
            "name": "Epoca impossibile",
            "start_year": 2025,
            "start_month": 2,
            "start_day": 29,
            "rarity": 1.0,
        },
    )
    assert invalid_epoch_day.status_code == 422

    place = auth_client.get("/api/places").json()["items"][0]
    leap_epoch = auth_client.post(
        "/api/epochs",
        json={
            "name": "Epoca bisestile",
            "start_year": 2024,
            "end_year": 2024,
            "rarity": 1.0,
        },
    ).json()
    leap_event = auth_client.post(
        "/api/events",
        json={
            "title": "Giorno bisestile",
            "place_id": place["id"],
            "epoch_id": leap_epoch["id"],
            "year": 2024,
            "month": 2,
            "day": 29,
            "rarity": 1.0,
        },
    )
    assert leap_event.status_code == 201

    invalid_event_day = auth_client.post(
        "/api/events",
        json={
            "title": "Giorno impossibile",
            "place_id": place["id"],
            "epoch_id": leap_epoch["id"],
            "year": 2025,
            "month": 2,
            "day": 29,
            "rarity": 1.0,
        },
    )
    assert invalid_event_day.status_code == 422


def test_event_epoch_range_validation_and_epoch_update_conflicts(
    auth_client: httpx.Client,
) -> None:
    place = auth_client.get("/api/places").json()["items"][0]
    epoch = auth_client.post(
        "/api/epochs",
        json={
            "name": "Epoca delimitata",
            "start_year": 2020,
            "start_month": 3,
            "end_year": 2025,
            "end_month": 6,
            "rarity": 1.0,
        },
    ).json()

    def create_event(title: str, year: int, month: int | None = None) -> httpx.Response:
        return auth_client.post(
            "/api/events",
            json={
                "title": title,
                "place_id": place["id"],
                "epoch_id": epoch["id"],
                "year": year,
                "month": month,
                "day": None,
                "rarity": 1.0,
            },
        )

    before = create_event("Prima dell'epoca", 2019)
    assert before.status_code == 422
    assert "precedente" in before.json()["detail"]

    overlapping = create_event("Data ambigua", 2020)
    assert overlapping.status_code == 201
    event_id = overlapping.json()["id"]

    after = create_event("Dopo l'epoca", 2026)
    assert after.status_code == 422
    assert "successiva" in after.json()["detail"]

    rejected_update = auth_client.put(
        f"/api/events/{event_id}",
        json={
            "title": "Data ambigua",
            "place_id": place["id"],
            "epoch_id": epoch["id"],
            "year": 2026,
            "month": None,
            "day": None,
            "rarity": 1.0,
        },
    )
    assert rejected_update.status_code == 422
    assert auth_client.get(f"/api/events/{event_id}").json()["year"] == 2020

    epoch_before = auth_client.get(f"/api/epochs/{epoch['id']}").json()
    rejected_epoch_update = auth_client.put(
        f"/api/epochs/{epoch['id']}",
        json={
            "name": epoch["name"],
            "description": epoch["description"],
            "start_year": 2021,
            "start_month": None,
            "start_day": None,
            "end_year": None,
            "end_month": None,
            "end_day": None,
            "rarity": epoch["rarity"],
        },
    )
    assert rejected_epoch_update.status_code == 409
    assert "Data ambigua" in rejected_epoch_update.json()["detail"]
    epoch_after = auth_client.get(f"/api/epochs/{epoch['id']}").json()
    assert epoch_after["start_year"] == epoch_before["start_year"]
    assert epoch_after["updated_at"] == epoch_before["updated_at"]

    start_only = auth_client.post(
        "/api/epochs",
        json={"name": "Solo inizio", "start_year": 2024, "rarity": 1.0},
    ).json()
    assert auth_client.post(
        "/api/events",
        json={
            "title": "Troppo presto",
            "place_id": place["id"],
            "epoch_id": start_only["id"],
            "year": 2023,
            "rarity": 1.0,
        },
    ).status_code == 422

    end_only = auth_client.post(
        "/api/epochs",
        json={"name": "Solo fine", "end_year": 2024, "rarity": 1.0},
    ).json()
    assert auth_client.post(
        "/api/events",
        json={
            "title": "Troppo tardi",
            "place_id": place["id"],
            "epoch_id": end_only["id"],
            "year": 2025,
            "rarity": 1.0,
        },
    ).status_code == 422


def test_relationships_and_pulls(auth_client: httpx.Client) -> None:
    people = auth_client.get("/api/people").json()["items"]
    events = auth_client.get("/api/events").json()["items"]
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
    people = auth_client.get("/api/people").json()["items"]
    event = auth_client.get("/api/events").json()["items"][0]

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


def test_media_upload_and_entity_ids(auth_client: httpx.Client, tmp_path: Path) -> None:
    event = auth_client.get("/api/events").json()["items"][0]
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
    assert auth_client.get("/api/media", params={"pullable_id": event["id"]}).status_code == 405
    refreshed_event = auth_client.get(f"/api/events/{event['id']}")
    assert refreshed_event.status_code == 200
    assert media_id in refreshed_event.json()["media_ids"]
    assert auth_client.get(f"/api/media/{media_id}").status_code == 200
    event_before_delete = auth_client.get(f"/api/events/{event['id']}").json()

    from app.database import SessionLocal
    from app.models import MediaAsset

    with SessionLocal() as db:
        stored_path = Path(db.get(MediaAsset, media_id).disk_path)
    assert stored_path.exists()

    deleted = auth_client.delete(f"/api/media/{media_id}")
    assert deleted.status_code == 204
    assert not stored_path.exists()
    event_after_delete = auth_client.get(f"/api/events/{event['id']}").json()
    assert parse_timestamp(event_after_delete["updated_at"]) > parse_timestamp(
        event_before_delete["updated_at"]
    )
    with SessionLocal() as db:
        assert db.get(MediaAsset, media_id) is None
    assert auth_client.delete(f"/api/media/{media_id}").status_code == 404


def test_media_delete_reconciles_missing_files_and_requires_authentication(
    auth_client: httpx.Client, client: httpx.Client, tmp_path: Path
) -> None:
    event = auth_client.get("/api/events").json()["items"][0]
    image = tmp_path / "stale.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        uploaded = auth_client.post(
            "/api/media",
            data={"pullable_id": str(event["id"])},
            files={"file": ("stale.png", handle, "image/png")},
        )
    assert uploaded.status_code == 201
    media_id = uploaded.json()["id"]

    from app.database import SessionLocal
    from app.models import MediaAsset

    with SessionLocal() as db:
        stored_path = Path(db.get(MediaAsset, media_id).disk_path)
    stored_path.unlink()

    auth_client.headers.pop("Authorization")
    assert client.delete(f"/api/media/{media_id}").status_code == 401
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    assert client.delete(f"/api/media/{media_id}").status_code == 204
    with SessionLocal() as db:
        assert db.get(MediaAsset, media_id) is None
