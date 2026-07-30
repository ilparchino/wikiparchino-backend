from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, make_engine
from app.manage_owner import assign_owner
from app.models import SecurityEventLog, SecurityEventType, UserAccount


FIXED_TIME = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
INITIAL_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def owner_session(tmp_path: Path) -> Session:
    engine = make_engine(f"sqlite:///{tmp_path / 'owner.sqlite'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = factory()
    db.add_all(
        [
            UserAccount(
                username="owner",
                display_name="Owner",
                password_hash="hash",
                is_active=True,
                is_admin=True,
                is_owner=True,
                created_at=INITIAL_TIME,
                updated_at=INITIAL_TIME,
            ),
            UserAccount(
                username="admin2",
                display_name="Admin 2",
                password_hash="hash",
                is_active=True,
                is_admin=True,
                is_owner=False,
                created_at=INITIAL_TIME,
                updated_at=INITIAL_TIME,
            ),
            UserAccount(
                username="regular",
                display_name="Regular",
                password_hash="hash",
                is_active=True,
                is_admin=False,
                is_owner=False,
                created_at=INITIAL_TIME,
                updated_at=INITIAL_TIME,
            ),
            UserAccount(
                username="inactive",
                display_name="Inactive",
                password_hash="hash",
                is_active=False,
                is_admin=True,
                is_owner=False,
                created_at=INITIAL_TIME,
                updated_at=INITIAL_TIME,
            ),
        ]
    )
    db.commit()
    return db


def test_assign_owner_transfers_atomically_and_logs_one_timestamp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.manage_owner.utcnow", lambda: FIXED_TIME)
    with owner_session(tmp_path) as db:
        target, previous, changed = assign_owner(db, "  ADMIN2 ")

        assert changed is True
        assert target.username == "admin2"
        assert target.is_owner is True
        assert previous is not None
        assert previous.username == "owner"
        assert previous.is_owner is False
        assert previous.is_admin is True
        assert previous.is_active is True
        assert target.updated_at == previous.updated_at == FIXED_TIME

        events = (
            db.query(SecurityEventLog)
            .filter(SecurityEventLog.event_type == SecurityEventType.ROLE_CHANGED.value)
            .order_by(SecurityEventLog.id)
            .all()
        )
        assert len(events) == 2
        assert all(event.actor_user_id is None for event in events)
        assert all(event.occurred_at == FIXED_TIME for event in events)
        assert [json.loads(event.payload_json or "{}") for event in events] == [
            {"field": "is_owner", "old": True, "new": False},
            {"field": "is_owner", "old": False, "new": True},
        ]

        same_target, same_previous, same_changed = assign_owner(db, "admin2")
        assert same_target.id == target.id
        assert same_previous is not None and same_previous.id == target.id
        assert same_changed is False
        assert db.query(SecurityEventLog).count() == 2


def test_assign_owner_supports_an_initial_explicit_assignment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.manage_owner.utcnow", lambda: FIXED_TIME)
    with owner_session(tmp_path) as db:
        previous = db.query(UserAccount).filter(UserAccount.is_owner.is_(True)).one()
        previous.is_owner = False
        db.commit()

        target, old_owner, changed = assign_owner(db, "admin2")

        assert changed is True
        assert old_owner is None
        assert target.is_owner is True
        event = db.query(SecurityEventLog).one()
        assert event.target_user_id == target.id
        assert event.occurred_at == target.updated_at == FIXED_TIME
        assert json.loads(event.payload_json or "{}") == {
            "field": "is_owner",
            "old": False,
            "new": True,
        }


@pytest.mark.parametrize(
    ("username", "message"),
    [
        ("missing", "User not found"),
        ("regular", "active administrator"),
        ("inactive", "active administrator"),
        ("   ", "Username is required"),
    ],
)
def test_assign_owner_rejects_invalid_targets(
    tmp_path: Path,
    username: str,
    message: str,
) -> None:
    with owner_session(tmp_path) as db:
        with pytest.raises(ValueError, match=message):
            assign_owner(db, username)
        assert db.query(UserAccount).filter(UserAccount.is_owner.is_(True)).one().username == "owner"
        assert db.query(SecurityEventLog).count() == 0
