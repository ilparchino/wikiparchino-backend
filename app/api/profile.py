from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import current_session, current_user
from app.api.utils import MODEL_BY_ENTITY, entity_title
from app.database import get_db
from app.models import ActivityLog, EntityType, UserAccount, UserSession
from app.schemas import PasswordChangeIn, ProfileActivityOut, ProfileOut, UserOut
from app.security import hash_password, utcnow, verify_password

router = APIRouter(prefix="/profile", tags=["profile"])
RECENT_ACTIVITY_LIMIT = 10


@router.get("", response_model=ProfileOut)
def get_profile(
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    logs = (
        db.query(ActivityLog)
        .filter(ActivityLog.actor_user_id == user.id, ActivityLog.action != "delete")
        .order_by(ActivityLog.occurred_at.desc(), ActivityLog.id.desc())
        .yield_per(100)
    )
    activity: list[ProfileActivityOut] = []
    for log in logs:
        try:
            entity_type = EntityType(log.entity_type)
        except ValueError:
            continue
        item = db.get(MODEL_BY_ENTITY[entity_type], log.entity_id)
        if item is None:
            continue
        if log.occurred_at < item.pullable.created_at:
            # Protect legacy activity created before pullable IDs became non-reusable.
            continue
        activity.append(
            ProfileActivityOut(
                entity_type=entity_type,
                entity_id=log.entity_id,
                title=entity_title(item, entity_type),
                action="created" if log.action == "create" else "updated",
                occurred_at=log.occurred_at,
            )
        )
        if len(activity) == RECENT_ACTIVITY_LIMIT:
            break
    return ProfileOut(
        user=UserOut.model_validate(user),
        recent_activity=activity,
    )


@router.put(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def change_password(
    payload: PasswordChangeIn,
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

    user.password_hash = hash_password(payload.new_password)
    user.updated_at = utcnow()
    (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.id != session.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
