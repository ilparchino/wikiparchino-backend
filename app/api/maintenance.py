from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.maintenance import maintenance_status
from app.schemas import MaintenanceStatusOut
from app.security import utcnow


router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/status", response_model=MaintenanceStatusOut)
def get_maintenance_status(
    response: Response,
    db: Session = Depends(get_db),
) -> MaintenanceStatusOut:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return maintenance_status(db, utcnow())
