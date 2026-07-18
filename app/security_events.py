from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import SecurityEventLog, SecurityEventType, UserAccount

AUTHENTICATION_EVENT_TYPES = (
    SecurityEventType.LOGIN_SUCCEEDED.value,
    SecurityEventType.LOGIN_FAILED.value,
    SecurityEventType.LOGIN_RATE_LIMITED.value,
    SecurityEventType.LOGOUT.value,
)
AUTHENTICATION_RETENTION = timedelta(days=90)


def request_ip(request: Request) -> str:
    return (request.client.host if request.client else "unknown")[:45]


def log_security_event(
    db: Session,
    event_type: SecurityEventType,
    occurred_at: datetime,
    *,
    actor: UserAccount | None = None,
    target: UserAccount | None = None,
    attempted_username: str | None = None,
    source_ip: str | None = None,
    payload: Any = None,
) -> SecurityEventLog:
    event = SecurityEventLog(
        event_type=event_type.value,
        actor_user_id=actor.id if actor else None,
        target_user_id=target.id if target else None,
        attempted_username=attempted_username,
        source_ip=source_ip,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        occurred_at=occurred_at,
    )
    db.add(event)
    return event


def prune_authentication_events(db: Session, now: datetime) -> int:
    return (
        db.query(SecurityEventLog)
        .filter(
            SecurityEventLog.event_type.in_(AUTHENTICATION_EVENT_TYPES),
            SecurityEventLog.occurred_at < now - AUTHENTICATION_RETENTION,
        )
        .delete(synchronize_session=False)
    )
