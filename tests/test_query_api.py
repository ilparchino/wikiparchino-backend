from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy import event as sqlalchemy_event, select

from app import database
from app.api.admin import get_summary, hydrate_activity
from app.api.entities import event_date_ordering
from app.models import (
    ActivityAction,
    ActivityLog,
    EntityType,
    Epoch,
    Event,
    Person,
    Place,
    Pullable,
    UserAccount,
)
from app.security import utcnow


COLLECTIONS = ("people", "places", "epochs", "events", "groups")


def test_collection_envelopes_pagination_filters_and_sorting(
    auth_client: httpx.Client,
) -> None:
    for collection in COLLECTIONS:
        response = auth_client.get(
            f"/api/{collection}",
            params={"page": 1, "page_size": 1},
        )
        assert response.status_code == 200
        page = response.json()
        assert set(page) == {"items", "total", "page", "page_size"}
        assert page["page"] == 1
        assert page["page_size"] == 1
        assert len(page["items"]) == 1
        assert page["total"] >= 1

    people = auth_client.get(
        "/api/people",
        params={
            "q": "Persona",
            "sex": "unknown",
            "connotation": "unknown",
            "sort": "alias",
            "order": "desc",
        },
    )
    assert people.status_code == 200
    aliases = [item["alias"] for item in people.json()["items"]]
    assert aliases == sorted(aliases, key=str.casefold, reverse=True)

    events = auth_client.get(
        "/api/events",
        params={"year": 2020, "sort": "date", "order": "asc"},
    )
    assert events.status_code == 200
    assert all(item["year"] == 2020 for item in events.json()["items"])

    assert auth_client.get("/api/people", params={"page_size": 101}).status_code == 422
    assert auth_client.get("/api/events", params={"sort": "unsupported"}).status_code == 422


def test_event_date_sort_uses_earliest_date_and_keeps_unknown_last(
    auth_client: httpx.Client,
) -> None:
    place_id = auth_client.get("/api/places", params={"page_size": 1}).json()["items"][0]["id"]
    epoch_id = auth_client.post(
        "/api/epochs",
        json={"name": "Epoca ordinamento date", "description": None, "rarity": 1.0},
    ).json()["id"]
    created: list[tuple[int, str]] = []
    dates = (
        ("Data sconosciuta", None, None, None),
        ("Solo anno", 2025, None, None),
        ("Anno e mese equivalenti", 2025, 1, None),
        ("Data completa equivalente", 2025, 1, 1),
        ("Data successiva", 2025, 2, 1),
    )
    for title, year, month, day in dates:
        response = auth_client.post(
            "/api/events",
            json={
                "place_id": place_id,
                "epoch_id": epoch_id,
                "title": title,
                "description": None,
                "year": year,
                "month": month,
                "day": day,
                "rarity": 1.0,
            },
        )
        assert response.status_code == 201
        created.append((response.json()["id"], title))

    created_ids = {item_id for item_id, _ in created}

    def sorted_created(order: str) -> list[dict]:
        response = auth_client.get(
            "/api/events",
            params={
                "epoch_id": epoch_id,
                "sort": "date",
                "order": order,
                "page_size": 100,
            },
        )
        assert response.status_code == 200
        return [item for item in response.json()["items"] if item["id"] in created_ids]

    ascending = sorted_created("asc")
    assert [item["title"] for item in ascending] == [
        "Solo anno",
        "Anno e mese equivalenti",
        "Data completa equivalente",
        "Data successiva",
        "Data sconosciuta",
    ]
    equivalent_ids = [item["id"] for item in ascending[:3]]
    assert equivalent_ids == sorted(equivalent_ids)

    descending = sorted_created("desc")
    assert [item["title"] for item in descending] == [
        "Data successiva",
        "Data completa equivalente",
        "Anno e mese equivalenti",
        "Solo anno",
        "Data sconosciuta",
    ]
    assert [item["id"] for item in descending[1:4]] == sorted(equivalent_ids, reverse=True)


