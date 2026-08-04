from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database import get_db
from app.models import EntityType, Epoch, Event, Person, Place, SocialGroup, UserAccount
from app.schemas import EntitySearchResult, Page, SearchResult

router = APIRouter(tags=["search"])


def search_term(q: str) -> str:
    normalized = q.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Inserisci un testo da cercare",
        )
    return f"%{normalized}%"


def person_subtitle(person: Person) -> str | None:
    full_name = " ".join(part for part in (person.name, person.surname) if part)
    return full_name or person.description


@router.get("/people/search", response_model=list[EntitySearchResult])
def search_people(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    term = search_term(q)
    people = (
        db.query(Person)
        .filter(or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)))
        .order_by(func.lower(Person.alias), Person.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.alias, subtitle=person_subtitle(item)) for item in people]


@router.get("/places/search", response_model=list[EntitySearchResult])
def search_places(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    term = search_term(q)
    places = (
        db.query(Place)
        .filter(or_(Place.name.ilike(term), Place.address.ilike(term), Place.description.ilike(term)))
        .order_by(func.lower(Place.name), Place.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.name, subtitle=item.address or item.description) for item in places]


@router.get("/epochs/search", response_model=list[EntitySearchResult])
def search_epochs(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    term = search_term(q)
    epochs = (
        db.query(Epoch)
        .filter(or_(Epoch.name.ilike(term), Epoch.description.ilike(term)))
        .order_by(func.lower(Epoch.name), Epoch.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.name, subtitle=item.description) for item in epochs]


@router.get("/events/search", response_model=list[EntitySearchResult])
def search_events(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    term = search_term(q)
    events = (
        db.query(Event)
        .filter(or_(Event.title.ilike(term), Event.description.ilike(term)))
        .order_by(func.lower(Event.title), Event.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.title, subtitle=item.description) for item in events]


@router.get("/groups/search", response_model=list[EntitySearchResult])
def search_groups(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    term = search_term(q)
    groups = (
        db.query(SocialGroup)
        .filter(or_(SocialGroup.name.ilike(term), SocialGroup.description.ilike(term)))
        .order_by(func.lower(SocialGroup.name), SocialGroup.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.name, subtitle=item.description) for item in groups]


def global_search_select(entity_type: EntityType, term: str):
    if entity_type == EntityType.PERSON:
        full_name = func.nullif(
            func.trim(func.coalesce(Person.name, "") + " " + func.coalesce(Person.surname, "")),
            "",
        )
        return select(
            literal(entity_type.value).label("entity_type"),
            Person.id.label("id"),
            Person.alias.label("title"),
            func.coalesce(full_name, Person.description).label("subtitle"),
        ).where(or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)))
    if entity_type == EntityType.PLACE:
        return select(
            literal(entity_type.value).label("entity_type"),
            Place.id.label("id"),
            Place.name.label("title"),
            func.coalesce(Place.address, Place.description).label("subtitle"),
        ).where(or_(Place.name.ilike(term), Place.address.ilike(term), Place.description.ilike(term)))
    if entity_type == EntityType.EPOCH:
        return select(
            literal(entity_type.value).label("entity_type"),
            Epoch.id.label("id"),
            Epoch.name.label("title"),
            Epoch.description.label("subtitle"),
        ).where(or_(Epoch.name.ilike(term), Epoch.description.ilike(term)))
    if entity_type == EntityType.EVENT:
        return select(
            literal(entity_type.value).label("entity_type"),
            Event.id.label("id"),
            Event.title.label("title"),
            Event.description.label("subtitle"),
        ).where(or_(Event.title.ilike(term), Event.description.ilike(term)))
    return select(
        literal(entity_type.value).label("entity_type"),
        SocialGroup.id.label("id"),
        SocialGroup.name.label("title"),
        SocialGroup.description.label("subtitle"),
    ).where(or_(SocialGroup.name.ilike(term), SocialGroup.description.ilike(term)))


@router.get("/search", response_model=Page[SearchResult])
def search(
    q: str = Query(min_length=1, max_length=120),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    entity_type: EntityType | None = Query(default=None),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[SearchResult]:
    term = search_term(q)
    kinds = [entity_type] if entity_type is not None else list(EntityType)
    combined = union_all(*(global_search_select(kind, term) for kind in kinds)).subquery()
    total = db.execute(select(func.count()).select_from(combined)).scalar_one()
    rows = db.execute(
        select(combined)
        .order_by(
            combined.c.title.collate("NOCASE"),
            combined.c.entity_type,
            combined.c.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings()
    return Page(
        items=[SearchResult(**row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )
