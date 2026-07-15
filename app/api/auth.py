from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import current_session, current_user
from app.config import get_settings
from app.database import get_db
from app.models import UserAccount, UserSession
from app.schemas import LoginIn, LoginOut, UserOut
from app.security import expires_in_days, hash_session_token, new_session_token, utcnow, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_WINDOW = timedelta(minutes=10)
MAX_LOGIN_ATTEMPTS = 5
login_attempts: dict[str, list] = defaultdict(list)


def rate_limit_key(request: Request, username: str) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{client}:{username.lower()}"


def check_rate_limit(request: Request, username: str) -> None:
    key = rate_limit_key(request, username)
    cutoff = utcnow() - LOGIN_WINDOW
    login_attempts[key] = [attempt for attempt in login_attempts[key] if attempt > cutoff]
    if len(login_attempts[key]) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")


def record_failed_attempt(request: Request, username: str) -> None:
    login_attempts[rate_limit_key(request, username)].append(utcnow())


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> LoginOut:
    check_rate_limit(request, payload.username)
    user = db.query(UserAccount).filter(UserAccount.username == payload.username.lower()).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_failed_attempt(request, payload.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    login_attempts.pop(rate_limit_key(request, payload.username), None)
    now = utcnow()
    db.query(UserSession).filter(UserSession.expires_at <= now).delete(
        synchronize_session=False
    )
    token = new_session_token()
    expires_at = expires_in_days(get_settings().session_days)
    db.add(UserSession(user_id=user.id, token_hash=hash_session_token(token), expires_at=expires_at))
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
    session: UserSession = Depends(current_session),
    db: Session = Depends(get_db),
) -> Response:
    db.delete(session)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: UserAccount = Depends(current_user)) -> UserAccount:
    return user
