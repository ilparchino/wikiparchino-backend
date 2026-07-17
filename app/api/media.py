from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.utils import ensure_pullable, touch_pullable
from app.config import get_settings
from app.database import get_db
from app.media_storage import (
    MediaStorageError,
    commit_staged_deletion,
    commit_uploaded_file,
    resolve_media_path,
    stage_media_deletion,
)
from app.models import MediaAsset, UserAccount
from app.schemas import MediaOut

router = APIRouter(prefix="/media", tags=["media"])


@router.get("", response_model=list[MediaOut])
def list_media(
    pullable_id: int | None = Query(default=None),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[MediaAsset]:
    query = db.query(MediaAsset).order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
    if pullable_id is not None:
        query = query.filter(MediaAsset.pullable_id == pullable_id)
    return query.all()


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
def upload_media(
    file: UploadFile = File(...),
    pullable_id: int = Form(...),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> MediaAsset:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Sono supportati soltanto file immagine",
        )
    pullable = ensure_pullable(db, pullable_id)

    media_dir = get_settings().media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()[:16]
    stored_name = f"{uuid4().hex}{suffix}"
    target_path = media_dir / stored_name
    try:
        with target_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    asset = MediaAsset(
        pullable_id=pullable_id,
        filename=file.filename or stored_name,
        content_type=file.content_type,
        disk_path=str(target_path),
        created_by=user.id,
    )
    db.add(asset)
    touch_pullable(pullable, user.id)
    commit_uploaded_file(db, target_path)
    db.refresh(asset)
    return asset


@router.get("/{media_id}")
def get_media(
    media_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> FileResponse:
    asset = db.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Immagine non trovata")
    try:
        path = resolve_media_path(asset.disk_path)
    except MediaStorageError:
        touch_pullable(asset.pullable, user.id)
        db.delete(asset)
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Immagine non disponibile")
    if not path.exists():
        touch_pullable(asset.pullable, user.id)
        db.delete(asset)
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Immagine non disponibile")
    return FileResponse(path, media_type=asset.content_type, filename=asset.filename)


@router.delete(
    "/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_media(
    media_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    asset = db.get(MediaAsset, media_id)
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Immagine non trovata")
    pullable = asset.pullable
    try:
        staged_deletion = stage_media_deletion([asset])
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Non è stato possibile preparare la rimozione dell'immagine",
        ) from exc
    db.delete(asset)
    touch_pullable(pullable, user.id)
    commit_staged_deletion(db, staged_deletion)
