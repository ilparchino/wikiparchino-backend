from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import current_session, current_user
from app.config import get_settings
from app.database import get_db
from app.models import SecurityEventLog, SecurityEventType, UserAccount, UserSession
from app.schemas import LoginIn, LoginOut, UserOut
from app.security import hash_session_token, new_session_token, utcnow, verify_password
from app.security_events import log_security_event, prune_authentication_events, request_ip

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_WINDOW = timedelta(minutes=10)
MAX_LOGIN_ATTEMPTS = 5
login_attempts: dict[str, list] = defaultdict(list)


def rate_limit_key(request: Request, username: str) -> str:
    return f"{request_ip(request)}:{username.strip().lower()}"


def check_rate_limit(request: Request, username: str, now) -> bool:
    key = rate_limit_key(request, username)
    cutoff = now - LOGIN_WINDOW
    login_attempts[key] = [attempt for attempt in login_attempts[key] if attempt > cutoff]
    return len(login_attempts[key]) >= MAX_LOGIN_ATTEMPTS


def record_failed_attempt(request: Request, username: str, now) -> None:
    login_attempts[rate_limit_key(request, username)].append(now)


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    now = utcnow()
    username = payload.username.strip().lower()
    source_ip = request_ip(request)
    prune_authentication_events(db, now)
    user = db.query(UserAccount).filter(UserAccount.username == username).first()
    if check_rate_limit(request, username, now):
        previously_logged = (
            db.query(SecurityEventLog.id)
            .filter(
                SecurityEventLog.event_type == SecurityEventType.LOGIN_RATE_LIMITED.value,
                SecurityEventLog.source_ip == source_ip,
                SecurityEventLog.attempted_username == username,
                SecurityEventLog.occurred_at > now - LOGIN_WINDOW,
            )
            .first()
        )
        if previously_logged is None:
            log_security_event(
                db,
                SecurityEventType.LOGIN_RATE_LIMITED,
                now,
                target=user,
                attempted_username=username,
                source_ip=source_ip,
            )
        db.commit()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Troppi tentativi di accesso")
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_failed_attempt(request, username, now)
        log_security_event(
            db,
            SecurityEventType.LOGIN_FAILED,
            now,
            target=user,
            attempted_username=username,
            source_ip=source_ip,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenziali non valide")

    login_attempts.pop(rate_limit_key(request, username), None)
    db.query(UserSession).filter(UserSession.expires_at <= now).delete(
        synchronize_session=False
    )
    token = new_session_token()
    expires_at = now + timedelta(days=get_settings().session_days)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=expires_at,
        )
    )
    log_security_event(
        db,
        SecurityEventType.LOGIN_SUCCEEDED,
        now,
        actor=user,
        target=user,
        source_ip=source_ip,
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return LoginOut(
        access_token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def logout(
    request: Request,
    session: UserSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    log_security_event(
        db,
        SecurityEventType.LOGOUT,
        utcnow(),
        actor=session.user,
        target=session.user,
        source_ip=request_ip(request),
    )
    db.delete(session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: UserAccount = Depends(current_user)) -> UserAccount:
    return user