def test_event_date_sort_matches_existing_indexes(
    auth_client: httpx.Client,
) -> None:
    expected_indexes = {
        None: "ix_event_date_id",
        "place": "ix_event_place_date_id",
        "epoch": "ix_event_epoch_date_id",
    }
    filters = {
        None: None,
        "place": Event.place_id == 1,
        "epoch": Event.epoch_id == 1,
    }

    for filter_name, index_name in expected_indexes.items():
        for order in ("asc", "desc"):
            statement = (
                select(Event.id)
                .join(Pullable, Pullable.id == Event.id)
                .join(Place, Place.id == Event.place_id)
                .join(Epoch, Epoch.id == Event.epoch_id)
            )
            if filters[filter_name] is not None:
                statement = statement.where(filters[filter_name])
            statement = statement.order_by(*event_date_ordering(order)).limit(18)
            parameterized_sql = str(statement.compile(database.engine))
            assert "coalesce(event.month, ?)" not in parameterized_sql
            assert "coalesce(event.day, ?)" not in parameterized_sql
            compiled = statement.compile(
                database.engine,
                compile_kwargs={"literal_binds": True},
            )
            sql = str(compiled)
            assert "coalesce(event.month, 1)" in sql
            assert "coalesce(event.day, 1)" in sql

            with database.engine.connect() as connection:
                plan = connection.exec_driver_sql(
                    f"EXPLAIN QUERY PLAN {sql}"
                ).all()
            details = [row[3] for row in plan]
            assert any(index_name in detail for detail in details)
            assert not any("TEMP B-TREE FOR ORDER BY" in detail.upper() for detail in details)


def test_pullable_counts_recent_and_global_search_pagination(
    auth_client: httpx.Client,
) -> None:
    counts_response = auth_client.get("/api/pullables/counts")
    assert counts_response.status_code == 200
    counts = counts_response.json()
    for collection in COLLECTIONS:
        collection_total = auth_client.get(
            f"/api/{collection}", params={"page_size": 1}
        ).json()["total"]
        assert counts[collection] == collection_total

    recent = auth_client.get(
        "/api/pullables/recent", params={"page": 1, "page_size": 2}
    )
    assert recent.status_code == 200
    payload = recent.json()
    assert len(payload["items"]) == 2
    assert payload["total"] == sum(counts.values())
    ordering = [(item["created_at"], item["id"]) for item in payload["items"]]
    assert ordering == sorted(ordering, reverse=True)

    people_recent = auth_client.get(
        "/api/pullables/recent",
        params={"entity_type": "person", "page_size": 1},
    )
    assert people_recent.status_code == 200
    assert people_recent.json()["items"][0]["entity_type"] == "person"
    assert people_recent.json()["total"] == counts["people"]

    search = auth_client.get(
        "/api/search",
        params={"q": "#", "entity_type": "person", "page_size": 1},
    )
    assert search.status_code == 200
    assert search.json()["page_size"] == 1
    assert len(search.json()["items"]) == 1
    assert all(item["entity_type"] == "person" for item in search.json()["items"])
    assert auth_client.get("/api/search", params={"q": "x", "page_size": 51}).status_code == 422


