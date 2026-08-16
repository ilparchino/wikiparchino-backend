from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Query as SqlQuery
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.entities import SortOrder, epoch_end_key, epoch_start_key, event_date_ordering, ordered
from app.api.search import person_subtitle, search_term
from app.api.utils import active_or_404, log_activity, touch_pullable
from app.database import get_db
from app.models import (
    ActivityAction,
    Connotation,
    EntityType,
    Epoch,
    Event,
    Person,
    PersonEvent,
    PersonPlace,
    Place,
    Sex,
    SocialGroup,
    SocialGroupEpoch,
    SocialGroupPerson,
    UserAccount,
    utcnow,
)
from app.schemas import (
    EntitySearchResult,
    EventParticipantChangeset,
    EventParticipantOut,
    MembershipChangeset,
    Page,
    PersonEventOut,
    PersonPlaceChangeset,
    PersonPlaceOut,
    PlacePersonChangeset,
    PlacePersonOut,
    RelatedEpochOut,
    RelatedEventOut,
    RelatedGroupOut,
    RelatedPersonOut,
    RelatedPlaceOut,
    RelationshipChangeOut,
)

router = APIRouter(tags=["relationships"])

ModelT = TypeVar("ModelT")
RelationshipSort = Literal["alias", "role"]


def relationship_term(q: str | None) -> str | None:
    normalized = q.strip() if q else ""
    return f"%{normalized}%" if normalized else None


def page_ids(query: SqlQuery, page: int, page_size: int) -> tuple[list[int], int]:
    total = query.order_by(None).count()
    ids = [row[0] for row in query.offset((page - 1) * page_size).limit(page_size).all()]
    return ids, total


def load_by_ids(db: Session, model: type[ModelT], ids: Sequence[int]) -> dict[int, ModelT]:
    if not ids:
        return {}
    return {item.id: item for item in db.query(model).filter(model.id.in_(ids)).all()}


def page(items: list[Any], total: int, current: int, size: int) -> Page[Any]:
    return Page(items=items, total=total, page=current, page_size=size)


def related_event(event: Event, places: dict[int, Place], epochs: dict[int, Epoch]) -> RelatedEventOut:
    return RelatedEventOut(
        id=event.id,
        title=event.title,
        place_id=event.place_id,
        epoch_id=event.epoch_id,
        year=event.year,
        month=event.month,
        day=event.day,
        place_name=places[event.place_id].name,
        epoch_name=epochs[event.epoch_id].name,
    )


def conflict(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def ensure_targets(db: Session, model: type[ModelT], ids: set[int], label: str) -> dict[int, ModelT]:
    targets = load_by_ids(db, model, sorted(ids))
    missing = sorted(ids - targets.keys())
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} inesistenti: {', '.join(map(str, missing))}",
        )
    return targets


def validate_state(
    existing: dict[int, Any], add_ids: set[int], update_ids: set[int], remove_ids: set[int]
) -> None:
    already_linked = sorted(add_ids & existing.keys())
    missing_updates = sorted(update_ids - existing.keys())
    missing_removals = sorted(remove_ids - existing.keys())
    if already_linked:
        conflict(f"Collegamenti già esistenti: {', '.join(map(str, already_linked))}")
    if missing_updates:
        conflict(f"Collegamenti da aggiornare non esistenti: {', '.join(map(str, missing_updates))}")
    if missing_removals:
        conflict(f"Collegamenti da rimuovere non esistenti: {', '.join(map(str, missing_removals))}")


@router.get("/events/{event_id}/participants/candidates", response_model=list[EntitySearchResult])
def event_participant_candidates(
    event_id: int,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    active_or_404(db, Event, event_id)
    term = search_term(q)
    people = (
        db.query(Person)
        .filter(
            or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)),
            ~db.query(PersonEvent).filter(PersonEvent.event_id == event_id, PersonEvent.person_id == Person.id).exists(),
        )
        .order_by(Person.alias.collate("NOCASE"), Person.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.alias, subtitle=person_subtitle(item)) for item in people]


