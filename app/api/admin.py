from __future__ import annotations

from datetime import timedelta
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.api.deps import current_admin, current_session
from app.api.utils import MODEL_BY_ENTITY, entity_title
from app.database import get_db
from app.models import (
    ActivityLog,
    EntityType,
    Epoch,
    Event,
    MediaAsset,
    Person,
    Place,
    SecurityEventLog,
    SecurityEventType,
    UserAccount,
    UserSession,
)
from app.schemas import (
    AdminActivityOut,
    AdminActivityPage,
    AdminPasswordResetIn,
    AdminSummaryOut,
    AdminUserCreate,
    AdminUserDetailOut,
    AdminUserOut,
    AdminUserUpdate,
    SessionRevocationOut,
    UserOut,
)
from app.security import hash_password, utcnow, verify_password
from app.security_events import AUTHENTICATION_EVENT_TYPES, log_security_event, request_ip

router = APIRouter(prefix="/admin", tags=["admin"])
USER_ACTIVITY_LIMIT = 20


def user_or_404(db: Session, user_id: int) -> UserAccount:
    user = db.get(UserAccount, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utente non trovato")
    return user


def active_session_counts(db: Session, now) -> dict[int, int]:
    return dict(
        db.query(UserSession.user_id, func.count(UserSession.id))
        .filter(UserSession.expires_at > now)
        .group_by(UserSession.user_id)
        .all()
    )


def serialize_admin_user(user: UserAccount, active_sessions: int = 0) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        is_owner=user.is_owner,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        active_session_count=active_sessions,
    )


def serialize_user(user: UserAccount | None) -> UserOut | None:
    return UserOut.model_validate(user) if user else None


def logged_title(log: ActivityLog) -> str | None:
    if not log.payload_json:
        return None
    try:
        payload = json.loads(log.payload_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("title", "alias", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def serialize_content_activity(db: Session, log: ActivityLog) -> AdminActivityOut:
    actor = db.get(UserAccount, log.actor_user_id) if log.actor_user_id else None
    entity_type = None
    item = None
    try:
        entity_type = EntityType(log.entity_type)
        candidate = db.get(MODEL_BY_ENTITY[entity_type], log.entity_id)
        if candidate is not None and log.occurred_at >= candidate.pullable.created_at:
            item = candidate
    except ValueError:
        pass
    return AdminActivityOut(
        source="content",
        action=log.action,
        occurred_at=log.occurred_at,
        actor=serialize_user(actor),
        entity_type=entity_type,
        entity_id=log.entity_id,
        title=entity_title(item, entity_type) if item is not None and entity_type else logged_title(log),
        linkable=item is not None and log.action != "delete",
    )


def serialize_security_activity(db: Session, event: SecurityEventLog) -> AdminActivityOut:
    actor = db.get(UserAccount, event.actor_user_id) if event.actor_user_id else None
    target = db.get(UserAccount, event.target_user_id) if event.target_user_id else None
    is_authentication = event.event_type in AUTHENTICATION_EVENT_TYPES
    return AdminActivityOut(
        source="authentication" if is_authentication else "account",
        action=event.event_type,
        occurred_at=event.occurred_at,
        actor=serialize_user(actor),
        target=serialize_user(target),
        title=target.display_name if target else event.attempted_username,
        source_ip=event.source_ip,
    )


def validate_admin_change(
    db: Session,
    actor: UserAccount,
    target: UserAccount,
    payload: AdminUserUpdate,
) -> None:
    if target.id == actor.id and not payload.is_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Non puoi rimuovere il tuo ruolo amministratore",
        )
    if target.id == actor.id and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Non puoi disattivare il tuo account",
        )
    removes_active_admin = target.is_active and target.is_admin and (
        not payload.is_active or not payload.is_admin
    )
    if removes_active_admin:
        active_admins = (
            db.query(UserAccount)
            .filter(UserAccount.is_active.is_(True), UserAccount.is_admin.is_(True))
            .count()
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deve rimanere almeno un amministratore attivo",
            )


def forbid_other_admin_from_managing_owner(
    actor: UserAccount,
    target: UserAccount,
) -> None:
    if target.is_owner and target.id != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="L'account Proprietario può essere gestito soltanto dal Proprietario",
        )


