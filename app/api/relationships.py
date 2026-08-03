from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import current_user
from app.api.utils import active_or_404, ensure_reference, log_activity, touch_pullable
from app.database import get_db
from app.models import (
    ActivityAction,
    EntityType,
    Epoch,
    Event,
    Person,
    PersonEvent,
    PersonPlace,
    Place,
    SocialGroup,
    SocialGroupEpoch,
    SocialGroupPerson,
    UserAccount,
    utcnow,
)
from app.schemas import (
    EventOut,
    EventParticipantIn,
    EventParticipantOut,
    GroupEpochsUpdate,
    GroupOut,
    GroupPeopleUpdate,
    EpochOut,
    PersonOut,
    PersonEventOut,
    PersonPlaceIn,
    PersonPlaceOut,
    PlacePersonIn,
    PlacePersonOut,
)

router = APIRouter(tags=["relationships"])


def changed_relationship_ids(
    previous: dict[int, str | None],
    proposed: dict[int, str | None],
) -> set[int]:
    missing = object()
    return {
        entity_id
        for entity_id in previous.keys() | proposed.keys()
        if previous.get(entity_id, missing) != proposed.get(entity_id, missing)
    }


@router.get("/events/{event_id}/participants", response_model=list[EventParticipantOut])
def list_event_participants(
    event_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> list[PersonEvent]:
    active_or_404(db, Event, event_id)
    return (
        db.query(PersonEvent)
        .join(Person, PersonEvent.person_id == Person.id)
        .options(joinedload(PersonEvent.person))
        .filter(PersonEvent.event_id == event_id)
        .order_by(Person.alias, PersonEvent.person_id)
        .all()
    )


@router.put("/events/{event_id}/participants", response_model=list[EventParticipantOut])
def replace_event_participants(
    event_id: int,
    payload: list[EventParticipantIn],
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[PersonEvent]:
    event = active_or_404(db, Event, event_id)
    ensure_unique_ids([entry.person_id for entry in payload], "persona")
    for entry in payload:
        ensure_reference(db, Person, entry.person_id, "persona")
    timestamp = utcnow()
    db.query(PersonEvent).filter(PersonEvent.event_id == event_id).delete()
    for entry in payload:
        db.add(
            PersonEvent(
                event_id=event_id,
                person_id=entry.person_id,
                role=entry.role,
                motivation=entry.motivation,
                created_at=timestamp,
                updated_at=timestamp,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    touch_pullable(event.pullable, user.id, timestamp)
    log_activity(
        db,
        user,
        EntityType.EVENT,
        event_id,
        ActivityAction.REPLACE_PARTICIPANTS,
        timestamp,
        [item.model_dump() for item in payload],
    )
    db.commit()
    return list_event_participants(event_id, user, db)


@router.get("/people/{person_id}/events", response_model=list[PersonEventOut])
def list_person_events(
    person_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> list[PersonEvent]:
    active_or_404(db, Person, person_id)
    return (
        db.query(PersonEvent)
        .options(
            joinedload(PersonEvent.event).joinedload(Event.pullable),
            joinedload(PersonEvent.event).joinedload(Event.place).joinedload(Place.pullable),
            joinedload(PersonEvent.event).joinedload(Event.epoch),
        )
        .filter(PersonEvent.person_id == person_id)
        .order_by(PersonEvent.event_id)
        .all()
    )


@router.get("/people/{person_id}/places", response_model=list[PersonPlaceOut])
def list_person_places(
    person_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> list[PersonPlace]:
    active_or_404(db, Person, person_id)
    return (
        db.query(PersonPlace)
        .options(joinedload(PersonPlace.place))
        .filter(PersonPlace.person_id == person_id)
        .order_by(PersonPlace.place_id)
        .all()
    )


@router.put("/people/{person_id}/places", response_model=list[PersonPlaceOut])
def replace_person_places(
    person_id: int,
    payload: list[PersonPlaceIn],
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[PersonPlace]:
    person = active_or_404(db, Person, person_id)
    ensure_unique_ids([entry.place_id for entry in payload], "luogo")
    places: dict[int, Place] = {}
    for entry in payload:
        places[entry.place_id] = ensure_reference(db, Place, entry.place_id, "luogo")
    previous = {
        link.place_id: link.motivation
        for link in db.query(PersonPlace).filter(PersonPlace.person_id == person_id).all()
    }
    proposed = {entry.place_id: entry.motivation for entry in payload}
    changed_place_ids = changed_relationship_ids(previous, proposed)
    timestamp = utcnow()
    db.query(PersonPlace).filter(PersonPlace.person_id == person_id).delete()
    for entry in payload:
        db.add(
            PersonPlace(
                person_id=person_id,
                place_id=entry.place_id,
                motivation=entry.motivation,
                created_at=timestamp,
                updated_at=timestamp,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    touch_pullable(person.pullable, user.id, timestamp)
    log_activity(
        db,
        user,
        EntityType.PERSON,
        person_id,
        ActivityAction.REPLACE_PLACES,
        timestamp,
        [item.model_dump() for item in payload],
    )
    for place_id in sorted(changed_place_ids):
        place = places.get(place_id) or ensure_reference(db, Place, place_id, "luogo")
        touch_pullable(place.pullable, user.id, timestamp)
        log_activity(
            db,
            user,
            EntityType.PLACE,
            place_id,
            ActivityAction.REPLACE_PEOPLE,
            timestamp,
            {
                "person_id": person_id,
                "linked": place_id in proposed,
                "motivation": proposed.get(place_id),
            },
        )
    db.commit()
    return list_person_places(person_id, user, db)


@router.get("/places/{place_id}/people", response_model=list[PlacePersonOut])
def list_place_people(
    place_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> list[PersonPlace]:
    active_or_404(db, Place, place_id)
    return (
        db.query(PersonPlace)
        .options(joinedload(PersonPlace.person).joinedload(Person.pullable))
        .filter(PersonPlace.place_id == place_id)
        .order_by(PersonPlace.person_id)
        .all()
    )


@router.put("/places/{place_id}/people", response_model=list[PlacePersonOut])
def replace_place_people(
    place_id: int,
    payload: list[PlacePersonIn],
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[PersonPlace]:
    place = active_or_404(db, Place, place_id)
    ensure_unique_ids([entry.person_id for entry in payload], "persona")
    people: dict[int, Person] = {}
    for entry in payload:
        people[entry.person_id] = ensure_reference(db, Person, entry.person_id, "persona")
    previous = {
        link.person_id: link.motivation
        for link in db.query(PersonPlace).filter(PersonPlace.place_id == place_id).all()
    }
    proposed = {entry.person_id: entry.motivation for entry in payload}
    changed_person_ids = changed_relationship_ids(previous, proposed)
    timestamp = utcnow()
    db.query(PersonPlace).filter(PersonPlace.place_id == place_id).delete()
    for entry in payload:
        db.add(
            PersonPlace(
                person_id=entry.person_id,
                place_id=place_id,
                motivation=entry.motivation,
                created_at=timestamp,
                updated_at=timestamp,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    touch_pullable(place.pullable, user.id, timestamp)
    log_activity(
        db,
        user,
        EntityType.PLACE,
        place_id,
        ActivityAction.REPLACE_PEOPLE,
        timestamp,
        [item.model_dump() for item in payload],
    )
    for person_id in sorted(changed_person_ids):
        person = people.get(person_id) or ensure_reference(db, Person, person_id, "persona")
        touch_pullable(person.pullable, user.id, timestamp)
        log_activity(
            db,
            user,
            EntityType.PERSON,
            person_id,
            ActivityAction.REPLACE_PLACES,
            timestamp,
            {
                "place_id": place_id,
                "linked": person_id in proposed,
                "motivation": proposed.get(person_id),
            },
        )
    db.commit()
    return list_place_people(place_id, user, db)


@router.get("/places/{place_id}/events", response_model=list[EventOut])
def list_place_events(
    place_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> list[Event]:
    active_or_404(db, Place, place_id)
    return (
        db.query(Event)
        .options(joinedload(Event.pullable), joinedload(Event.place).joinedload(Place.pullable), joinedload(Event.epoch))
        .filter(Event.place_id == place_id)
        .order_by(Event.year.desc().nullslast(), Event.month.desc().nullslast(), Event.day.desc().nullslast(), Event.title)
        .all()
    )


@router.get("/epochs/{epoch_id}/events", response_model=list[EventOut])
def list_epoch_events(
    epoch_id: int, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)
) -> list[Event]:
    active_or_404(db, Epoch, epoch_id)
    return (
        db.query(Event)
        .options(joinedload(Event.pullable), joinedload(Event.place).joinedload(Place.pullable), joinedload(Event.epoch))
        .filter(Event.epoch_id == epoch_id)
        .order_by(Event.year.desc().nullslast(), Event.month.desc().nullslast(), Event.day.desc().nullslast(), Event.title)
        .all()
    )


def ensure_unique_ids(ids: list[int], label: str) -> None:
    if len(ids) != len(set(ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ogni {label} può essere collegata una sola volta",
        )


@router.get("/groups/{group_id}/people", response_model=list[PersonOut])
def list_group_people(
    group_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Person]:
    active_or_404(db, SocialGroup, group_id)
    return (
        db.query(Person)
        .join(SocialGroupPerson, SocialGroupPerson.person_id == Person.id)
        .options(joinedload(Person.pullable))
        .filter(SocialGroupPerson.group_id == group_id)
        .order_by(Person.alias, Person.id)
        .all()
    )


@router.put("/groups/{group_id}/people", response_model=list[PersonOut])
def replace_group_people(
    group_id: int,
    payload: GroupPeopleUpdate,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Person]:
    group = active_or_404(db, SocialGroup, group_id)
    ensure_unique_ids(payload.person_ids, "persona")
    for person_id in payload.person_ids:
        ensure_reference(db, Person, person_id, "persona")
    timestamp = utcnow()
    db.query(SocialGroupPerson).filter(SocialGroupPerson.group_id == group_id).delete()
    for person_id in payload.person_ids:
        db.add(
            SocialGroupPerson(
                group_id=group_id,
                person_id=person_id,
                created_at=timestamp,
                updated_at=timestamp,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    touch_pullable(group.pullable, user.id, timestamp)
    log_activity(
        db,
        user,
        EntityType.GROUP,
        group_id,
        ActivityAction.REPLACE_GROUP_PEOPLE,
        timestamp,
        payload.model_dump(),
    )
    db.commit()
    return list_group_people(group_id, user, db)


@router.get("/groups/{group_id}/epochs", response_model=list[EpochOut])
def list_group_epochs(
    group_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Epoch]:
    active_or_404(db, SocialGroup, group_id)
    return (
        db.query(Epoch)
        .join(SocialGroupEpoch, SocialGroupEpoch.epoch_id == Epoch.id)
        .options(joinedload(Epoch.pullable))
        .filter(SocialGroupEpoch.group_id == group_id)
        .order_by(Epoch.name, Epoch.id)
        .all()
    )


@router.put("/groups/{group_id}/epochs", response_model=list[EpochOut])
def replace_group_epochs(
    group_id: int,
    payload: GroupEpochsUpdate,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Epoch]:
    group = active_or_404(db, SocialGroup, group_id)
    ensure_unique_ids(payload.epoch_ids, "epoca")
    for epoch_id in payload.epoch_ids:
        ensure_reference(db, Epoch, epoch_id, "epoca")
    timestamp = utcnow()
    db.query(SocialGroupEpoch).filter(SocialGroupEpoch.group_id == group_id).delete()
    for epoch_id in payload.epoch_ids:
        db.add(
            SocialGroupEpoch(
                group_id=group_id,
                epoch_id=epoch_id,
                created_at=timestamp,
                updated_at=timestamp,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    touch_pullable(group.pullable, user.id, timestamp)
    log_activity(
        db,
        user,
        EntityType.GROUP,
        group_id,
        ActivityAction.REPLACE_GROUP_EPOCHS,
        timestamp,
        payload.model_dump(),
    )
    db.commit()
    return list_group_epochs(group_id, user, db)


@router.get("/people/{person_id}/groups", response_model=list[GroupOut])
def list_person_groups(
    person_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SocialGroup]:
    active_or_404(db, Person, person_id)
    return (
        db.query(SocialGroup)
        .join(SocialGroupPerson, SocialGroupPerson.group_id == SocialGroup.id)
        .options(joinedload(SocialGroup.pullable))
        .filter(SocialGroupPerson.person_id == person_id)
        .order_by(SocialGroup.name, SocialGroup.id)
        .all()
    )


@router.get("/epochs/{epoch_id}/groups", response_model=list[GroupOut])
def list_epoch_groups(
    epoch_id: int,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[SocialGroup]:
    active_or_404(db, Epoch, epoch_id)
    return (
        db.query(SocialGroup)
        .join(SocialGroupEpoch, SocialGroupEpoch.group_id == SocialGroup.id)
        .options(joinedload(SocialGroup.pullable))
        .filter(SocialGroupEpoch.epoch_id == epoch_id)
        .order_by(SocialGroup.name, SocialGroup.id)
        .all()
    )