@router.get("/people/{person_id}/places/candidates", response_model=list[EntitySearchResult])
def person_place_candidates(
    person_id: int,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    active_or_404(db, Person, person_id)
    term = search_term(q)
    places = (
        db.query(Place)
        .filter(
            or_(Place.name.ilike(term), Place.address.ilike(term), Place.description.ilike(term)),
            ~db.query(PersonPlace).filter(PersonPlace.person_id == person_id, PersonPlace.place_id == Place.id).exists(),
        )
        .order_by(Place.name.collate("NOCASE"), Place.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.name, subtitle=item.address or item.description) for item in places]


@router.get("/places/{place_id}/people/candidates", response_model=list[EntitySearchResult])
def place_people_candidates(
    place_id: int,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    active_or_404(db, Place, place_id)
    term = search_term(q)
    people = (
        db.query(Person)
        .filter(
            or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)),
            ~db.query(PersonPlace).filter(PersonPlace.place_id == place_id, PersonPlace.person_id == Person.id).exists(),
        )
        .order_by(Person.alias.collate("NOCASE"), Person.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.alias, subtitle=person_subtitle(item)) for item in people]


@router.get("/groups/{group_id}/people/candidates", response_model=list[EntitySearchResult])
def group_people_candidates(
    group_id: int,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    active_or_404(db, SocialGroup, group_id)
    term = search_term(q)
    people = (
        db.query(Person)
        .filter(
            or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)),
            ~db.query(SocialGroupPerson).filter(SocialGroupPerson.group_id == group_id, SocialGroupPerson.person_id == Person.id).exists(),
        )
        .order_by(Person.alias.collate("NOCASE"), Person.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.alias, subtitle=person_subtitle(item)) for item in people]


@router.get("/groups/{group_id}/epochs/candidates", response_model=list[EntitySearchResult])
def group_epoch_candidates(
    group_id: int,
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[EntitySearchResult]:
    active_or_404(db, SocialGroup, group_id)
    term = search_term(q)
    epochs = (
        db.query(Epoch)
        .filter(
            or_(Epoch.name.ilike(term), Epoch.description.ilike(term)),
            ~db.query(SocialGroupEpoch).filter(SocialGroupEpoch.group_id == group_id, SocialGroupEpoch.epoch_id == Epoch.id).exists(),
        )
        .order_by(Epoch.name.collate("NOCASE"), Epoch.id)
        .limit(limit)
        .all()
    )
    return [EntitySearchResult(id=item.id, title=item.name, subtitle=item.description) for item in epochs]


@router.get("/events/{event_id}/participants", response_model=Page[EventParticipantOut])
def list_event_participants(
    event_id: int,
    page_number: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sex: Sex | None = None,
    connotation: Connotation | None = None,
    sort: RelationshipSort = "alias",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[EventParticipantOut]:
    active_or_404(db, Event, event_id)
    query = db.query(Person.id).join(PersonEvent, PersonEvent.person_id == Person.id).filter(PersonEvent.event_id == event_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term), PersonEvent.role.ilike(term), PersonEvent.motivation.ilike(term)))
    if sex:
        query = query.filter(Person.sex == sex.value)
    if connotation:
        query = query.filter(Person.connotation == connotation.value)
    sort_expression = Person.alias.collate("NOCASE") if sort == "alias" else PersonEvent.role.collate("NOCASE")
    query = query.order_by(ordered(sort_expression, order, nulls_last=sort == "role"), ordered(Person.id, order))
    ids, total = page_ids(query, page_number, page_size)
    people = load_by_ids(db, Person, ids)
    links = {item.person_id: item for item in db.query(PersonEvent).filter(PersonEvent.event_id == event_id, PersonEvent.person_id.in_(ids)).all()} if ids else {}
    items = [EventParticipantOut(event_id=event_id, person_id=person_id, role=links[person_id].role, motivation=links[person_id].motivation, person=RelatedPersonOut.model_validate(people[person_id])) for person_id in ids]
    return page(items, total, page_number, page_size)


