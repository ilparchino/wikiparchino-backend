from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.database import get_db
from app.models import EntityType, Epoch, Event, Person, Place, UserAccount
from app.schemas import SearchResult

router = APIRouter(tags=["search"])


@router.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(min_length=1, max_length=120),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SearchResult]:
    term = f"%{q.strip()}%"
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
        db.query(Place).filter(or_(Place.name.ilike(term), Place.description.ilike(term))).limit(20).all()
    ):
        results.append(SearchResult(entity_type=EntityType.PLACE, id=place.id, title=place.name, subtitle=place.description))
    for epoch in (
        db.query(Epoch).filter(or_(Epoch.name.ilike(term), Epoch.description.ilike(term))).limit(20).all()
    ):
        results.append(SearchResult(entity_type=EntityType.EPOCH, id=epoch.id, title=epoch.name, subtitle=epoch.description))
    for event in (
        db.query(Event).filter(or_(Event.title.ilike(term), Event.description.ilike(term))).limit(20).all()
    ):
        results.append(SearchResult(entity_type=EntityType.EVENT, id=event.id, title=event.title, subtitle=event.description))
    return results[:50]
