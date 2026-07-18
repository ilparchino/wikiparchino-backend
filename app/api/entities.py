from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, joinedload

from app.api.deps import current_user
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
from app.models import ActivityAction, EntityType, Epoch, Event, Person, Place, UserAccount, utcnow
from app.schemas import (
    EpochCreate,
    EpochOut,
    EpochUpdate,
    EventCreate,
    EventOut,
    EventUpdate,
    PersonCreate,
    PersonOut,
    PersonUpdate,
    PlaceCreate,
    PlaceOut,
    PlaceUpdate,
)

router = APIRouter(tags=["entities"])


def split_rarity(payload) -> tuple[dict, float]:
    data = payload.model_dump()
    rarity = data.pop("rarity")
    return data, rarity


@router.get("/people", response_model=list[PersonOut])
def list_people(user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> list[Person]:
    return db.query(Person).options(joinedload(Person.pullable)).order_by(Person.alias).all()


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


@router.get("/places", response_model=list[PlaceOut])
def list_places(user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> list[Place]:
    return db.query(Place).options(joinedload(Place.pullable)).order_by(Place.name).all()


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


@router.get("/epochs", response_model=list[EpochOut])
def list_epochs(user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> list[Epoch]:
    return db.query(Epoch).options(joinedload(Epoch.pullable)).order_by(Epoch.name).all()


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


@router.get("/events", response_model=list[EventOut])
def list_events(user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> list[Event]:
    return (
        db.query(Event)
        .options(joinedload(Event.pullable), joinedload(Event.place).joinedload(Place.pullable), joinedload(Event.epoch).joinedload(Epoch.pullable))
        .order_by(Event.year.desc().nullslast(), Event.month.desc().nullslast(), Event.day.desc().nullslast(), Event.title)
        .all()
    )


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(payload: EventCreate, user: UserAccount = Depends(current_user), db: Session = Depends(get_db)) -> Event:
    ensure_reference(db, Place, payload.place_id, "luogo")
    ensure_reference(db, Epoch, payload.epoch_id, "epoca")
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
    ensure_reference(db, Epoch, payload.epoch_id, "epoca")
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
