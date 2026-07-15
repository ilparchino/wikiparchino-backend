from __future__ import annotations

from datetime import timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserAccount, UserSession
from app.security import hash_session_token, utcnow

bearer_scheme = HTTPBearer(auto_error=False)
AUTHENTICATE_HEADER = {"WWW-Authenticate": "Bearer"}


def bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers=AUTHENTICATE_HEADER,
        )
    return credentials.credentials


def current_session(
    token: str = Depends(bearer_token),
    db: Session = Depends(get_db),
) -> UserSession:
    token_hash = hash_session_token(token)
    session = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
            headers=AUTHENTICATE_HEADER,
        )
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= utcnow():
        db.delete(session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
            headers=AUTHENTICATE_HEADER,
        )
    if not session.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive account",
            headers=AUTHENTICATE_HEADER,
        )
    return session


def current_user(
    session: UserSession = Depends(current_session),
) -> UserAccount:
    return session.user
