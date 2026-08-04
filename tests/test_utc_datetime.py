from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import sessionmaker

from app.database import Base, make_engine
from app.database_types import UTCDateTime
from app.models import (
    ActivityLog,
    MediaAsset,
    PersonEvent,
    PersonPlace,
    Pullable,
    SecurityEventLog,
    UserAccount,
    UserSession,
)


def assert_explicit_utc(value: str) -> None:
    assert value.endswith("Z") or value.endswith("+00:00")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() == timedelta(0)


def test_every_complete_model_timestamp_uses_utc_datetime() -> None:
    timestamp_columns = (
        UserAccount.created_at,
        UserAccount.updated_at,
        UserSession.created_at,
        UserSession.expires_at,
        Pullable.created_at,
        Pullable.updated_at,
        PersonPlace.created_at,
        PersonPlace.updated_at,
        PersonEvent.created_at,
        PersonEvent.updated_at,
        MediaAsset.created_at,
        ActivityLog.occurred_at,
        SecurityEventLog.occurred_at,
    )
    assert all(isinstance(column.property.columns[0].type, UTCDateTime) for column in timestamp_columns)


def test_sqlite_utc_datetime_normalizes_restores_and_rejects_naive_values(
    tmp_path: Path,
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'utc.sqlite'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    source = datetime(2026, 7, 20, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    expected = datetime(2026, 7, 20, 10, 30, tzinfo=timezone.utc)

    with factory() as db:
        pullable = Pullable(rarity=1.0, created_at=source, updated_at=source)
        db.add(pullable)
        db.commit()
        pullable_id = pullable.id
        db.expunge_all()

        stored = db.get(Pullable, pullable_id)
        assert stored is not None
        assert stored.created_at == expected
        assert stored.updated_at == expected
        assert stored.created_at.tzinfo is timezone.utc

        db.add(
            Pullable(
                rarity=1.0,
                created_at=datetime(2026, 7, 20, 10, 30),
                updated_at=datetime(2026, 7, 20, 10, 30),
            )
        )
        with pytest.raises(StatementError, match="requires a timezone-aware datetime"):
            db.commit()
        db.rollback()

    with engine.begin() as connection:
        raw_value = connection.execute(
            text("select created_at from pullable where id = :id"),
            {"id": pullable_id},
        ).scalar_one()
        assert raw_value == "2026-07-20 10:30:00.000000"
        connection.execute(
            text(
                "insert into pullable (id, rarity, created_at, updated_at) "
                "values (100, 1.0, '2026-01-02 03:04:05.123456', "
                "'2026-01-02 03:04:05.123456')"
            )
        )

    with factory() as db:
        legacy = db.get(Pullable, 100)
        assert legacy is not None
        assert legacy.created_at == datetime(
            2026, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc
        )
        assert legacy.updated_at.tzinfo is timezone.utc


def test_api_serializes_all_exposed_complete_timestamps_as_utc(
    client: httpx.Client,
    tmp_path: Path,
) -> None:
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert login.status_code == 200
    assert_explicit_utc(login.json()["expires_at"])
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    created = client.post(
        "/api/people",
        headers=headers,
        json={
            "alias": "Persona UTC",
            "name": None,
            "surname": None,
            "sex": "unknown",
            "connotation": "unknown",
            "description": "Verifica serializzazione UTC",
            "rarity": 1.0,
        },
    )
    assert created.status_code == 201
    assert_explicit_utc(created.json()["created_at"])
    assert_explicit_utc(created.json()["updated_at"])

    image = tmp_path / "utc.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with image.open("rb") as handle:
        media = client.post(
            "/api/media",
            headers=headers,
            data={"pullable_id": str(created.json()["id"])},
            files={"file": ("utc.png", handle, "image/png")},
        )
    assert media.status_code == 201
    assert_explicit_utc(media.json()["created_at"])

    profile = client.get("/api/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["activity"]["items"]
    for item in profile.json()["activity"]["items"]:
        assert_explicit_utc(item["occurred_at"])

    users = client.get("/api/admin/users", headers=headers)
    assert users.status_code == 200
    for user in users.json():
        assert_explicit_utc(user["created_at"])
        assert_explicit_utc(user["updated_at"])

    activity = client.get("/api/admin/activity", headers=headers)
    assert activity.status_code == 200
    assert activity.json()["items"]
    for item in activity.json()["items"]:
        assert_explicit_utc(item["occurred_at"])
