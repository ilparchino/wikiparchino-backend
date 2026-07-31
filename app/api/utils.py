from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.media_storage import MediaStorageError, StagedMediaDeletion, stage_media_deletion
from app.models import ActivityAction, ActivityLog, EntityType, Epoch, Event, MediaAsset, Person, Place, Pullable, SocialGroup, UserAccount

ModelT = TypeVar("ModelT", Person, Place, Epoch, Event, SocialGroup)

MODEL_BY_ENTITY: dict[EntityType, type[Any]] = {
    EntityType.PERSON: Person,
    EntityType.PLACE: Place,
    EntityType.EPOCH: Epoch,
    EntityType.EVENT: Event,
    EntityType.GROUP: SocialGroup,
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


def create_pullable(
    db: Session,
    rarity: float,
    user_id: int,
    timestamp: datetime,
) -> Pullable:
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


def touch_pullable(pullable: Pullable, user_id: int, timestamp: datetime) -> None:
    pullable.updated_at = timestamp
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


def log_activity(
    db: Session,
    actor: UserAccount,
    entity_type: EntityType,
    entity_id: int,
    action: ActivityAction,
    occurred_at: datetime,
    payload: Any = None,
) -> None:
    db.add(
        ActivityLog(
            actor_user_id=actor.id,
            entity_type=entity_type.value,
            entity_id=entity_id,
            action=action.value,
            payload_json=json.dumps(payload, default=str, ensure_ascii=False) if payload is not None else None,
            occurred_at=occurred_at,
        )
    )


def entity_title(item: Any, entity_type: EntityType) -> str:
    if entity_type == EntityType.PERSON:
        return item.alias
    if entity_type in {EntityType.PLACE, EntityType.EPOCH, EntityType.GROUP}:
        return item.name
    return item.title


def pullable_entity_type(db: Session, pullable_id: int) -> EntityType:
    for entity_type, model in MODEL_BY_ENTITY.items():
        if db.get(model, pullable_id) is not None:
            return entity_type
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Elemento collegato non valido",
    )
