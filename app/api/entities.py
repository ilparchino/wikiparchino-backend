from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import current_user
from app.api.pagination import paginate_query
from app.api.utils import (
    active_or_404,
    create_pullable,
    delete_pullable,
    ensure_reference,
    log_activity,
    touch_pullable,
    update_rarity,
)
from app.database import get_db
from app.media_storage import commit_staged_deletion
from app.models import (
    ActivityAction,
    Connotation,
    EntityType,
    Epoch,
    Event,
    Person,
    Place,
    Pullable,
    Sex,
    SocialGroup,
    SocialGroupEpoch,
    SocialGroupPerson,
    UserAccount,
    utcnow,
)
from app.partial_dates import PartialDate, event_epoch_conflict
from app.schemas import (
    EpochCreate,
    EpochOut,
    EpochUpdate,
    EventCreate,
    EventOut,
    EventUpdate,
    GroupCreate,
    GroupOut,
    GroupSummaryOut,
    GroupUpdate,
    Page,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    PlaceCreate,
    PlaceOut,
    PlaceUpdate,
)

router = APIRouter(tags=["entities"])

SortOrder = Literal["asc", "desc"]


def text_term(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return f"%{normalized}%" if normalized else None


def ordered(expression, order: SortOrder, *, nulls_last: bool = False):
    clause = expression.asc() if order == "asc" else expression.desc()
    return clause.nullslast() if nulls_last else clause


def event_date_key():
    return case(
        (Event.year.is_(None), None),
        else_=(
            Event.year * 10000
            + func.coalesce(Event.month, 1) * 100
            + func.coalesce(Event.day, 1)
        ),
    )


def epoch_start_key():
    return case(
        (Epoch.start_year.is_(None), None),
        else_=(
            Epoch.start_year * 10000
            + func.coalesce(Epoch.start_month, 1) * 100
            + func.coalesce(Epoch.start_day, 1)
        ),
    )


def epoch_end_key():
    leap_february = case(
        (
            or_(
                Epoch.end_year % 400 == 0,
                (Epoch.end_year % 4 == 0) & (Epoch.end_year % 100 != 0),
            ),
            29,
        ),
        else_=28,
    )
    last_day = case(
        (Epoch.end_day.is_not(None), Epoch.end_day),
        (Epoch.end_month.is_(None), 31),
        (Epoch.end_month == 2, leap_february),
        (Epoch.end_month.in_((4, 6, 9, 11)), 30),
        else_=31,
    )
    return case(
        (Epoch.end_year.is_(None), None),
        else_=(
            Epoch.end_year * 10000
            + func.coalesce(Epoch.end_month, 12) * 100
            + last_day
        ),
    )


def epoch_start(epoch: Epoch | EpochCreate | EpochUpdate) -> PartialDate:
    return PartialDate(epoch.start_year, epoch.start_month, epoch.start_day)


def epoch_end(epoch: Epoch | EpochCreate | EpochUpdate) -> PartialDate:
    return PartialDate(epoch.end_year, epoch.end_month, epoch.end_day)


def event_date(event: Event | EventCreate | EventUpdate) -> PartialDate:
    return PartialDate(event.year, event.month, event.day)


def validate_event_epoch(
    event: Event | EventCreate | EventUpdate,
    epoch: Epoch,
) -> None:
    conflict = event_epoch_conflict(
        event_date(event),
        epoch_start(epoch),
        epoch_end(epoch),
    )
    if conflict == "before":
        detail = "La data dell'evento è precedente all'inizio dell'epoca selezionata"
    elif conflict == "after":
        detail = "La data dell'evento è successiva alla fine dell'epoca selezionata"
    else:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def split_rarity(payload) -> tuple[dict, float]:
    data = payload.model_dump()
    rarity = data.pop("rarity")
    return data, rarity


@router.get("/people", response_model=Page[PersonOut])
def list_people(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=18, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sex: Sex | None = Query(default=None),
    connotation: Connotation | None = Query(default=None),
    sort: Literal["alias", "name", "surname", "created_at", "updated_at", "rarity"] = "alias",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[PersonOut]:
    query = db.query(Person).join(Pullable).options(joinedload(Person.pullable))
    term = text_term(q)
    if term:
        query = query.filter(or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)))
    if sex:
        query = query.filter(Person.sex == sex.value)
    if connotation:
        query = query.filter(Person.connotation == connotation.value)
    expressions = {
        "alias": Person.alias.collate("NOCASE"),
        "name": Person.name.collate("NOCASE"),
        "surname": Person.surname.collate("NOCASE"),
        "created_at": Pullable.created_at,
        "updated_at": Pullable.updated_at,
        "rarity": Pullable.rarity,
    }
    query = query.order_by(ordered(expressions[sort], order, nulls_last=sort in {"name", "surname"}), ordered(Person.id, order))
    return paginate_query(query, page, page_size)