@router.get("/people/{person_id}/events", response_model=Page[PersonEventOut])
def list_person_events(
    person_id: int,
    page_number: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    place_id: int | None = Query(default=None, ge=1),
    epoch_id: int | None = Query(default=None, ge=1),
    year: int | None = Query(default=None, ge=1900),
    sort: Literal["date", "title", "role"] = "date",
    order: SortOrder = "desc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[PersonEventOut]:
    active_or_404(db, Person, person_id)
    query = db.query(Event.id).join(PersonEvent, PersonEvent.event_id == Event.id).join(Place, Event.place_id == Place.id).join(Epoch, Event.epoch_id == Epoch.id).filter(PersonEvent.person_id == person_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(Event.title.ilike(term), Event.description.ilike(term), Place.name.ilike(term), Place.address.ilike(term), Epoch.name.ilike(term), PersonEvent.role.ilike(term), PersonEvent.motivation.ilike(term)))
    if place_id is not None:
        query = query.filter(Event.place_id == place_id)
    if epoch_id is not None:
        query = query.filter(Event.epoch_id == epoch_id)
    if year is not None:
        query = query.filter(Event.year == year)
    if sort == "date":
        query = query.order_by(*event_date_ordering(order))
    else:
        expression = Event.title.collate("NOCASE") if sort == "title" else PersonEvent.role.collate("NOCASE")
        query = query.order_by(ordered(expression, order, nulls_last=sort == "role"), ordered(Event.id, order))
    ids, total = page_ids(query, page_number, page_size)
    events = load_by_ids(db, Event, ids)
    places = load_by_ids(db, Place, {events[item].place_id for item in ids})
    epochs = load_by_ids(db, Epoch, {events[item].epoch_id for item in ids})
    links = {item.event_id: item for item in db.query(PersonEvent).filter(PersonEvent.person_id == person_id, PersonEvent.event_id.in_(ids)).all()} if ids else {}
    items = [PersonEventOut(person_id=person_id, event_id=event_id, role=links[event_id].role, motivation=links[event_id].motivation, event=related_event(events[event_id], places, epochs)) for event_id in ids]
    return page(items, total, page_number, page_size)


@router.get("/people/{person_id}/places", response_model=Page[PersonPlaceOut])
def list_person_places(
    person_id: int,
    page_number: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sort: Literal["name", "address"] = "name",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[PersonPlaceOut]:
    active_or_404(db, Person, person_id)
    query = db.query(Place.id).join(PersonPlace, PersonPlace.place_id == Place.id).filter(PersonPlace.person_id == person_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(Place.name.ilike(term), Place.address.ilike(term), Place.description.ilike(term), PersonPlace.motivation.ilike(term)))
    expression = Place.name.collate("NOCASE") if sort == "name" else Place.address.collate("NOCASE")
    query = query.order_by(ordered(expression, order, nulls_last=sort == "address"), ordered(Place.id, order))
    ids, total = page_ids(query, page_number, page_size)
    places = load_by_ids(db, Place, ids)
    links = {item.place_id: item for item in db.query(PersonPlace).filter(PersonPlace.person_id == person_id, PersonPlace.place_id.in_(ids)).all()} if ids else {}
    items = [PersonPlaceOut(person_id=person_id, place_id=place_id, motivation=links[place_id].motivation, place=RelatedPlaceOut.model_validate(places[place_id])) for place_id in ids]
    return page(items, total, page_number, page_size)


@router.get("/places/{place_id}/people", response_model=Page[PlacePersonOut])
def list_place_people(
    place_id: int,
    page_number: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120),
    sex: Sex | None = None,
    connotation: Connotation | None = None,
    sort: Literal["alias", "name", "surname"] = "alias",
    order: SortOrder = "asc",
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[PlacePersonOut]:
    active_or_404(db, Place, place_id)
    query = db.query(Person.id).join(PersonPlace, PersonPlace.person_id == Person.id).filter(PersonPlace.place_id == place_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term), PersonPlace.motivation.ilike(term)))
    if sex:
        query = query.filter(Person.sex == sex.value)
    if connotation:
        query = query.filter(Person.connotation == connotation.value)
    expression = {"alias": Person.alias, "name": Person.name, "surname": Person.surname}[sort].collate("NOCASE")
    query = query.order_by(ordered(expression, order, nulls_last=sort != "alias"), ordered(Person.id, order))
    ids, total = page_ids(query, page_number, page_size)
    people = load_by_ids(db, Person, ids)
    links = {item.person_id: item for item in db.query(PersonPlace).filter(PersonPlace.place_id == place_id, PersonPlace.person_id.in_(ids)).all()} if ids else {}
    items = [PlacePersonOut(place_id=place_id, person_id=person_id, motivation=links[person_id].motivation, person=RelatedPersonOut.model_validate(people[person_id])) for person_id in ids]
    return page(items, total, page_number, page_size)


