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
    SocialGroup,
    SocialGroupEpoch,
    SocialGroupPerson,
    UserAccount,
    UserSession,
)
from app.security import verify_password
from app.seed import (
    DEMO_PASSWORD,
    SeedDataError,
    StressSeedScale,
    seed_demo_data,
    seed_stress_data,
    seed_test_data,
)
from app.partial_dates import PartialDate, event_epoch_conflict


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
        assert db.query(SocialGroup).count() == 6
        assert db.query(Pullable).count() == 87
        assert db.query(PersonPlace).count() == 48
        assert db.query(PersonEvent).count() == 160
        assert db.query(SocialGroupPerson).count() == 38
        assert db.query(SocialGroupEpoch).count() == 11
        assert {person.alias for person in db.query(Person).all()} == {
            f"Persona #{index}" for index in range(1, 25)
        }
        assert {place.name for place in db.query(Place).all()} == {
            f"Luogo #{index}" for index in range(1, 13)
        }
        assert db.query(Place).filter(Place.address.is_not(None)).count() == 8
        assert db.query(Place).filter(Place.address.is_(None)).count() == 4
        assert all(
            place.address is None or "Dimostrativa" in place.address
            for place in db.query(Place).all()
        )
        assert {epoch.name for epoch in db.query(Epoch).all()} == {
            f"Epoca #{index}" for index in range(1, 6)
        }
        epoch_shapes = {
            (
                epoch.start_year is not None,
                epoch.start_month is not None,
                epoch.start_day is not None,
                epoch.end_year is not None,
                epoch.end_month is not None,
                epoch.end_day is not None,
            )
            for epoch in db.query(Epoch).all()
        }
        assert epoch_shapes == {
            (False, False, False, False, False, False),
            (True, False, False, False, False, False),
            (False, False, False, True, True, False),
            (True, True, False, True, True, True),
            (True, True, True, True, False, False),
        }
        assert {event.title for event in db.query(Event).all()} == {
            f"Evento #{index}" for index in range(1, 41)
        }
        assert {group.name for group in db.query(SocialGroup).all()} == {
            f"Cerchia #{index}" for index in range(1, 7)
        }
        empty_group = db.query(SocialGroup).filter_by(name="Cerchia #6").one()
        assert db.query(SocialGroupPerson).filter_by(group_id=empty_group.id).count() == 0
        assert db.query(SocialGroupEpoch).filter_by(group_id=empty_group.id).count() == 0

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

        for model in (Person, Place, Epoch, Event, SocialGroup):
            descriptions = [
                description
                for (description,) in db.query(model.description).all()
                if description is not None
            ]
            lengths = {len(description) for description in descriptions}
            assert min(lengths) < 20
            assert max(lengths) > 2_000
            assert len(lengths) >= 5
        assert any(
            description is None
            for model in (Person, Place, Event, SocialGroup)
            for (description,) in db.query(model.description).all()
        )

        events = db.query(Event).all()
        assert all(
            event_epoch_conflict(
                PartialDate(event.year, event.month, event.day),
                PartialDate(
                    event.epoch.start_year,
                    event.epoch.start_month,
                    event.epoch.start_day,
                ),
                PartialDate(
                    event.epoch.end_year,
                    event.epoch.end_month,
                    event.epoch.end_day,
                ),
            )
            is None
            for event in events
        )
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
        assert len(assets) == 20
        assert all(Path(asset.disk_path).is_file() for asset in assets)
        assert all(Path(asset.disk_path).parent == media_dir.resolve() for asset in assets)
        assert all(Path(asset.disk_path).read_bytes().startswith(b"<?xml") for asset in assets)
        image_counts = dict(
            db.query(MediaAsset.pullable_id, func.count(MediaAsset.id))
            .group_by(MediaAsset.pullable_id)
            .all()
        )
        assert len(image_counts) == 16
        assert list(image_counts.values()).count(2) == 4
        assert db.query(MediaAsset).join(Person, Person.id == MediaAsset.pullable_id).count() == 6
        assert db.query(MediaAsset).join(Place, Place.id == MediaAsset.pullable_id).count() == 5
        assert db.query(MediaAsset).join(Epoch, Epoch.id == MediaAsset.pullable_id).count() == 3
        assert db.query(MediaAsset).join(Event, Event.id == MediaAsset.pullable_id).count() == 4
        assert db.query(MediaAsset).join(SocialGroup, SocialGroup.id == MediaAsset.pullable_id).count() == 2
        rendered_images = b"".join(Path(asset.disk_path).read_bytes() for asset in assets)
        assert b'width="480" height="640"' in rendered_images
        assert b'width="640" height="360"' in rendered_images

        assert db.query(ActivityLog).count() == 181
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
            action=ActivityAction.REPLACE_GROUP_PEOPLE.value
        ):
            links = db.query(SocialGroupPerson).filter_by(group_id=log.entity_id).all()
            assert links
            assert all(link.created_at == link.updated_at == log.occurred_at for link in links)
        for log in db.query(ActivityLog).filter_by(
            action=ActivityAction.REPLACE_GROUP_EPOCHS.value
        ):
            links = db.query(SocialGroupEpoch).filter_by(group_id=log.entity_id).all()
            assert links
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


