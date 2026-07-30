from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SecurityEventType, UserAccount
from app.security import utcnow
from app.security_events import log_security_event


def assign_owner(db: Session, username: str) -> tuple[UserAccount, UserAccount | None, bool]:
    normalized = username.strip().lower()
    if not normalized:
        raise ValueError("Username is required")

    target = db.query(UserAccount).filter(UserAccount.username == normalized).one_or_none()
    if target is None:
        raise ValueError(f"User not found: {normalized}")
    if not target.is_active or not target.is_admin:
        raise ValueError("The Owner must already be an active administrator")

    previous = db.query(UserAccount).filter(UserAccount.is_owner.is_(True)).one_or_none()
    if previous is not None and previous.id == target.id:
        return target, previous, False

    timestamp = utcnow()
    if previous is not None:
        previous.is_owner = False
        previous.updated_at = timestamp
        log_security_event(
            db,
            SecurityEventType.ROLE_CHANGED,
            timestamp,
            target=previous,
            payload={"field": "is_owner", "old": True, "new": False},
        )
        db.flush()

    target.is_owner = True
    target.updated_at = timestamp
    log_security_event(
        db,
        SecurityEventType.ROLE_CHANGED,
        timestamp,
        target=target,
        payload={"field": "is_owner", "old": False, "new": True},
    )
    db.commit()
    db.refresh(target)
    if previous is not None:
        db.refresh(previous)
    return target, previous, True


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign or transfer Wiki Parchino ownership")
    parser.add_argument("--username", required=True, help="Existing active administrator username")
    args = parser.parse_args()

    try:
        with SessionLocal() as db:
            owner, previous, changed = assign_owner(db, args.username)
    except ValueError as error:
        raise SystemExit(f"Error: {error}") from None

    if not changed:
        print(f"Owner unchanged: {owner.username}")
    elif previous is None:
        print(f"Owner assigned: {owner.username}")
    else:
        print(f"Ownership transferred from {previous.username} to {owner.username}")


if __name__ == "__main__":
    main()
