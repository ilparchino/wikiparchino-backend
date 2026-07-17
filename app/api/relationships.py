from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.api.deps import current_user
from app.api.utils import active_or_404, log_activity, touch_pullable
from app.database import get_db
from app.models import ActivityAction, EntityType, Epoch, Event, Person, PersonEvent, PersonPlace, Place, UserAccount, utcnow
from app.schemas import (
    EventOut,
    EventParticipantIn,
    EventParticipantOut,
    PersonEventOut,
    PersonPlaceIn,
    PersonPlaceOut,
    PlacePersonOut,
)

router = APIRouter(tags=["relationships"])


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
    for entry in payload:
        active_or_404(db, Person, entry.person_id)
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
    for entry in payload:
        active_or_404(db, Place, entry.place_id)
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
