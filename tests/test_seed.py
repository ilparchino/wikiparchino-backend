from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy import func
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, make_engine
from app.models import (
    ActivityAction,
    ActivityLog,
    Connotation,
    Epoch,
    Event,
    MediaAsset,
    Person,
    PersonEvent,
    PersonPlace,
    Place,
    Pullable,
    SecurityEventLog,
    SecurityEventType,
    Sex,
    UserAccount,
    UserSession,
)
from app.security import verify_password
from app.seed import DEMO_PASSWORD, SeedDataError, seed_demo_data, seed_test_data


def database_session(tmp_path: Path, name: str = "seed.sqlite") -> Session:
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return factory()


def test_rich_demo_seed_is_anonymized_complete_and_consistent(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    with database_session(tmp_path) as db:
        seed_demo_data(db, media_dir=media_dir, now=now)

        assert db.query(UserAccount).count() == 8
        assert db.query(UserAccount).filter(UserAccount.is_active.is_(True)).count() == 7
        assert db.query(UserAccount).filter(UserAccount.is_admin.is_(True)).count() == 2
        assert db.query(UserAccount).filter(UserAccount.is_owner.is_(True)).count() == 1
        assert db.query(UserSession).count() == 0
        assert {user.username for user in db.query(UserAccount).all()} == {
            "admin",
            "admin2",
            "utente1",
            "utente2",
            "utente3",
            "utente4",
            "utente5",
            "utente6",
        }
        assert all(
            verify_password(DEMO_PASSWORD, user.password_hash)
            for user in db.query(UserAccount).all()
        )
        inactive = db.query(UserAccount).filter_by(username="utente6").one()
        assert inactive.is_active is False
        owner = db.query(UserAccount).filter_by(is_owner=True).one()
        assert owner.username == "admin"
        assert owner.is_admin is True
        assert owner.is_active is True

        assert db.query(Person).count() == 24
        assert db.query(Place).count() == 12
        assert db.query(Epoch).count() == 5
        assert db.query(Event).count() == 40
        assert db.query(Pullable).count() == 81
        assert db.query(PersonPlace).count() == 48
        assert db.query(PersonEvent).count() == 160
        assert {person.alias for person in db.query(Person).all()} == {
            f"Persona #{index}" for index in range(1, 25)
        }
        assert {place.name for place in db.query(Place).all()} == {
            f"Luogo #{index}" for index in range(1, 13)
        }
        assert {epoch.name for epoch in db.query(Epoch).all()} == {
            f"Epoca #{index}" for index in range(1, 6)
        }
        assert {event.title for event in db.query(Event).all()} == {
            f"Evento #{index}" for index in range(1, 41)
        }

        assert {person.sex for person in db.query(Person).all()} == {
            value.value for value in Sex
        }
        assert {person.connotation for person in db.query(Person).all()} == {
            value.value for value in Connotation
        }
        assert {pullable.rarity for pullable in db.query(Pullable).all()} >= {
            0.5,
            1.0,
            1.5,
            2.0,
            3.0,
        }
        assert db.query(Person).filter(Person.name.is_(None)).count() > 0
        assert db.query(Person).filter(Person.surname.is_(None)).count() > 0
        assert db.query(Person).filter(Person.description.is_(None)).count() > 0

        events = db.query(Event).all()
        date_shapes = {
            (event.year is not None, event.month is not None, event.day is not None)
            for event in events
        }
        assert date_shapes == {
            (False, False, False),
            (True, False, False),
            (True, True, False),
            (True, True, True),
        }
        assert {link.role for link in db.query(PersonEvent).all()} == {
            "Organizzatore",
            "Guida",
            "Partecipante",
            None,
        }

        assets = db.query(MediaAsset).all()
        assert len(assets) == 18
        assert all(Path(asset.disk_path).is_file() for asset in assets)
        assert all(Path(asset.disk_path).parent == media_dir.resolve() for asset in assets)
        assert all(Path(asset.disk_path).read_bytes().startswith(b"<?xml") for asset in assets)
        image_counts = dict(
            db.query(MediaAsset.pullable_id, func.count(MediaAsset.id))
            .group_by(MediaAsset.pullable_id)
            .all()
        )
        assert len(image_counts) == 14
        assert list(image_counts.values()).count(2) == 4
        assert db.query(MediaAsset).join(Person, Person.id == MediaAsset.pullable_id).count() == 6
        assert db.query(MediaAsset).join(Place, Place.id == MediaAsset.pullable_id).count() == 5
        assert db.query(MediaAsset).join(Epoch, Epoch.id == MediaAsset.pullable_id).count() == 3
        assert db.query(MediaAsset).join(Event, Event.id == MediaAsset.pullable_id).count() == 4
        rendered_images = b"".join(Path(asset.disk_path).read_bytes() for asset in assets)
        assert b'width="480" height="640"' in rendered_images
        assert b'width="640" height="360"' in rendered_images

        assert db.query(ActivityLog).count() == 163
        assert db.query(SecurityEventLog).count() == 9
        active_ids = {
            user.id
            for user in db.query(UserAccount).filter(UserAccount.is_active.is_(True)).all()
        }
        assert {
            actor_id
            for (actor_id,) in db.query(ActivityLog.actor_user_id).distinct().all()
        } == active_ids

        for log in db.query(ActivityLog).filter_by(action=ActivityAction.CREATE.value):
            assert db.get(Pullable, log.entity_id).created_at == log.occurred_at
        for log in db.query(ActivityLog).filter_by(
            action=ActivityAction.REPLACE_PLACES.value
        ):
            links = db.query(PersonPlace).filter_by(person_id=log.entity_id).all()
            assert len(links) == 2
            assert all(link.created_at == link.updated_at == log.occurred_at for link in links)
        for log in db.query(ActivityLog).filter_by(
            action=ActivityAction.REPLACE_PARTICIPANTS.value
        ):
            links = db.query(PersonEvent).filter_by(event_id=log.entity_id).all()
            assert len(links) == 4
            assert all(link.created_at == link.updated_at == log.occurred_at for link in links)
        for log in db.query(ActivityLog).filter_by(
            action=ActivityAction.UPLOAD_MEDIA.value
        ):
            media_id = json.loads(log.payload_json)["media_id"]
            assert db.get(MediaAsset, media_id).created_at == log.occurred_at

        for pullable in db.query(Pullable).all():
            latest = (
                db.query(ActivityLog)
                .filter_by(entity_id=pullable.id)
                .order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
                .first()
            )
            assert latest is not None
            assert pullable.updated_at == latest.occurred_at
            assert pullable.updated_by == latest.actor_user_id

        for user in db.query(UserAccount).all():
            created = (
                db.query(SecurityEventLog)
                .filter_by(
                    target_user_id=user.id,
                    event_type=SecurityEventType.USER_CREATED.value,
                )
                .one()
            )
            assert created.occurred_at == user.created_at
        deactivated = (
            db.query(SecurityEventLog)
            .filter_by(
                target_user_id=inactive.id,
                event_type=SecurityEventType.USER_DEACTIVATED.value,
            )
            .one()
        )
        assert deactivated.occurred_at == inactive.updated_at

        ordered = [
            value
            for (value,) in db.query(ActivityLog.occurred_at)
            .order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
            .all()
        ]
        assert ordered == sorted(ordered, reverse=True)

        with pytest.raises(SeedDataError, match="requires an empty database"):
            seed_demo_data(db, media_dir=media_dir, now=now)


def test_demo_seed_rejects_existing_media_and_cleans_up_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    occupied_media = tmp_path / "occupied-media"
    occupied_media.mkdir()
    existing = occupied_media / "keep.txt"
    existing.write_text("keep")
    with database_session(tmp_path, "occupied.sqlite") as db:
        with pytest.raises(SeedDataError, match="empty media directory"):
            seed_demo_data(db, media_dir=occupied_media)
        assert existing.read_text() == "keep"
        assert db.query(UserAccount).count() == 0

    failed_media = tmp_path / "failed-media"
    with database_session(tmp_path, "failed.sqlite") as db:
        def fail_commit() -> None:
            raise RuntimeError("database commit failed")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="database commit failed"):
            seed_demo_data(
                db,
                media_dir=failed_media,
                now=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
            )
        assert not failed_media.exists()
        assert db.query(UserAccount).count() == 0
        assert db.query(Pullable).count() == 0


def test_minimal_test_seed_remains_small_and_has_no_history(tmp_path: Path) -> None:
    with database_session(tmp_path, "minimal.sqlite") as db:
        seed_test_data(db)
        admin = db.query(UserAccount).one()
        assert admin.username == "admin"
        assert admin.is_owner is True
        assert verify_password("admin", admin.password_hash)
        assert db.query(Person).count() == 3
        assert db.query(Place).count() == 2
        assert db.query(Epoch).count() == 1
        assert db.query(Event).count() == 1
        assert db.query(PersonEvent).count() == 3
        assert db.query(MediaAsset).count() == 0
        assert db.query(ActivityLog).count() == 0
        assert db.query(SecurityEventLog).count() == 0
        assert all(
            pullable.created_at == pullable.updated_at
            and pullable.created_by == admin.id
            and pullable.updated_by == admin.id
            for pullable in db.query(Pullable).all()
        )