@router.get("/summary", response_model=AdminSummaryOut)
def get_summary(
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> AdminSummaryOut:
    now = utcnow()
    since = now - timedelta(days=1)
    return AdminSummaryOut(
        total_users=db.query(UserAccount).count(),
        active_users=db.query(UserAccount).filter(UserAccount.is_active.is_(True)).count(),
        inactive_users=db.query(UserAccount).filter(UserAccount.is_active.is_(False)).count(),
        admin_users=db.query(UserAccount).filter(UserAccount.is_admin.is_(True)).count(),
        active_sessions=db.query(UserSession).filter(UserSession.expires_at > now).count(),
        people=db.query(Person).count(),
        places=db.query(Place).count(),
        epochs=db.query(Epoch).count(),
        events=db.query(Event).count(),
        media=db.query(MediaAsset).count(),
        activity_last_24h=(
            db.query(ActivityLog).filter(ActivityLog.occurred_at >= since).count()
            + db.query(SecurityEventLog).filter(SecurityEventLog.occurred_at >= since).count()
        ),
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    counts = active_session_counts(db, utcnow())
    users = db.query(UserAccount).order_by(UserAccount.display_name, UserAccount.username).all()
    return [serialize_admin_user(user, counts.get(user.id, 0)) for user in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    if db.query(UserAccount.id).filter(UserAccount.username == payload.username).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username già utilizzato")
    timestamp = utcnow()
    user = UserAccount(
        username=payload.username,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_admin=payload.is_admin,
        is_owner=False,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(user)
    db.flush()
    log_security_event(
        db,
        SecurityEventType.USER_CREATED,
        timestamp,
        actor=admin,
        target=user,
        source_ip=request_ip(request),
    )
    db.commit()
    db.refresh(user)
    return serialize_admin_user(user)


@router.get("/users/{user_id}", response_model=AdminUserDetailOut)
def get_user(
    user_id: int,
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> AdminUserDetailOut:
    target = user_or_404(db, user_id)
    content_logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.actor_user_id == user_id)
        .order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
        .limit(USER_ACTIVITY_LIMIT)
        .all()
    )
    account_logs = (
        db.query(SecurityEventLog)
        .filter(SecurityEventLog.target_user_id == user_id)
        .order_by(SecurityEventLog.occurred_at.desc(), SecurityEventLog.id.desc())
        .limit(USER_ACTIVITY_LIMIT)
        .all()
    )
    sessions = active_session_counts(db, utcnow()).get(user_id, 0)
    return AdminUserDetailOut(
        user=serialize_admin_user(target, sessions),
        content_activity=[serialize_content_activity(db, log) for log in content_logs],
        account_activity=[serialize_security_activity(db, event) for event in account_logs],
    )


@router.put("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    request: Request,
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    target = user_or_404(db, user_id)
    forbid_other_admin_from_managing_owner(admin, target)
    validate_admin_change(db, admin, target, payload)
    timestamp = utcnow()
    changed = False
    if target.display_name != payload.display_name:
        target.display_name = payload.display_name
        log_security_event(
            db,
            SecurityEventType.DISPLAY_NAME_CHANGED,
            timestamp,
            actor=admin,
            target=target,
            source_ip=request_ip(request),
        )
        changed = True
    if target.is_admin != payload.is_admin:
        previous = target.is_admin
        target.is_admin = payload.is_admin
        log_security_event(
            db,
            SecurityEventType.ROLE_CHANGED,
            timestamp,
            actor=admin,
            target=target,
            source_ip=request_ip(request),
            payload={"old": previous, "new": payload.is_admin},
        )
        changed = True
    if target.is_active != payload.is_active:
        target.is_active = payload.is_active
        if not payload.is_active:
            db.query(UserSession).filter(UserSession.user_id == target.id).delete(
                synchronize_session=False
            )
        log_security_event(
            db,
            SecurityEventType.USER_ACTIVATED if payload.is_active else SecurityEventType.USER_DEACTIVATED,
            timestamp,
            actor=admin,
            target=target,
            source_ip=request_ip(request),
        )
        changed = True
    if changed:
        target.updated_at = timestamp
        db.commit()
        db.refresh(target)
    sessions = active_session_counts(db, utcnow()).get(target.id, 0)
    return serialize_admin_user(target, sessions)


@router.put(
    "/users/{user_id}/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def reset_password(
    user_id: int,
    payload: AdminPasswordResetIn,
    request: Request,
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> Response:
    target = user_or_404(db, user_id)
    forbid_other_admin_from_managing_owner(admin, target)
    if target.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cambia la tua password dalla pagina profilo",
        )
    if verify_password(payload.new_password, target.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve essere diversa da quella attuale",
        )
    timestamp = utcnow()
    target.password_hash = hash_password(payload.new_password)
    target.updated_at = timestamp
    db.query(UserSession).filter(UserSession.user_id == target.id).delete(synchronize_session=False)
    log_security_event(
        db,
        SecurityEventType.PASSWORD_RESET,
        timestamp,
        actor=admin,
        target=target,
        source_ip=request_ip(request),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/sessions/revoke", response_model=SessionRevocationOut)
def revoke_sessions(
    user_id: int,
    request: Request,
    session: UserSession = Depends(current_session),
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> SessionRevocationOut:
    target = user_or_404(db, user_id)
    forbid_other_admin_from_managing_owner(admin, target)
    query = db.query(UserSession).filter(UserSession.user_id == target.id)
    if target.id == admin.id:
        query = query.filter(UserSession.id != session.id)
    revoked = query.delete(synchronize_session=False)
    timestamp = utcnow()
    log_security_event(
        db,
        SecurityEventType.SESSIONS_REVOKED,
        timestamp,
        actor=admin,
        target=target,
        source_ip=request_ip(request),
        payload={"count": revoked},
    )
    db.commit()
    return SessionRevocationOut(revoked_count=revoked)


@router.get("/activity", response_model=AdminActivityPage)
def list_activity(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    actor_user_id: int | None = Query(default=None, ge=1),
    source: Literal["content", "account", "authentication"] | None = None,
    action: str | None = Query(default=None, max_length=40),
    admin: UserAccount = Depends(current_admin),
    db: Session = Depends(get_db),
) -> AdminActivityPage:
    queries = []
    if source in (None, "content"):
        content_query = select(
            literal("content").label("source"),
            ActivityLog.id.label("log_id"),
            ActivityLog.occurred_at.label("occurred_at"),
        )
        if actor_user_id is not None:
            content_query = content_query.where(ActivityLog.actor_user_id == actor_user_id)
        if action:
            content_query = content_query.where(ActivityLog.action == action)
        queries.append(content_query)
    if source != "content":
        source_column = case(
            (SecurityEventLog.event_type.in_(AUTHENTICATION_EVENT_TYPES), literal("authentication")),
            else_=literal("account"),
        )
        security_query = select(
            source_column.label("source"),
            SecurityEventLog.id.label("log_id"),
            SecurityEventLog.occurred_at.label("occurred_at"),
        )
        if source == "authentication":
            security_query = security_query.where(
                SecurityEventLog.event_type.in_(AUTHENTICATION_EVENT_TYPES)
            )
        elif source == "account":
            security_query = security_query.where(
                ~SecurityEventLog.event_type.in_(AUTHENTICATION_EVENT_TYPES)
            )
        if actor_user_id is not None:
            security_query = security_query.where(SecurityEventLog.actor_user_id == actor_user_id)
        if action:
            security_query = security_query.where(SecurityEventLog.event_type == action)
        queries.append(security_query)

    combined = union_all(*queries).subquery()
    total = db.execute(select(func.count()).select_from(combined)).scalar_one()
    rows = db.execute(
        select(combined)
        .order_by(combined.c.occurred_at.desc(), combined.c.source, combined.c.log_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items: list[AdminActivityOut] = []
    for row in rows:
        if row.source == "content":
            log = db.get(ActivityLog, row.log_id)
            if log:
                items.append(serialize_content_activity(db, log))
        else:
            event = db.get(SecurityEventLog, row.log_id)
            if event:
                items.append(serialize_security_activity(db, event))
    return AdminActivityPage(items=items, total=total, page=page, page_size=page_size)
