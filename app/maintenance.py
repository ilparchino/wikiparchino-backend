from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import MaintenanceWindow, UserSession
from app.schemas import MaintenanceStatusOut


DEFAULT_MAINTENANCE_MESSAGE = (
    "Wiki Parchino sarà temporaneamente non disponibile per manutenzione."
)


class MaintenanceState(StrEnum):
    AVAILABLE = "available"
    SCHEDULED = "scheduled"
    ACTIVE = "active"


def open_maintenance_window(db: Session) -> MaintenanceWindow | None:
    return (
        db.query(MaintenanceWindow)
        .filter(MaintenanceWindow.ended_at.is_(None))
        .one_or_none()
    )


def activate_due_maintenance(
    db: Session,
    window: MaintenanceWindow,
    now: datetime,
) -> MaintenanceWindow:
    if now < window.starts_at or window.sessions_revoked_at is not None:
        return window

    claimed = db.execute(
        update(MaintenanceWindow)
        .where(
            MaintenanceWindow.id == window.id,
            MaintenanceWindow.sessions_revoked_at.is_(None),
        )
        .values(sessions_revoked_at=now, sessions_revoked_count=0)
    )
    if claimed.rowcount:
        revoked = db.query(UserSession).delete(synchronize_session=False)
        db.execute(
            update(MaintenanceWindow)
            .where(MaintenanceWindow.id == window.id)
            .values(sessions_revoked_count=revoked)
        )
        db.commit()
    else:
        db.rollback()

    db.expire_all()
    return db.get(MaintenanceWindow, window.id)


def maintenance_status(db: Session, now: datetime) -> MaintenanceStatusOut:
    window = open_maintenance_window(db)
    if window is None:
        return MaintenanceStatusOut(
            state=MaintenanceState.AVAILABLE,
            server_time=now,
            login_allowed=True,
            api_available=True,
        )

    window = activate_due_maintenance(db, window, now)
    state = (
        MaintenanceState.ACTIVE
        if now >= window.starts_at
        else MaintenanceState.SCHEDULED
    )
    return MaintenanceStatusOut(
        state=state,
        server_time=now,
        announced_at=window.announced_at,
        starts_at=window.starts_at,
        message=window.message,
        login_allowed=False,
        api_available=state is MaintenanceState.SCHEDULED,
    )