def test_media_ids_profile_pagination_and_activity_order(
    auth_client: httpx.Client,
) -> None:
    person = auth_client.get("/api/people", params={"page_size": 1}).json()["items"][0]
    uploaded_ids: list[int] = []
    for index in range(2):
        uploaded = auth_client.post(
            "/api/media",
            data={"pullable_id": str(person["id"])},
            files={"file": (f"image-{index}.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        assert uploaded.status_code == 201
        uploaded_ids.append(uploaded.json()["id"])

    detail = auth_client.get(f"/api/people/{person['id']}").json()
    assert detail["media_ids"][:2] == list(reversed(uploaded_ids))
    assert auth_client.get("/api/media", params={"pullable_id": person["id"]}).status_code == 405

    profile = auth_client.get("/api/profile", params={"page": 1, "page_size": 2})
    assert profile.status_code == 200
    activity = profile.json()["activity"]
    assert activity["page"] == 1
    assert activity["page_size"] == 2
    assert len(activity["items"]) <= 2
    assert activity["total"] >= len(activity["items"])

    descending = auth_client.get(
        "/api/admin/activity", params={"page_size": 20, "order": "desc"}
    )
    ascending = auth_client.get(
        "/api/admin/activity", params={"page_size": 20, "order": "asc"}
    )
    assert descending.status_code == ascending.status_code == 200
    desc_times = [item["occurred_at"] for item in descending.json()["items"]]
    asc_times = [item["occurred_at"] for item in ascending.json()["items"]]
    assert desc_times == sorted(desc_times, reverse=True)
    assert asc_times == sorted(asc_times)


def test_auth_me_is_canonical(client: httpx.Client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/me").status_code == 404
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    token = login.json()["access_token"]
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_activity_hydration_query_count_is_independent_of_page_size(
    auth_client: httpx.Client,
) -> None:
    with database.SessionLocal() as db:
        admin = db.query(UserAccount).filter_by(username="admin").one()
        person = db.query(Person).order_by(Person.id).first()
        timestamp = utcnow()
        logs = [
            ActivityLog(
                entity_type=EntityType.PERSON.value,
                entity_id=person.id,
                action=ActivityAction.UPDATE.value,
                actor_user_id=admin.id,
                occurred_at=timestamp + timedelta(microseconds=index),
            )
            for index in range(20)
        ]
        db.add_all(logs)
        db.commit()
        identities = [("content", log.id) for log in logs]

    def select_count(requested: list[tuple[str, int]]) -> int:
        statements = 0

        def count_selects(conn, cursor, statement, parameters, context, executemany):
            nonlocal statements
            if statement.lstrip().upper().startswith("SELECT"):
                statements += 1

        sqlalchemy_event.listen(database.engine, "before_cursor_execute", count_selects)
        try:
            with database.SessionLocal() as db:
                hydrate_activity(db, requested)
        finally:
            sqlalchemy_event.remove(database.engine, "before_cursor_execute", count_selects)
        return statements

    assert select_count(identities[:1]) == select_count(identities)


def test_admin_summary_uses_one_database_round_trip(auth_client: httpx.Client) -> None:
    statements = 0

    def count_selects(conn, cursor, statement, parameters, context, executemany):
        nonlocal statements
        if statement.lstrip().upper().startswith("SELECT"):
            statements += 1

    with database.SessionLocal() as db:
        admin = db.query(UserAccount).filter_by(username="admin").one()
        sqlalchemy_event.listen(database.engine, "before_cursor_execute", count_selects)
        try:
            summary = get_summary(admin=admin, db=db)
        finally:
            sqlalchemy_event.remove(database.engine, "before_cursor_execute", count_selects)

    assert statements == 1
    assert summary.total_users >= 1


def test_relationship_hydration_query_count_is_independent_of_page_size(
    auth_client: httpx.Client,
) -> None:
    from app.api.relationships import list_event_participants
    def select_statements(page_size: int) -> list[str]:
        statements: list[str] = []

        def collect_selects(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        with database.SessionLocal() as db:
            admin = db.query(UserAccount).filter_by(username="admin").one()
            event_id = db.query(Event.id).order_by(Event.id).scalar()
            sqlalchemy_event.listen(database.engine, "before_cursor_execute", collect_selects)
            try:
                list_event_participants(
                    event_id=event_id,
                    page_number=1,
                    page_size=page_size,
                    q=None,
                    sex=None,
                    connotation=None,
                    sort="alias",
                    order="asc",
                    user=admin,
                    db=db,
                )
            finally:
                sqlalchemy_event.remove(database.engine, "before_cursor_execute", collect_selects)
        return statements

    one_item = select_statements(1)
    full_page = select_statements(100)
    assert len(one_item) == len(full_page)
    assert not any("media_asset" in statement.lower() for statement in full_page)
