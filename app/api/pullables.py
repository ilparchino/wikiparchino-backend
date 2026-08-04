from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.pagination import paginate_query
from app.database import get_db
from app.models import EntityType, Epoch, Event, Person, Place, Pullable, SocialGroup, UserAccount
from app.schemas import Page, PullableCountsOut, RecentPullableOut


router = APIRouter(prefix="/pullables", tags=["pullables"])


def pullable_count_columns():
    return (
        db_count(Person).label("people"),
        db_count(Place).label("places"),
        db_count(Epoch).label("epochs"),
        db_count(Event).label("events"),
        db_count(SocialGroup).label("groups"),
    )


def db_count(model):
    return select(func.count(model.id)).scalar_subquery()


@router.get("/counts", response_model=PullableCountsOut)
def counts(
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> PullableCountsOut:
    row = db.query(*pullable_count_columns()).one()
    return PullableCountsOut(**row._mapping)


@router.get("/recent", response_model=Page[RecentPullableOut])
def recent(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=5, ge=1, le=50),
    entity_type: EntityType | None = Query(default=None),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[RecentPullableOut]:
    type_expression = case(
        (Person.id.is_not(None), EntityType.PERSON.value),
        (Place.id.is_not(None), EntityType.PLACE.value),
        (Epoch.id.is_not(None), EntityType.EPOCH.value),
        (Event.id.is_not(None), EntityType.EVENT.value),
        else_=EntityType.GROUP.value,
    )
    title_expression = func.coalesce(
        Person.alias,
        Place.name,
        Epoch.name,
        Event.title,
        SocialGroup.name,
    )
    query = (
        db.query(
            type_expression.label("entity_type"),
            Pullable.id.label("id"),
            title_expression.label("title"),
            Pullable.created_at.label("created_at"),
        )
        .outerjoin(Person, Person.id == Pullable.id)
        .outerjoin(Place, Place.id == Pullable.id)
        .outerjoin(Epoch, Epoch.id == Pullable.id)
        .outerjoin(Event, Event.id == Pullable.id)
        .outerjoin(SocialGroup, SocialGroup.id == Pullable.id)
    )
    if entity_type is not None:
        query = query.filter(type_expression == entity_type.value)
    query = query.order_by(
        Pullable.created_at.desc(),
        Pullable.id.desc(),
        type_expression,
    )
    return paginate_query(
        query,
        page,
        page_size,
        lambda row: RecentPullableOut(**row._mapping),
    )