def test_stress_seed_covers_scale_boundaries_and_relationships(tmp_path: Path) -> None:
    media_dir = tmp_path / "stress-media"
    now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    scale = StressSeedScale(
        people=252,
        places=212,
        epochs=212,
        events=252,
        groups=212,
        media=20,
    )
    with database_session(tmp_path, "stress.sqlite") as db:
        seed_stress_data(db, media_dir=media_dir, now=now, scale=scale)

        assert db.query(UserAccount).count() == 8
        assert db.query(UserAccount).filter_by(is_owner=True).one().username == "admin"
        assert db.query(UserAccount).filter_by(username="utente6").one().is_active is False
        assert max(len(user.display_name) for user in db.query(UserAccount).all()) == 160
        assert db.query(Person).count() == scale.people
        assert db.query(Place).count() == scale.places
        assert db.query(Epoch).count() == scale.epochs
        assert db.query(Event).count() == scale.events
        assert db.query(SocialGroup).count() == scale.groups
        assert db.query(Pullable).count() == sum(
            (scale.people, scale.places, scale.epochs, scale.events, scale.groups)
        )

        assert db.query(PersonPlace).count() == scale.people * 4
        assert db.query(PersonEvent).count() == scale.events * 6
        assert db.query(SocialGroupPerson).count() == sum(
            min(scale.people, 5 + index % 46)
            for index in range(scale.groups - 1)
        )
        assert db.query(SocialGroupEpoch).count() == sum(
            min(scale.epochs, 1 + index % 10)
            for index in range(scale.groups - 1)
        )
        empty_group = db.query(SocialGroup).order_by(SocialGroup.id.desc()).first()
        assert empty_group is not None
        assert db.query(SocialGroupPerson).filter_by(group_id=empty_group.id).count() == 0
        assert db.query(SocialGroupEpoch).filter_by(group_id=empty_group.id).count() == 0

        assert max(len(person.alias) for person in db.query(Person).all()) == 255
        assert max(len(place.name) for place in db.query(Place).all()) == 255
        assert max(len(place.address or "") for place in db.query(Place).all()) == 500
        assert max(len(epoch.name) for epoch in db.query(Epoch).all()) == 255
        assert max(len(event.title) for event in db.query(Event).all()) == 255
        assert max(len(group.name) for group in db.query(SocialGroup).all()) == 255
        assert max(len(link.role or "") for link in db.query(PersonEvent).all()) == 255
        assert max(
            len(link.motivation or "")
            for model in (PersonPlace, PersonEvent)
            for link in db.query(model).all()
        ) > 20_000

        for model in (Person, Place, Epoch, Event, SocialGroup):
            descriptions = [
                value for (value,) in db.query(model.description).all() if value is not None
            ]
            assert db.query(model).filter(model.description.is_(None)).count() > 0
            assert min(map(len, descriptions)) < 200
            assert max(map(len, descriptions)) > 20_000
            assert any("\n" in value for value in descriptions)
            assert any("漢字" in value for value in descriptions)

        assert {person.sex for person in db.query(Person).all()} == {
            value.value for value in Sex
        }
        assert {person.connotation for person in db.query(Person).all()} == {
            value.value for value in Connotation
        }
        assert {pullable.rarity for pullable in db.query(Pullable).all()} == {
            0.5,
            1.0,
            1.5,
            2.0,
            3.0,
        }
        assert all(
            event_epoch_conflict(
                PartialDate(event.year, event.month, event.day),
                PartialDate(
                    event.epoch.start_year,
                    event.epoch.start_month,
                    event.epoch.start_day,
                ),
                PartialDate(
                    event.epoch.end_year,
                    event.epoch.end_month,
                    event.epoch.end_day,
                ),
            )
            is None
            for event in db.query(Event).all()
        )

        assets = db.query(MediaAsset).all()
        assert len(assets) == scale.media
        assert len({asset.pullable_id for asset in assets}) == 15
        assert all(Path(asset.disk_path).is_file() for asset in assets)
        assert len(list(media_dir.glob("*.svg"))) == scale.media
        assert db.query(ActivityLog).count() == (
            db.query(Pullable).count()
            + scale.people
            + scale.events
            + (scale.groups - 1) * 2
            + scale.media
        )
        assert db.query(SecurityEventLog).count() == 9

        person_without_media = (
            db.query(Person)
            .filter(
                ~Person.id.in_(db.query(MediaAsset.pullable_id))
            )
            .order_by(Person.id)
            .first()
        )
        assert person_without_media is not None
        person_log = (
            db.query(ActivityLog)
            .filter_by(
                entity_type="person",
                entity_id=person_without_media.id,
                action=ActivityAction.REPLACE_PLACES.value,
            )
            .one()
        )
        assert all(
            link.created_at == link.updated_at == person_log.occurred_at
            for link in db.query(PersonPlace)
            .filter_by(person_id=person_without_media.id)
            .all()
        )
        assert person_without_media.updated_at == person_log.occurred_at

        with pytest.raises(SeedDataError, match="requires an empty database"):
            seed_stress_data(db, media_dir=media_dir, now=now, scale=scale)


def test_minimal_test_seed_remains_small_and_has_no_history(tmp_path: Path) -> None:
    with database_session(tmp_path, "minimal.sqlite") as db:
        seed_test_data(db)
        admin = db.query(UserAccount).one()
        assert admin.username == "admin"
        assert admin.is_owner is True
        assert verify_password("admin", admin.password_hash)
        assert db.query(Person).count() == 3
        assert db.query(Place).count() == 2
        assert db.query(Place).filter(Place.address.is_not(None)).count() == 1
        assert db.query(Place).filter(Place.address.is_(None)).count() == 1
        assert db.query(Epoch).count() == 1
        assert db.query(Event).count() == 1
        assert db.query(SocialGroup).count() == 2
        assert db.query(SocialGroupPerson).count() == 1
        assert db.query(SocialGroupEpoch).count() == 1
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