def group_people_page(
    group_id: int, page_number: int, page_size: int, q: str | None, sex: Sex | None,
    connotation: Connotation | None, sort: Literal["alias", "name", "surname"], order: SortOrder,
    db: Session,
) -> Page[RelatedPersonOut]:
    active_or_404(db, SocialGroup, group_id)
    query = db.query(Person.id).join(SocialGroupPerson, SocialGroupPerson.person_id == Person.id).filter(SocialGroupPerson.group_id == group_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(Person.alias.ilike(term), Person.name.ilike(term), Person.surname.ilike(term), Person.description.ilike(term)))
    if sex:
        query = query.filter(Person.sex == sex.value)
    if connotation:
        query = query.filter(Person.connotation == connotation.value)
    expression = {"alias": Person.alias, "name": Person.name, "surname": Person.surname}[sort].collate("NOCASE")
    query = query.order_by(ordered(expression, order, nulls_last=sort != "alias"), ordered(Person.id, order))
    ids, total = page_ids(query, page_number, page_size)
    people = load_by_ids(db, Person, ids)
    return page([RelatedPersonOut.model_validate(people[item]) for item in ids], total, page_number, page_size)


@router.get("/groups/{group_id}/people", response_model=Page[RelatedPersonOut])
def list_group_people(
    group_id: int, page_number: int = Query(default=1, ge=1, alias="page"), page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120), sex: Sex | None = None, connotation: Connotation | None = None,
    sort: Literal["alias", "name", "surname"] = "alias", order: SortOrder = "asc",
    user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> Page[RelatedPersonOut]:
    return group_people_page(group_id, page_number, page_size, q, sex, connotation, sort, order, db)


@router.get("/groups/{group_id}/epochs", response_model=Page[RelatedEpochOut])
def list_group_epochs(
    group_id: int, page_number: int = Query(default=1, ge=1, alias="page"), page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120), sort: Literal["name", "start_date", "end_date"] = "name",
    order: SortOrder = "asc", user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> Page[RelatedEpochOut]:
    active_or_404(db, SocialGroup, group_id)
    query = db.query(Epoch.id).join(SocialGroupEpoch, SocialGroupEpoch.epoch_id == Epoch.id).filter(SocialGroupEpoch.group_id == group_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(Epoch.name.ilike(term), Epoch.description.ilike(term)))
    expression = {"name": Epoch.name.collate("NOCASE"), "start_date": epoch_start_key(), "end_date": epoch_end_key()}[sort]
    query = query.order_by(ordered(expression, order, nulls_last=sort != "name"), ordered(Epoch.id, order))
    ids, total = page_ids(query, page_number, page_size)
    epochs = load_by_ids(db, Epoch, ids)
    return page([RelatedEpochOut.model_validate(epochs[item]) for item in ids], total, page_number, page_size)


def related_groups_page(
    parent_model: type[Person] | type[Epoch], parent_id: int, link_model: type[SocialGroupPerson] | type[SocialGroupEpoch],
    link_column: Any, page_number: int, page_size: int, q: str | None, order: SortOrder, db: Session,
) -> Page[RelatedGroupOut]:
    active_or_404(db, parent_model, parent_id)
    query = db.query(SocialGroup.id).join(link_model, link_model.group_id == SocialGroup.id).filter(link_column == parent_id)
    term = relationship_term(q)
    if term:
        query = query.filter(or_(SocialGroup.name.ilike(term), SocialGroup.description.ilike(term)))
    query = query.order_by(ordered(SocialGroup.name.collate("NOCASE"), order), ordered(SocialGroup.id, order))
    ids, total = page_ids(query, page_number, page_size)
    groups = load_by_ids(db, SocialGroup, ids)
    return page([RelatedGroupOut.model_validate(groups[item]) for item in ids], total, page_number, page_size)


@router.get("/people/{person_id}/groups", response_model=Page[RelatedGroupOut])
def list_person_groups(
    person_id: int, page_number: int = Query(default=1, ge=1, alias="page"), page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120), sort: Literal["name"] = "name", order: SortOrder = "asc",
    user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> Page[RelatedGroupOut]:
    return related_groups_page(Person, person_id, SocialGroupPerson, SocialGroupPerson.person_id, page_number, page_size, q, order, db)