@router.post("/people", response_model=PersonOut, status_code=status.HTTP_201_CREATED)
def create_person(payload: PersonCreate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Person:
    data, rarity = split_rarity(payload)
    timestamp = utcnow()
    pullable = create_pullable(db, rarity, user.id, timestamp)
    item = Person(id=pullable.id, **data)
    db.add(item)
    log_activity(db, user, EntityType.PERSON, item.id, ActivityAction.CREATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.get("/people/{person_id}", response_model=PersonOut)
def get_person(person_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Person:
    return active_or_404(db, Person, person_id)


@router.put("/people/{person_id}", response_model=PersonOut)
def update_person(
    person_id: int, payload: PersonUpdate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> Person:
    item = active_or_404(db, Person, person_id)
    data, rarity = split_rarity(payload)
    for key, value in data.items():
        setattr(item, key, value)
    update_rarity(item, rarity)
    timestamp = utcnow()
    touch_pullable(item.pullable, user.id, timestamp)
    log_activity(db, user, EntityType.PERSON, item.id, ActivityAction.UPDATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.delete("/people/{person_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_person(person_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> None:
    item = active_or_404(db, Person, person_id)
    log_activity(db, user, EntityType.PERSON, person_id, ActivityAction.DELETE, utcnow(), {"title": item.alias})
    staged_deletion = delete_pullable(db, person_id)
    commit_staged_deletion(db, staged_deletion)


@router.get("/places", response_model=Page[PlaceOut])
def list_places(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=18, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sort: Literal["name", "address", "created_at", "updated_at", "rarity"] = "name",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[PlaceOut]:
    query = db.query(Place).join(Pullable).options(joinedload(Place.pullable))
    term = text_term(q)
    if term:
        query = query.filter(or_(Place.name.ilike(term), Place.address.ilike(term), Place.description.ilike(term)))
    expressions = {
        "name": Place.name.collate("NOCASE"),
        "address": Place.address.collate("NOCASE"),
        "created_at": Pullable.created_at,
        "updated_at": Pullable.updated_at,
        "rarity": Pullable.rarity,
    }
    query = query.order_by(ordered(expressions[sort], order, nulls_last=sort == "address"), ordered(Place.id, order))
    return paginate_query(query, page, page_size)


@router.post("/places", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
def create_place(payload: PlaceCreate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Place:
    data, rarity = split_rarity(payload)
    timestamp = utcnow()
    pullable = create_pullable(db, rarity, user.id, timestamp)
    item = Place(id=pullable.id, **data)
    db.add(item)
    log_activity(db, user, EntityType.PLACE, item.id, ActivityAction.CREATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.get("/places/{place_id}", response_model=PlaceOut)
def get_place(place_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Place:
    return active_or_404(db, Place, place_id)


@router.put("/places/{place_id}", response_model=PlaceOut)
def update_place(
    place_id: int, payload: PlaceUpdate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> Place:
    item = active_or_404(db, Place, place_id)
    data, rarity = split_rarity(payload)
    for key, value in data.items():
        setattr(item, key, value)
    update_rarity(item, rarity)
    timestamp = utcnow()
    touch_pullable(item.pullable, user.id, timestamp)
    log_activity(db, user, EntityType.PLACE, item.id, ActivityAction.UPDATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.delete("/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_place(place_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> None:
    item = active_or_404(db, Place, place_id)
    if db.query(Event).filter(Event.place_id == place_id).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Il luogo è usato da uno o più eventi")
    log_activity(db, user, EntityType.PLACE, place_id, ActivityAction.DELETE, utcnow(), {"title": item.name})
    staged_deletion = delete_pullable(db, place_id)
    commit_staged_deletion(db, staged_deletion)


@router.get("/epochs", response_model=Page[EpochOut])
def list_epochs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=18, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sort: Literal["name", "start_date", "end_date", "created_at", "updated_at", "rarity"] = "name",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[EpochOut]:
    query = db.query(Epoch).join(Pullable).options(joinedload(Epoch.pullable))
    term = text_term(q)
    if term:
        query = query.filter(or_(Epoch.name.ilike(term), Epoch.description.ilike(term)))
    expressions = {
        "name": Epoch.name.collate("NOCASE"),
        "start_date": epoch_start_key(),
        "end_date": epoch_end_key(),
        "created_at": Pullable.created_at,
        "updated_at": Pullable.updated_at,
        "rarity": Pullable.rarity,
    }
    query = query.order_by(ordered(expressions[sort], order, nulls_last=sort in {"start_date", "end_date"}), ordered(Epoch.id, order))
    return paginate_query(query, page, page_size)


@router.post("/epochs", response_model=EpochOut, status_code=status.HTTP_201_CREATED)
def create_epoch(payload: EpochCreate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Epoch:
    data, rarity = split_rarity(payload)
    timestamp = utcnow()
    pullable = create_pullable(db, rarity, user.id, timestamp)
    item = Epoch(id=pullable.id, **data)
    db.add(item)
    log_activity(db, user, EntityType.EPOCH, item.id, ActivityAction.CREATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.get("/epochs/{epoch_id}", response_model=EpochOut)
def get_epoch(epoch_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Epoch:
    return active_or_404(db, Epoch, epoch_id)


@router.put("/epochs/{epoch_id}", response_model=EpochOut)
def update_epoch(
    epoch_id: int, payload: EpochUpdate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> Epoch:
    item = active_or_404(db, Epoch, epoch_id)
    incompatible = [
        event.title
        for event in db.query(Event).filter(Event.epoch_id == epoch_id).all()
        if event_epoch_conflict(
            event_date(event),
            epoch_start(payload),
            epoch_end(payload),
        )
        is not None
    ]
    if incompatible:
        preview = ", ".join(incompatible[:5])
        if len(incompatible) > 5:
            preview += f" e altri {len(incompatible) - 5}"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Le nuove date dell'epoca escluderebbero eventi già collegati: "
                f"{preview}"
            ),
        )
    data, rarity = split_rarity(payload)
    for key, value in data.items():
        setattr(item, key, value)
    update_rarity(item, rarity)
    timestamp = utcnow()
    touch_pullable(item.pullable, user.id, timestamp)
    log_activity(db, user, EntityType.EPOCH, item.id, ActivityAction.UPDATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.delete("/epochs/{epoch_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_epoch(epoch_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> None:
    item = active_or_404(db, Epoch, epoch_id)
    if db.query(Event).filter(Event.epoch_id == epoch_id).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="L'epoca è usata da uno o più eventi")
    log_activity(db, user, EntityType.EPOCH, epoch_id, ActivityAction.DELETE, utcnow(), {"title": item.name})
    staged_deletion = delete_pullable(db, epoch_id)
    commit_staged_deletion(db, staged_deletion)


@router.get("/events", response_model=Page[EventOut])
def list_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=18, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    place_id: int | None = Query(default=None, ge=1),
    epoch_id: int | None = Query(default=None, ge=1),
    year: int | None = Query(default=None, ge=1900),
    sort: Literal["title", "date", "created_at", "updated_at", "rarity"] = "date",
    order: SortOrder = "desc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[EventOut]:
    query = (
        db.query(Event)
        .join(Pullable, Pullable.id == Event.id)
        .join(Place, Place.id == Event.place_id)
        .join(Epoch, Epoch.id == Event.epoch_id)
        .options(joinedload(Event.pullable), joinedload(Event.place).joinedload(Place.pullable), joinedload(Event.epoch).joinedload(Epoch.pullable))
    )
    term = text_term(q)
    if term:
        query = query.filter(or_(Event.title.ilike(term), Event.description.ilike(term), Place.name.ilike(term), Epoch.name.ilike(term)))
    if place_id:
        query = query.filter(Event.place_id == place_id)
    if epoch_id:
        query = query.filter(Event.epoch_id == epoch_id)
    if year:
        query = query.filter(Event.year == year)
    expressions = {
        "title": Event.title.collate("NOCASE"),
        "date": event_date_key(),
        "created_at": Pullable.created_at,
        "updated_at": Pullable.updated_at,
        "rarity": Pullable.rarity,
    }
    query = query.order_by(ordered(expressions[sort], order, nulls_last=sort == "date"), ordered(Event.id, order))
    return paginate_query(query, page, page_size)


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Event:
    ensure_reference(db, Place, payload.place_id, "luogo")
    epoch = ensure_reference(db, Epoch, payload.epoch_id, "epoca")
    validate_event_epoch(payload, epoch)
    data, rarity = split_rarity(payload)
    timestamp = utcnow()
    pullable = create_pullable(db, rarity, user.id, timestamp)
    item = Event(id=pullable.id, **data)
    db.add(item)
    log_activity(db, user, EntityType.EVENT, item.id, ActivityAction.CREATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Event:
    return active_or_404(db, Event, event_id)


@router.put("/events/{event_id}", response_model=EventOut)
def update_event(
    event_id: int, payload: EventUpdate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> Event:
    ensure_reference(db, Place, payload.place_id, "luogo")
    epoch = ensure_reference(db, Epoch, payload.epoch_id, "epoca")
    validate_event_epoch(payload, epoch)
    item = active_or_404(db, Event, event_id)
    data, rarity = split_rarity(payload)
    for key, value in data.items():
        setattr(item, key, value)
    update_rarity(item, rarity)
    timestamp = utcnow()
    touch_pullable(item.pullable, user.id, timestamp)
    log_activity(db, user, EntityType.EVENT, item.id, ActivityAction.UPDATE, timestamp, payload.model_dump())
    db.commit()
    db.refresh(item)
    return item


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
def delete_event(event_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> None:
    item = active_or_404(db, Event, event_id)
    log_activity(db, user, EntityType.EVENT, event_id, ActivityAction.DELETE, utcnow(), {"title": item.title})
    staged_deletion = delete_pullable(db, event_id)
    commit_staged_deletion(db, staged_deletion)


@router.get("/groups", response_model=Page[GroupSummaryOut])
def list_groups(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=18, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sort: Literal["name", "people_count", "epoch_count", "created_at", "updated_at", "rarity"] = "name",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[GroupSummaryOut]:
    people_counts = (
        select(
            SocialGroupPerson.group_id.label("group_id"),
            func.count(SocialGroupPerson.person_id).label("count"),
        )
        .group_by(SocialGroupPerson.group_id)
        .subquery()
    )
    epoch_counts = (
        select(
            SocialGroupEpoch.group_id.label("group_id"),
            func.count(SocialGroupEpoch.epoch_id).label("count"),
        )
        .group_by(SocialGroupEpoch.group_id)
        .subquery()
    )
    people_count = func.coalesce(people_counts.c.count, 0)
    epoch_count = func.coalesce(epoch_counts.c.count, 0)
    query = (
        db.query(
            SocialGroup,
            people_count,
            epoch_count,
        )
        .join(Pullable, Pullable.id == SocialGroup.id)
        .outerjoin(people_counts, people_counts.c.group_id == SocialGroup.id)
        .outerjoin(epoch_counts, epoch_counts.c.group_id == SocialGroup.id)
        .options(joinedload(SocialGroup.pullable))
    )
    term = text_term(q)
    if term:
        query = query.filter(or_(SocialGroup.name.ilike(term), SocialGroup.description.ilike(term)))
    expressions = {
        "name": SocialGroup.name.collate("NOCASE"),
        "people_count": people_count,
        "epoch_count": epoch_count,
        "created_at": Pullable.created_at,
        "updated_at": Pullable.updated_at,
        "rarity": Pullable.rarity,
    }
    query = query.order_by(ordered(expressions[sort], order), ordered(SocialGroup.id, order))
    return paginate_query(
        query,
        page,
        page_size,
        lambda row: GroupSummaryOut(
            **GroupOut.model_validate(row[0]).model_dump(),
            people_count=row[1],
            epoch_count=row[2],
        ),
    )


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: GroupCreate,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> SocialGroup:
    data, rarity = split_rarity(payload)
    timestamp = utcnow()
    pullable = create_pullable(db, rarity, user.id, timestamp)
    item = SocialGroup(id=pullable.id, **data)
    db.add(item)
    log_activity(
        db,
        user,
        EntityType.GROUP,
        item.id,
        ActivityAction.CREATE,
        timestamp,
        payload.model_dump(),
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/groups/{group_id}", response_model=GroupSummaryOut)
def get_group(
    group_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> GroupSummaryOut:
    group = active_or_404(db, SocialGroup, group_id)
    return GroupSummaryOut(
        **GroupOut.model_validate(group).model_dump(),
        people_count=db.query(SocialGroupPerson).filter(SocialGroupPerson.group_id == group_id).count(),
        epoch_count=db.query(SocialGroupEpoch).filter(SocialGroupEpoch.group_id == group_id).count(),
    )


@router.put("/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: int,
    payload: GroupUpdate,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> SocialGroup:
    item = active_or_404(db, SocialGroup, group_id)
    data, rarity = split_rarity(payload)
    for key, value in data.items():
        setattr(item, key, value)
    update_rarity(item, rarity)
    timestamp = utcnow()
    touch_pullable(item.pullable, user.id, timestamp)
    log_activity(
        db,
        user,
        EntityType.GROUP,
        item.id,
        ActivityAction.UPDATE,
        timestamp,
        payload.model_dump(),
    )
    db.commit()
    db.refresh(item)
    return item


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
def delete_group(
    group_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    item = active_or_404(db, SocialGroup, group_id)
    log_activity(
        db,
        user,
        EntityType.GROUP,
        group_id,
        ActivityAction.DELETE,
        utcnow(),
        {"title": item.name},
    )
    staged_deletion = delete_pullable(db, group_id)
    commit_staged_deletion(db, staged_deletion)
