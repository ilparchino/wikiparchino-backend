from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database import get_db
from app.models import EntityType, Epoch, Event, Person, Place, SocialGroup, UserAccount
from app.schemas import EntitySearchResult, SearchResult

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


@router.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(min_length=1, max_length=120),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SearchResult]:
    term = search_term(q)
    results: list[SearchResult] = []
    for person in (
        db.query(Person)
        .filter(
            or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)),
        )
        .limit(20)
        .all()
    ):
        results.append(SearchResult(entity_type=EntityType.PERSON, id=person.id, title=person.alias, subtitle=person.description))
    for place in (
        db.query(Place)
        .filter(
            or_(
                Place.name.ilike(term),
                Place.address.ilike(term),
                Place.description.ilike(term),
            )
        )
        .limit(20)
        .all()
    ):
        results.append(
            SearchResult(
                entity_type=EntityType.PLACE,
                id=place.id,
                title=place.name,
                subtitle=place.address or place.description,
            )
        )
    for epoch in (
        db.query(Epoch).filter(or_(Epoch.name.ilike(term), Epoch.description.ilike(term))).limit(20).all()
    ):
        results.append(SearchResult(entity_type=EntityType.EPOCH, id=epoch.id, title=epoch.name, subtitle=epoch.description))
    for event in (
        db.query(Event).filter(or_(Event.title.ilike(term), Event.description.ilike(term))).limit(20).all()
    ):
        results.append(SearchResult(entity_type=EntityType.EVENT, id=event.id, title=event.title, subtitle=event.description))
    for group in (
        db.query(SocialGroup)
        .filter(or_(SocialGroup.name.ilike(term), SocialGroup.description.ilike(term)))
        .limit(20)
        .all()
    ):
        results.append(
            SearchResult(
                entity_type=EntityType.GROUP,
                id=group.id,
                title=group.name,
                subtitle=group.description,
            )
        )
    return results[:50]