@router.get("/epochs/{epoch_id}/groups", response_model=Page[RelatedGroupOut])
def list_epoch_groups(
    epoch_id: int, page_number: int = Query(default=1, ge=1, alias="page"), page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=120), sort: Literal["name"] = "name", order: SortOrder = "asc",
    user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> Page[RelatedGroupOut]:
    return related_groups_page(Epoch, epoch_id, SocialGroupEpoch, SocialGroupEpoch.epoch_id, page_number, page_size, q, order, db)


@router.patch("/events/{event_id}/participants", response_model=RelationshipChangeOut)
def change_event_participants(
    event_id: int, payload: EventParticipantChangeset, user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> RelationshipChangeOut:
    event = active_or_404(db, Event, event_id)
    add = {item.person_id: item for item in payload.add}
    update = {item.person_id: item for item in payload.update}
    affected = set(add) | set(update) | set(payload.remove_ids)
    existing = {item.person_id: item for item in db.query(PersonEvent).filter(PersonEvent.event_id == event_id, PersonEvent.person_id.in_(affected)).all()} if affected else {}
    validate_state(existing, set(add), set(update), set(payload.remove_ids))
    ensure_targets(db, Person, set(add) | set(update), "Persone")
    real_updates = {key: item for key, item in update.items() if (existing[key].role, existing[key].motivation) != (item.role, item.motivation)}
    if not add and not real_updates and not payload.remove_ids:
        return RelationshipChangeOut(created=0, updated=0, deleted=0)
    timestamp = utcnow()
    for item in add.values():
        db.add(PersonEvent(person_id=item.person_id, event_id=event_id, role=item.role, motivation=item.motivation, created_at=timestamp, updated_at=timestamp, created_by=user.id, updated_by=user.id))
    for key, item in real_updates.items():
        existing[key].role = item.role
        existing[key].motivation = item.motivation
        existing[key].updated_at = timestamp
        existing[key].updated_by = user.id
    for key in payload.remove_ids:
        db.delete(existing[key])
    touch_pullable(event.pullable, user.id, timestamp)
    log_activity(db, user, EntityType.EVENT, event_id, ActivityAction.CHANGE_PARTICIPANTS, timestamp, payload.model_dump())
    db.commit()
    return RelationshipChangeOut(created=len(add), updated=len(real_updates), deleted=len(payload.remove_ids))


def change_person_places_common(
    *, owner: Person | Place, owner_type: EntityType, owner_id: int, payload: PersonPlaceChangeset | PlacePersonChangeset,
    person_side: bool, user: UserAccount, db: Session,
) -> RelationshipChangeOut:
    add = {(item.place_id if person_side else item.person_id): item for item in payload.add}
    update = {(item.place_id if person_side else item.person_id): item for item in payload.update}
    affected = set(add) | set(update) | set(payload.remove_ids)
    link_filter = PersonPlace.person_id == owner_id if person_side else PersonPlace.place_id == owner_id
    counterpart_column = PersonPlace.place_id if person_side else PersonPlace.person_id
    existing = {getattr(item, "place_id" if person_side else "person_id"): item for item in db.query(PersonPlace).filter(link_filter, counterpart_column.in_(affected)).all()} if affected else {}
    validate_state(existing, set(add), set(update), set(payload.remove_ids))
    counterpart_model: type[Place] | type[Person] = Place if person_side else Person
    counterparts = ensure_targets(db, counterpart_model, affected, "Luoghi" if person_side else "Persone")
    real_updates = {key: item for key, item in update.items() if existing[key].motivation != item.motivation}
    changed_ids = set(add) | set(real_updates) | set(payload.remove_ids)
    if not changed_ids:
        return RelationshipChangeOut(created=0, updated=0, deleted=0)
    timestamp = utcnow()
    for key, item in add.items():
        db.add(PersonPlace(person_id=owner_id if person_side else key, place_id=key if person_side else owner_id, motivation=item.motivation, created_at=timestamp, updated_at=timestamp, created_by=user.id, updated_by=user.id))
    for key, item in real_updates.items():
        existing[key].motivation = item.motivation
        existing[key].updated_at = timestamp
        existing[key].updated_by = user.id
    for key in payload.remove_ids:
        db.delete(existing[key])
    owner_action = ActivityAction.CHANGE_PLACES if person_side else ActivityAction.CHANGE_PEOPLE
    counterpart_type = EntityType.PLACE if person_side else EntityType.PERSON
    counterpart_action = ActivityAction.CHANGE_PEOPLE if person_side else ActivityAction.CHANGE_PLACES
    touch_pullable(owner.pullable, user.id, timestamp)
    log_activity(db, user, owner_type, owner_id, owner_action, timestamp, payload.model_dump())
    for key in sorted(changed_ids):
        counterpart = counterparts[key]
        touch_pullable(counterpart.pullable, user.id, timestamp)
        log_activity(db, user, counterpart_type, key, counterpart_action, timestamp, {"counterpart_id": owner_id})
    db.commit()
    return RelationshipChangeOut(created=len(add), updated=len(real_updates), deleted=len(payload.remove_ids))


@router.patch("/people/{person_id}/places", response_model=RelationshipChangeOut)
def change_person_places(
    person_id: int, payload: PersonPlaceChangeset, user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> RelationshipChangeOut:
    return change_person_places_common(owner=active_or_404(db, Person, person_id), owner_type=EntityType.PERSON, owner_id=person_id, payload=payload, person_side=True, user=user, db=db)


@router.patch("/places/{place_id}/people", response_model=RelationshipChangeOut)
def change_place_people(
    place_id: int, payload: PlacePersonChangeset, user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> RelationshipChangeOut:
    return change_person_places_common(owner=active_or_404(db, Place, place_id), owner_type=EntityType.PLACE, owner_id=place_id, payload=payload, person_side=False, user=user, db=db)


def change_group_memberships(
    *, group: SocialGroup, payload: MembershipChangeset, link_model: type[SocialGroupPerson] | type[SocialGroupEpoch],
    counterpart_model: type[Person] | type[Epoch], counterpart_column: Any, label: str, action: ActivityAction,
    user: UserAccount, db: Session,
) -> RelationshipChangeOut:
    affected = set(payload.add_ids) | set(payload.remove_ids)
    existing = {getattr(item, counterpart_column.key): item for item in db.query(link_model).filter(link_model.group_id == group.id, counterpart_column.in_(affected)).all()} if affected else {}
    validate_state(existing, set(payload.add_ids), set(), set(payload.remove_ids))
    ensure_targets(db, counterpart_model, set(payload.add_ids), label)
    if not affected:
        return RelationshipChangeOut(created=0, updated=0, deleted=0)
    timestamp = utcnow()
    for counterpart_id in payload.add_ids:
        kwargs = {"group_id": group.id, counterpart_column.key: counterpart_id, "created_at": timestamp, "updated_at": timestamp, "created_by": user.id, "updated_by": user.id}
        db.add(link_model(**kwargs))
    for counterpart_id in payload.remove_ids:
        db.delete(existing[counterpart_id])
    touch_pullable(group.pullable, user.id, timestamp)
    log_activity(db, user, EntityType.GROUP, group.id, action, timestamp, payload.model_dump())
    db.commit()
    return RelationshipChangeOut(created=len(payload.add_ids), updated=0, deleted=len(payload.remove_ids))


@router.patch("/groups/{group_id}/people", response_model=RelationshipChangeOut)
def change_group_people(
    group_id: int, payload: MembershipChangeset, user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> RelationshipChangeOut:
    return change_group_memberships(group=active_or_404(db, SocialGroup, group_id), payload=payload, link_model=SocialGroupPerson, counterpart_model=Person, counterpart_column=SocialGroupPerson.person_id, label="Persone", action=ActivityAction.CHANGE_GROUP_PEOPLE, user=user, db=db)


@router.patch("/groups/{group_id}/epochs", response_model=RelationshipChangeOut)
def change_group_epochs(
    group_id: int, payload: MembershipChangeset, user: UserAccount = Depends(current_user), db: Session = Depends(get_db),
) -> RelationshipChangeOut:
    return change_group_memberships(group=active_or_404(db, SocialGroup, group_id), payload=payload, link_model=SocialGroupEpoch, counterpart_model=Epoch, counterpart_column=SocialGroupEpoch.epoch_id, label="Epoche", action=ActivityAction.CHANGE_GROUP_EPOCHS, user=user, db=db)
