from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import random

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, literal, select, union_all
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database import get_db
from app.models import EntityType, Epoch, Event, Person, Place, Pullable, UserAccount
from app.schemas import PullResult

router = APIRouter(prefix="/pulls", tags=["pulls"])


@dataclass(frozen=True)
class PullCandidate:
    entity_type: EntityType
    id: int
    title: str
    rarity: float


def candidate_select(entity_type: EntityType) -> Select:
    if entity_type == EntityType.PERSON:
        return select(
            literal(EntityType.PERSON.value).label("entity_type"),
            Person.id.label("id"),
            Person.alias.label("title"),
            Pullable.rarity.label("rarity"),
        ).join(Pullable, Pullable.id == Person.id)
    if entity_type == EntityType.PLACE:
        return select(
            literal(EntityType.PLACE.value).label("entity_type"),
            Place.id.label("id"),
            Place.name.label("title"),
            Pullable.rarity.label("rarity"),
        ).join(Pullable, Pullable.id == Place.id)
    if entity_type == EntityType.EPOCH:
        return select(
            literal(EntityType.EPOCH.value).label("entity_type"),
            Epoch.id.label("id"),
            Epoch.name.label("title"),
            Pullable.rarity.label("rarity"),
        ).join(Pullable, Pullable.id == Epoch.id)
    return select(
        literal(EntityType.EVENT.value).label("entity_type"),
        Event.id.label("id"),
        Event.title.label("title"),
        Pullable.rarity.label("rarity"),
    ).join(Pullable, Pullable.id == Event.id)


def active_pullables(db: Session, entity_type: EntityType | None = None) -> list[PullCandidate]:
    entity_types = [entity_type] if entity_type is not None else list(EntityType)
    selects = [candidate_select(kind).where(Pullable.rarity > 0) for kind in entity_types]
    statement = union_all(*selects)
    rows = db.execute(statement).mappings().all()
    return [
        PullCandidate(
            entity_type=EntityType(row["entity_type"]),
            id=row["id"],
            title=row["title"],
            rarity=row["rarity"],
        )
        for row in rows
    ]


def weighted_pick(candidates: list[PullCandidate], rng: random.Random) -> PullCandidate:
    if not candidates:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pullable items")
    total = sum(candidate.rarity for candidate in candidates)
    threshold = rng.uniform(0, total)
    cursor = 0.0
    for candidate in candidates:
        cursor += candidate.rarity
        if cursor >= threshold:
            return candidate
    return candidates[-1]


def to_result(candidate: PullCandidate, mode: str) -> PullResult:
    return PullResult(
        entity_type=candidate.entity_type,
        id=candidate.id,
        title=candidate.title,
        rarity=candidate.rarity,
        mode=mode,
    )


@router.get("/random", response_model=PullResult)
def random_pull(
    entity_type: EntityType | None = Query(default=None),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> PullResult:
    return to_result(weighted_pick(active_pullables(db, entity_type), random.Random()), "random")


@router.get("/daily", response_model=PullResult)
def daily_pull(
    entity_type: EntityType | None = Query(default=None),
    day: date = Query(default_factory=date.today),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> PullResult:
    seed_input = f"{day.isoformat()}:{entity_type.value if entity_type else 'all'}"
    seed = int(hashlib.sha256(seed_input.encode("utf-8")).hexdigest(), 16)
    return to_result(weighted_pick(active_pullables(db, entity_type), random.Random(seed)), "daily")
