from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.api.deps import current_session, current_user
from app.api.utils import MODEL_BY_ENTITY
from app.database import get_db
from app.models import ActivityLog, EntityType, Pullable, SecurityEventType, UserAccount, UserSession
from app.schemas import Page, PasswordChangeIn, ProfileActivityOut, ProfileOut, UserOut
from app.security import hash_password, utcnow, verify_password
from app.security_events import log_security_event, request_ip

router = APIRouter(prefix="/profile", tags=["profile"])


def profile_activity_select(entity_type: EntityType, user_id: int):
    model = MODEL_BY_ENTITY[entity_type]
    title = model.alias if entity_type == EntityType.PERSON else (
        model.title if entity_type == EntityType.EVENT else model.name
    )
    return (
        select(
            literal(entity_type.value).label("entity_type"),
            ActivityLog.entity_id.label("entity_id"),
            title.label("title"),
            ActivityLog.action.label("action"),
            ActivityLog.occurred_at.label("occurred_at"),
            ActivityLog.id.label("log_id"),
        )
        .select_from(ActivityLog)
        .join(
            model,
            and_(
                ActivityLog.entity_type == entity_type.value,
                ActivityLog.entity_id == model.id,
            ),
        )
        .join(Pullable, Pullable.id == model.id)
        .where(
            ActivityLog.actor_user_id == user_id,
            ActivityLog.action != "delete",
            ActivityLog.occurred_at >= Pullable.created_at,
        )
    )


@router.get("", response_model=ProfileOut)
def get_profile(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    combined = union_all(*(profile_activity_select(kind, user.id) for kind in EntityType)).subquery()
    total = db.execute(select(func.count()).select_from(combined)).scalar_one()
    rows = db.execute(
        select(combined)
        .order_by(combined.c.occurred_at.desc(), combined.c.log_id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings()
    activity = [
        ProfileActivityOut(
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            title=row["title"],
            action="created" if row["action"] == "create" else "updated",
            occurred_at=row["occurred_at"],
        )
        for row in rows
    ]
    return ProfileOut(
        user=UserOut.model_validate(user),
        activity=Page(items=activity, total=total, page=page, page_size=page_size),
    )


@router.put(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    session: UserSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    user = session.user
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La password attuale non è corretta",
        )
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nuova password deve essere diversa da quella attuale",
        )

    timestamp = utcnow()
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = timestamp
    (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.id != session.id)
        .delete(synchronize_session=False)
    )
    log_security_event(
        db,
        SecurityEventType.PASSWORD_CHANGED,
        timestamp,
        actor=user,
        target=user,
        source_ip=request_ip(request),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
