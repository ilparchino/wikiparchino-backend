from __future__ import annotations

import json
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.media_storage import MediaStorageError, StagedMediaDeletion, stage_media_deletion
from app.models import AuditLog, EntityType, Epoch, Event, MediaAsset, Person, Place, Pullable, UserAccount, utcnow

ModelT = TypeVar("ModelT", Person, Place, Epoch, Event)

MODEL_BY_ENTITY: dict[EntityType, type[Any]] = {
    EntityType.PERSON: Person,
    EntityType.PLACE: Place,
    EntityType.EPOCH: Epoch,
    EntityType.EVENT: Event,
}


def active_or_404(db: Session, model: type[ModelT], entity_id: int) -> ModelT:
    item = db.get(model, entity_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Elemento non trovato")
    return item


def ensure_reference(db: Session, model: type[ModelT], entity_id: int, label: str) -> ModelT:
    item = db.get(model, entity_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Riferimento {label} non valido")
    return item


def ensure_pullable(db: Session, pullable_id: int) -> Pullable:
    pullable = db.get(Pullable, pullable_id)
    if pullable is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Elemento collegato non valido")
    return pullable


def create_pullable(db: Session, rarity: float, user_id: int) -> Pullable:
    timestamp = utcnow()
    pullable = Pullable(
        rarity=rarity,
        created_at=timestamp,
        updated_at=timestamp,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(pullable)
    db.flush()
    return pullable


def update_rarity(item: Any, rarity: float) -> None:
    item.pullable.rarity = rarity


def touch_pullable(pullable: Pullable, user_id: int) -> None:
    pullable.updated_at = utcnow()
    pullable.updated_by = user_id


def delete_pullable(db: Session, entity_id: int) -> StagedMediaDeletion:
    pullable = db.get(Pullable, entity_id)
    if pullable is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Elemento non trovato")
    assets = db.query(MediaAsset).filter(MediaAsset.pullable_id == entity_id).all()
    try:
        staged_deletion = stage_media_deletion(assets)
    except MediaStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Non è stato possibile preparare la rimozione delle immagini",
        ) from exc
    db.delete(pullable)
    return staged_deletion


def audit(db: Session, actor: UserAccount, entity_type: str, entity_id: int, action: str, payload: Any = None) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            payload_json=json.dumps(payload, default=str, ensure_ascii=False) if payload is not None else None,
        )
    )


def entity_title(item: Any, entity_type: EntityType) -> str:
    if entity_type == EntityType.PERSON:
        return item.alias
    if entity_type in {EntityType.PLACE, EntityType.EPOCH}:
        return item.name
    return item.title
