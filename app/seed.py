from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
import json
from pathlib import Path
from typing import TypeVar

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    ActivityAction,
    ActivityLog,
    Connotation,
    EntityType,
    Epoch,
    Event,
    MediaAsset,
    Person,
    PersonEvent,
    PersonPlace,
    Place,
    Pullable,
    SecurityEventLog,
    SecurityEventType,
    Sex,
    SocialGroup,
    SocialGroupEpoch,
    SocialGroupPerson,
    UserAccount,
    UserSession,
    utcnow,
)
from app.security import hash_password
from app.security_events import log_security_event

DEMO_PASSWORD = "demo-password-123"
TEST_PASSWORD = "admin"
EntityT = TypeVar("EntityT", Person, Place, Epoch, Event, SocialGroup)


@dataclass(frozen=True)
class StressSeedScale:
    people: int = 1_500
    places: int = 300
    epochs: int = 60
    events: int = 3_000
    groups: int = 200
    media: int = 300

    def __post_init__(self) -> None:
        values = (
            self.people,
            self.places,
            self.epochs,
            self.events,
            self.groups,
            self.media,
        )
        if any(value <= 0 for value in values):
            raise ValueError("Stress seed sizes must all be positive")
        if self.media % len(EntityType) != 0:
            raise ValueError("Stress media count must be divisible by the entity-type count")


STRESS_SEED_SCALE = StressSeedScale()


class SeedDataError(RuntimeError):
    pass


def varied_demo_description(
    label: str,
    subject: str,
    index: int,
) -> str | None:
    variant = (index - 1) % 7
    if variant == 6:
        return None
    if variant == 0:
        return f"{label} #{index}."

    repetitions = (0, 1, 3, 8, 24, 70)[variant]
    return " ".join(
        f"Dettaglio generico #{part} {subject} #{index}, usato per verificare la resa di descrizioni con lunghezze differenti."
        for part in range(1, repetitions + 1)
    )


def stress_bounded_text(
    label: str, index: int, maximum: int, *, force_maximum: bool = False
) -> str:
    base = f"{label} #{index}"
    if force_maximum or index % 211 == 0:
        return (base + " " + "testo-di-confine " * maximum)[:maximum]
    if index % 127 == 0:
        return (base + "-" + "X" * maximum)[:maximum]
    if index % 89 == 0:
        return f"{base} - prova Unicode àèìòù 漢字 🧭"
    return base


def stress_description(label: str, subject: str, index: int) -> str | None:
    bucket = index % 100
    if bucket < 10:
        return None
    if index % 251 == 0:
        return f"{label} #{index}: " + "X" * 20_000

    repetitions = 1
    if bucket >= 50:
        repetitions = 5
    if bucket >= 80:
        repetitions = 25
    if bucket >= 95:
        repetitions = 100
    if bucket == 99:
        repetitions = 500

    separator = "\n\n" if index % 17 == 0 else " "
    description = separator.join(
        f"Dettaglio di carico #{part} {subject} {label} #{index}: testo generico per verificare prestazioni, wrapping e troncamento."
        for part in range(1, repetitions + 1)
    )
    if index % 89 == 0:
        description += " Contenuto Unicode àèìòù 漢字 🧭."
    return description


def stress_motivation(label: str, index: int) -> str | None:
    bucket = index % 40
    if bucket < 4:
        return None
    if index % 503 == 0:
        return f"{label} #{index}: " + "M" * 20_000
    repetitions = 1 if bucket < 24 else 5 if bucket < 36 else 30
    separator = "\n" if index % 29 == 0 else " "
    return separator.join(
        f"Motivazione di carico #{part} per {label.lower()} #{index}, con contenuto anonimo e deterministico."
        for part in range(1, repetitions + 1)
    )


def add_activity(
    db: Session,
    actor: UserAccount,
    entity_type: EntityType,
    entity_id: int,
    action: ActivityAction,
    timestamp: datetime,
    payload: object | None = None,
) -> None:
    db.add(
        ActivityLog(
            actor_user_id=actor.id,
            entity_type=entity_type.value,
            entity_id=entity_id,
            action=action.value,
            payload_json=(
                json.dumps(payload, ensure_ascii=False) if payload is not None else None
            ),
            occurred_at=timestamp,
        )
    )


def add_entity(
    db: Session,
    model: type[EntityT],
    entity_type: EntityType,
    actor: UserAccount,
    timestamp: datetime,
    rarity: float = 1.0,
    *,
    log_creation: bool = True,
    **values: object,
) -> EntityT:
    pullable = Pullable(
        rarity=rarity,
        created_at=timestamp,
        updated_at=timestamp,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(pullable)
    db.flush()
    item = model(id=pullable.id, **values)
    db.add(item)
    db.flush()
    if log_creation:
        add_activity(
            db,
            actor,
            entity_type,
            item.id,
            ActivityAction.CREATE,
            timestamp,
        )
    return item


def touch_entity(item: EntityT, actor: UserAccount, timestamp: datetime) -> None:
    item.pullable.updated_at = timestamp
    item.pullable.updated_by = actor.id


def ensure_empty_demo_target(db: Session, media_dir: Path) -> None:
    table_counts = {
        "users": db.query(UserAccount).count(),
        "sessions": db.query(UserSession).count(),
        "content": db.query(Pullable).count(),
        "media": db.query(MediaAsset).count(),
        "activity": db.query(ActivityLog).count(),
        "security activity": db.query(SecurityEventLog).count(),
    }
    populated = [name for name, count in table_counts.items() if count]
    if populated:
        raise SeedDataError(
            "The demo seed requires an empty database; existing data found in: "
            + ", ".join(populated)
        )
    if media_dir.exists() and any(media_dir.iterdir()):
        raise SeedDataError(
            f"The demo seed requires an empty media directory: {media_dir}"
        )


def create_demo_users(
    db: Session, now: datetime, *, stress: bool = False
) -> list[UserAccount]:
    definitions = [
        ("admin", "Amministratore #1", True, True),
        ("admin2", "Amministratore #2", True, True),
        ("utente1", "Utente #1", False, True),
        ("utente2", "Utente #2", False, True),
        ("utente3", "Utente #3", False, True),
        ("utente4", "Utente #4", False, True),
        ("utente5", "Utente #5", False, True),
        ("utente6", "Utente #6", False, False),
    ]
    users: list[UserAccount] = []
    creation_start = now - timedelta(days=60)
    for index, (username, display_name, is_admin, is_active) in enumerate(definitions):
        if stress and username == "utente5":
            display_name = stress_bounded_text("Utente", 211, 160)
        created_at = creation_start + timedelta(hours=index)
        user = UserAccount(
            username=username,
            display_name=display_name,
            password_hash=hash_password(DEMO_PASSWORD),
            is_admin=is_admin,
            is_active=is_active,
            is_owner=index == 0,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(user)
        db.flush()
        users.append(user)

    administrator = users[0]
    for user in users:
        log_security_event(
            db,
            SecurityEventType.USER_CREATED,
            user.created_at,
            actor=administrator,
            target=user,
        )

    inactive_user = users[-1]
    deactivated_at = now - timedelta(days=2)
    inactive_user.updated_at = deactivated_at
    log_security_event(
        db,
        SecurityEventType.USER_DEACTIVATED,
        deactivated_at,
        actor=administrator,
        target=inactive_user,
    )
    return users


def create_people(
    db: Session, actors: list[UserAccount], now: datetime
) -> list[Person]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    sexes = tuple(Sex)
    connotations = tuple(Connotation)
    start = now - timedelta(days=50)
    people: list[Person] = []
    for index in range(1, 25):
        actor = actors[(index - 1) % len(actors)]
        people.append(
            add_entity(
                db,
                Person,
                EntityType.PERSON,
                actor,
                start + timedelta(hours=index),
                rarities[(index - 1) % len(rarities)],
                alias=f"Persona #{index}",
                name=None if index % 5 == 0 else f"Nome #{index}",
                surname=None if index % 4 == 0 else f"Cognome #{index}",
                sex=sexes[(index - 1) % len(sexes)].value,
                connotation=connotations[(index - 1) % len(connotations)].value,
                description=varied_demo_description(
                    "Persona",
                    "della persona",
                    index,
                ),
            )
        )
    return people


def create_places(
    db: Session, actors: list[UserAccount], now: datetime
) -> list[Place]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    start = now - timedelta(days=45)
    places: list[Place] = []
    for index in range(1, 13):
        actor = actors[(index + 1) % len(actors)]
        places.append(
            add_entity(
                db,
                Place,
                EntityType.PLACE,
                actor,
                start + timedelta(hours=index),
                rarities[index % len(rarities)],
                name=f"Luogo #{index}",
                address=(
                    None
                    if index % 3 == 0
                    else f"Via Dimostrativa #{index}, 100{index:02d} Città #{(index % 4) + 1}"
                ),
                description=varied_demo_description(
                    "Luogo",
                    "del luogo",
                    index,
                ),
            )
        )
    return places


def create_epochs(
    db: Session, actors: list[UserAccount], now: datetime
) -> list[Epoch]:
    start = now - timedelta(days=40)
    date_ranges = (
        {},
        {"start_year": 2000},
        {"end_year": 2030, "end_month": 12},
        {
            "start_year": 2000,
            "start_month": 1,
            "end_year": 2030,
            "end_month": 12,
            "end_day": 31,
        },
        {
            "start_year": 2000,
            "start_month": 1,
            "start_day": 1,
            "end_year": 2030,
        },
    )
    epochs: list[Epoch] = []
    for index in range(1, 6):
        actor = actors[(index + 2) % len(actors)]
        epochs.append(
            add_entity(
                db,
                Epoch,
                EntityType.EPOCH,
                actor,
                start + timedelta(hours=index),
                (0.75, 1.0, 1.5, 2.0, 3.0)[index - 1],
                name=f"Epoca #{index}",
                description=varied_demo_description(
                    "Epoca",
                    "dell'epoca",
                    index,
                ),
                **date_ranges[index - 1],
            )
        )
    return epochs


def event_date(index: int) -> tuple[int | None, int | None, int | None]:
    year = 2010 + (index % 16)
    variant = (index - 1) % 4
    if variant == 0:
        return None, None, None
    if variant == 1:
        return year, None, None
    if variant == 2:
        return year, ((index - 1) % 12) + 1, None
    return year, ((index - 1) % 12) + 1, ((index - 1) % 28) + 1


def create_events(
    db: Session,
    actors: list[UserAccount],
    places: list[Place],
    epochs: list[Epoch],
    now: datetime,
) -> list[Event]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    start = now - timedelta(days=35)
    events: list[Event] = []
    for index in range(1, 41):
        actor = actors[(index + 3) % len(actors)]
        year, month, day = event_date(index)
        events.append(
            add_entity(
                db,
                Event,
                EntityType.EVENT,
                actor,
                start + timedelta(hours=index * 6),
                rarities[(index + 1) % len(rarities)],
                epoch_id=epochs[(index - 1) % len(epochs)].id,
                place_id=places[(index - 1) % len(places)].id,
                title=f"Evento #{index}",
                description=varied_demo_description(
                    "Evento",
                    "dell'evento",
                    index,
                ),
                year=year,
                month=month,
                day=day,
            )
        )
    return events


def create_groups(
    db: Session, actors: list[UserAccount], now: datetime
) -> list[SocialGroup]:
    start = now - timedelta(days=30)
    groups: list[SocialGroup] = []
    for index in range(1, 7):
        actor = actors[(index + 4) % len(actors)]
        groups.append(
            add_entity(
                db,
                SocialGroup,
                EntityType.GROUP,
                actor,
                start + timedelta(hours=index),
                (0.5, 1.0, 1.5, 2.0, 3.0, 1.0)[index - 1],
                name=f"Cerchia #{index}",
                description=(
                    None
                    if index == 4
                    else varied_demo_description(
                        "Cerchia",
                        "della cerchia",
                        index,
                    )
                ),
            )
        )
    return groups


def create_group_links(
    db: Session,
    actors: list[UserAccount],
    groups: list[SocialGroup],
    people: list[Person],
    epochs: list[Epoch],
    now: datetime,
) -> None:
    people_by_group = (
        range(0, 8),
        range(4, 12),
        range(9, 18),
        range(16, 24),
        range(0, 24, 5),
        (),
    )
    epochs_by_group = (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (0, 2, 4),
        (),
    )
    start = now - timedelta(days=8)
    for index, group in enumerate(groups):
        actor = actors[(index + 2) % len(actors)]
        person_ids = [people[person_index].id for person_index in people_by_group[index]]
        if person_ids:
            timestamp = start + timedelta(hours=index * 2)
            for person_id in person_ids:
                db.add(
                    SocialGroupPerson(
                        group_id=group.id,
                        person_id=person_id,
                        created_at=timestamp,
                        updated_at=timestamp,
                        created_by=actor.id,
                        updated_by=actor.id,
                    )
                )
            touch_entity(group, actor, timestamp)
            add_activity(
                db,
                actor,
                EntityType.GROUP,
                group.id,
                ActivityAction.REPLACE_GROUP_PEOPLE,
                timestamp,
                {"person_ids": person_ids},
            )

        epoch_ids = [epochs[epoch_index].id for epoch_index in epochs_by_group[index]]
        if epoch_ids:
            timestamp = start + timedelta(hours=index * 2 + 1)
            for epoch_id in epoch_ids:
                db.add(
                    SocialGroupEpoch(
                        group_id=group.id,
                        epoch_id=epoch_id,
                        created_at=timestamp,
                        updated_at=timestamp,
                        created_by=actor.id,
                        updated_by=actor.id,
                    )
                )
            touch_entity(group, actor, timestamp)
            add_activity(
                db,
                actor,
                EntityType.GROUP,
                group.id,
                ActivityAction.REPLACE_GROUP_EPOCHS,
                timestamp,
                {"epoch_ids": epoch_ids},
            )


def create_person_place_links(
    db: Session,
    actors: list[UserAccount],
    people: list[Person],
    places: list[Place],
    now: datetime,
) -> None:
    start = now - timedelta(days=10)
    for index, person in enumerate(people):
        actor = actors[index % len(actors)]
        timestamp = start + timedelta(hours=index)
        linked_places = [places[index % len(places)], places[(index + 5) % len(places)]]
        for place_index, place in enumerate(linked_places, start=1):
            db.add(
                PersonPlace(
                    person_id=person.id,
                    place_id=place.id,
                    motivation=f"Collegamento generico #{place_index} per Persona #{index + 1}.",
                    created_at=timestamp,
                    updated_at=timestamp,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
        touch_entity(person, actor, timestamp)
        add_activity(
            db,
            actor,
            EntityType.PERSON,
            person.id,
            ActivityAction.REPLACE_PLACES,
            timestamp,
            {"count": 2},
        )


def create_event_participants(
    db: Session,
    actors: list[UserAccount],
    people: list[Person],
    events: list[Event],
    now: datetime,
) -> None:
    roles = ("Organizzatore", "Guida", "Partecipante", None)
    start = now - timedelta(days=8)
    for index, event in enumerate(events):
        actor = actors[(index + 1) % len(actors)]
        timestamp = start + timedelta(hours=index)
        for offset, role in enumerate(roles):
            person = people[(index * 3 + offset * 5) % len(people)]
            db.add(
                PersonEvent(
                    person_id=person.id,
                    event_id=event.id,
                    role=role,
                    motivation=(
                        None
                        if role is None
                        else f"Motivazione generica per il ruolo {role.lower()}."
                    ),
                    created_at=timestamp,
                    updated_at=timestamp,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
        touch_entity(event, actor, timestamp)
        add_activity(
            db,
            actor,
            EntityType.EVENT,
            event.id,
            ActivityAction.REPLACE_PARTICIPANTS,
            timestamp,
            {"count": 4},
        )


def sample_svg(index: int, width: int, height: int) -> bytes:
    palette = (
        ("#0d6efd", "#f8f9fa"),
        ("#198754", "#f8f9fa"),
        ("#dc3545", "#f8f9fa"),
        ("#ffc107", "#212529"),
        ("#6f42c1", "#f8f9fa"),
        ("#20c997", "#212529"),
    )
    background, foreground = palette[(index - 1) % len(palette)]
    label = escape(f"Immagine #{index}")
    orientation = escape("Verticale" if height > width else "Orizzontale")
    markup = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="{width}" height="{height}" fill="{background}"/>
  <circle cx="{width * 3 // 4}" cy="{height // 4}" r="{min(width, height) // 7}" fill="{foreground}" opacity="0.22"/>
  <text x="{width // 2}" y="{height // 2}" fill="{foreground}" font-family="sans-serif" font-size="{max(24, min(width, height) // 12)}" text-anchor="middle">{label}</text>
  <text x="{width // 2}" y="{height // 2 + max(36, min(width, height) // 10)}" fill="{foreground}" font-family="sans-serif" font-size="{max(16, min(width, height) // 24)}" text-anchor="middle">{orientation}</text>
</svg>
"""
    return markup.encode("utf-8")


def create_media(
    db: Session,
    actors: list[UserAccount],
    people: list[Person],
    places: list[Place],
    epochs: list[Epoch],
    events: list[Event],
    groups: list[SocialGroup],
    media_dir: Path,
    now: datetime,
    created_files: list[Path],
) -> None:
    targets: list[tuple[EntityType, EntityT]] = [
        (EntityType.PERSON, people[0]),
        (EntityType.PERSON, people[0]),
        *((EntityType.PERSON, person) for person in people[1:5]),
        (EntityType.PLACE, places[0]),
        (EntityType.PLACE, places[0]),
        *((EntityType.PLACE, place) for place in places[1:4]),
        (EntityType.EPOCH, epochs[0]),
        (EntityType.EPOCH, epochs[0]),
        (EntityType.EPOCH, epochs[1]),
        (EntityType.EVENT, events[0]),
        (EntityType.EVENT, events[0]),
        (EntityType.EVENT, events[1]),
        (EntityType.EVENT, events[2]),
        (EntityType.GROUP, groups[0]),
        (EntityType.GROUP, groups[1]),
    ]
    media_dir.mkdir(parents=True, exist_ok=True)
    start = now - timedelta(hours=len(targets) - 1)
    for index, (entity_type, item) in enumerate(targets, start=1):
        actor = actors[(index + 2) % len(actors)]
        timestamp = start + timedelta(hours=index - 1)
        width, height = (480, 640) if index % 3 == 0 else (640, 360)
        path = media_dir / f"seed-immagine-{index:02d}.svg"
        path.write_bytes(sample_svg(index, width, height))
        created_files.append(path)
        asset = MediaAsset(
            pullable_id=item.id,
            filename=f"immagine-{index:02d}.svg",
            content_type="image/svg+xml",
            disk_path=str(path.resolve()),
            created_at=timestamp,
            created_by=actor.id,
        )
        db.add(asset)
        db.flush()
        touch_entity(item, actor, timestamp)
        add_activity(
            db,
            actor,
            entity_type,
            item.id,
            ActivityAction.UPLOAD_MEDIA,
            timestamp,
            {"media_id": asset.id},
        )


def add_stress_entities(
    db: Session,
    model: type[EntityT],
    entity_type: EntityType,
    definitions: list[tuple[UserAccount, datetime, float, dict[str, object]]],
) -> list[EntityT]:
    pullables = [
        Pullable(
            rarity=rarity,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=actor.id,
            updated_by=actor.id,
        )
        for actor, timestamp, rarity, _ in definitions
    ]
    db.add_all(pullables)
    db.flush()

    items: list[EntityT] = []
    activities: list[ActivityLog] = []
    for pullable, (actor, timestamp, _, values) in zip(
        pullables, definitions, strict=True
    ):
        item = model(id=pullable.id, **values)
        item.pullable = pullable
        items.append(item)
        activities.append(
            ActivityLog(
                actor_user_id=actor.id,
                entity_type=entity_type.value,
                entity_id=pullable.id,
                action=ActivityAction.CREATE.value,
                occurred_at=timestamp,
            )
        )
    db.add_all(items)
    db.add_all(activities)
    db.flush()
    return items


def create_stress_people(
    db: Session,
    actors: list[UserAccount],
    now: datetime,
    count: int,
) -> list[Person]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    sexes = tuple(Sex)
    connotations = tuple(Connotation)
    start = now - timedelta(days=60)
    definitions = []
    for index in range(1, count + 1):
        definitions.append(
            (
                actors[(index - 1) % len(actors)],
                start + timedelta(seconds=index),
                rarities[(index - 1) % len(rarities)],
                {
                    "alias": stress_bounded_text("Persona", index, 255),
                    "name": (
                        None
                        if index % 5 == 0
                        else stress_bounded_text("Nome", index, 255)
                    ),
                    "surname": (
                        None
                        if index % 4 == 0
                        else stress_bounded_text("Cognome", index, 255)
                    ),
                    "sex": sexes[(index - 1) % len(sexes)].value,
                    "connotation": connotations[(index - 1) % len(connotations)].value,
                    "description": stress_description("Persona", "della persona", index),
                },
            )
        )
    return add_stress_entities(db, Person, EntityType.PERSON, definitions)


def create_stress_places(
    db: Session,
    actors: list[UserAccount],
    now: datetime,
    count: int,
) -> list[Place]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    start = now - timedelta(days=55)
    definitions = []
    for index in range(1, count + 1):
        definitions.append(
            (
                actors[(index + 1) % len(actors)],
                start + timedelta(seconds=index),
                rarities[index % len(rarities)],
                {
                    "name": stress_bounded_text("Luogo", index, 255),
                    "address": (
                        None
                        if index % 3 == 0
                        else stress_bounded_text("Via dimostrativa", index, 500)
                    ),
                    "description": stress_description("Luogo", "del luogo", index),
                },
            )
        )
    return add_stress_entities(db, Place, EntityType.PLACE, definitions)


def create_stress_epochs(
    db: Session,
    actors: list[UserAccount],
    now: datetime,
    count: int,
) -> list[Epoch]:
    date_ranges: tuple[dict[str, int], ...] = (
        {},
        {"start_year": 2000},
        {"end_year": 2030, "end_month": 12},
        {
            "start_year": 2000,
            "start_month": 1,
            "end_year": 2030,
            "end_month": 12,
            "end_day": 31,
        },
        {
            "start_year": 2000,
            "start_month": 1,
            "start_day": 1,
            "end_year": 2030,
        },
    )
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    start = now - timedelta(days=50)
    definitions = []
    for index in range(1, count + 1):
        definitions.append(
            (
                actors[(index + 2) % len(actors)],
                start + timedelta(seconds=index),
                rarities[(index - 1) % len(rarities)],
                {
                    "name": stress_bounded_text(
                        "Epoca", index, 255, force_maximum=index == count
                    ),
                    "description": stress_description("Epoca", "dell'epoca", index),
                    **date_ranges[(index - 1) % len(date_ranges)],
                },
            )
        )
    return add_stress_entities(db, Epoch, EntityType.EPOCH, definitions)


def create_stress_events(
    db: Session,
    actors: list[UserAccount],
    places: list[Place],
    epochs: list[Epoch],
    now: datetime,
    count: int,
) -> list[Event]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    start = now - timedelta(days=45)
    definitions = []
    for index in range(1, count + 1):
        year, month, day = event_date(index)
        definitions.append(
            (
                actors[(index + 3) % len(actors)],
                start + timedelta(seconds=index),
                rarities[(index + 1) % len(rarities)],
                {
                    "epoch_id": epochs[(index - 1) % len(epochs)].id,
                    "place_id": places[(index - 1) % len(places)].id,
                    "title": stress_bounded_text("Evento", index, 255),
                    "description": stress_description("Evento", "dell'evento", index),
                    "year": year,
                    "month": month,
                    "day": day,
                },
            )
        )
    return add_stress_entities(db, Event, EntityType.EVENT, definitions)


def create_stress_groups(
    db: Session,
    actors: list[UserAccount],
    now: datetime,
    count: int,
) -> list[SocialGroup]:
    rarities = (0.5, 1.0, 1.5, 2.0, 3.0)
    start = now - timedelta(days=40)
    definitions = []
    for index in range(1, count + 1):
        definitions.append(
            (
                actors[(index + 4) % len(actors)],
                start + timedelta(seconds=index),
                rarities[(index + 2) % len(rarities)],
                {
                    "name": stress_bounded_text("Cerchia", index, 255),
                    "description": stress_description("Cerchia", "della cerchia", index),
                },
            )
        )
    return add_stress_entities(db, SocialGroup, EntityType.GROUP, definitions)


def create_stress_person_place_links(
    db: Session,
    actors: list[UserAccount],
    people: list[Person],
    places: list[Place],
    now: datetime,
) -> None:
    start = now - timedelta(days=20)
    links: list[PersonPlace] = []
    for index, person in enumerate(people, start=1):
        actor = actors[(index - 1) % len(actors)]
        timestamp = start + timedelta(seconds=index)
        place_ids = [places[(index * 7 + offset) % len(places)].id for offset in range(4)]
        for offset, place_id in enumerate(place_ids, start=1):
            link_index = (index - 1) * 4 + offset
            links.append(
                PersonPlace(
                    person_id=person.id,
                    place_id=place_id,
                    motivation=stress_motivation("Collegamento persona-luogo", link_index),
                    created_at=timestamp,
                    updated_at=timestamp,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
        touch_entity(person, actor, timestamp)
        add_activity(
            db,
            actor,
            EntityType.PERSON,
            person.id,
            ActivityAction.REPLACE_PLACES,
            timestamp,
            {"count": len(place_ids)},
        )
    db.add_all(links)
    db.flush()


def stress_role(index: int) -> str | None:
    if index % 6 == 0:
        return None
    if index % 211 == 0:
        return stress_bounded_text("Ruolo", 211, 255)
    if index % 89 == 0:
        return "Coordinatore Unicode àèìòù 漢字 🧭"
    return ("Organizzatore", "Guida", "Partecipante", "Ospite", "Testimone")[
        index % 5
    ]


def create_stress_event_participants(
    db: Session,
    actors: list[UserAccount],
    people: list[Person],
    events: list[Event],
    now: datetime,
) -> None:
    start = now - timedelta(days=18)
    links: list[PersonEvent] = []
    for index, event in enumerate(events, start=1):
        actor = actors[index % len(actors)]
        timestamp = start + timedelta(seconds=index)
        for offset in range(6):
            link_index = (index - 1) * 6 + offset + 1
            person = people[(index * 11 + offset) % len(people)]
            links.append(
                PersonEvent(
                    person_id=person.id,
                    event_id=event.id,
                    role=stress_role(link_index),
                    motivation=stress_motivation("Partecipazione evento", link_index),
                    created_at=timestamp,
                    updated_at=timestamp,
                    created_by=actor.id,
                    updated_by=actor.id,
                )
            )
        touch_entity(event, actor, timestamp)
        add_activity(
            db,
            actor,
            EntityType.EVENT,
            event.id,
            ActivityAction.REPLACE_PARTICIPANTS,
            timestamp,
            {"count": 6},
        )
    db.add_all(links)
    db.flush()


def create_stress_group_links(
    db: Session,
    actors: list[UserAccount],
    groups: list[SocialGroup],
    people: list[Person],
    epochs: list[Epoch],
    now: datetime,
) -> None:
    people_links: list[SocialGroupPerson] = []
    epoch_links: list[SocialGroupEpoch] = []
    start = now - timedelta(days=16)
    for index, group in enumerate(groups[:-1]):
        actor = actors[(index + 2) % len(actors)]
        people_timestamp = start + timedelta(seconds=index * 2)
        people_count = min(len(people), 5 + index % 46)
        person_ids = [
            people[(index * 53 + offset) % len(people)].id
            for offset in range(people_count)
        ]
        people_links.extend(
            SocialGroupPerson(
                group_id=group.id,
                person_id=person_id,
                created_at=people_timestamp,
                updated_at=people_timestamp,
                created_by=actor.id,
                updated_by=actor.id,
            )
            for person_id in person_ids
        )
        touch_entity(group, actor, people_timestamp)
        add_activity(
            db,
            actor,
            EntityType.GROUP,
            group.id,
            ActivityAction.REPLACE_GROUP_PEOPLE,
            people_timestamp,
            {"person_ids": person_ids},
        )

        epochs_timestamp = start + timedelta(seconds=index * 2 + 1)
        epoch_count = min(len(epochs), 1 + index % 10)
        epoch_ids = [
            epochs[(index * 7 + offset) % len(epochs)].id
            for offset in range(epoch_count)
        ]
        epoch_links.extend(
            SocialGroupEpoch(
                group_id=group.id,
                epoch_id=epoch_id,
                created_at=epochs_timestamp,
                updated_at=epochs_timestamp,
                created_by=actor.id,
                updated_by=actor.id,
            )
            for epoch_id in epoch_ids
        )
        touch_entity(group, actor, epochs_timestamp)
        add_activity(
            db,
            actor,
            EntityType.GROUP,
            group.id,
            ActivityAction.REPLACE_GROUP_EPOCHS,
            epochs_timestamp,
            {"epoch_ids": epoch_ids},
        )
    db.add_all(people_links)
    db.add_all(epoch_links)
    db.flush()


def create_stress_media(
    db: Session,
    actors: list[UserAccount],
    entities: dict[EntityType, list[EntityT]],
    media_dir: Path,
    now: datetime,
    count: int,
    created_files: list[Path],
) -> None:
    media_dir.mkdir(parents=True, exist_ok=True)
    per_type = count // len(EntityType)
    media_index = 0
    for entity_type in EntityType:
        items = entities[entity_type]
        unique_targets = min(len(items), max(1, per_type * 5 // 6))
        for type_index in range(per_type):
            media_index += 1
            item = items[type_index % unique_targets]
            actor = actors[(media_index + 2) % len(actors)]
            timestamp = now - timedelta(days=1) + timedelta(seconds=media_index)
            width, height = (480, 640) if media_index % 3 == 0 else (640, 360)
            path = media_dir / f"stress-immagine-{media_index:03d}.svg"
            path.write_bytes(sample_svg(media_index, width, height))
            created_files.append(path)
            asset = MediaAsset(
                pullable_id=item.id,
                filename=f"immagine-stress-{media_index:03d}.svg",
                content_type="image/svg+xml",
                disk_path=str(path.resolve()),
                created_at=timestamp,
                created_by=actor.id,
            )
            db.add(asset)
            db.flush()
            touch_entity(item, actor, timestamp)
            add_activity(
                db,
                actor,
                entity_type,
                item.id,
                ActivityAction.UPLOAD_MEDIA,
                timestamp,
                {"media_id": asset.id},
            )


def seed_stress_data(
    db: Session,
    *,
    media_dir: Path | None = None,
    now: datetime | None = None,
    scale: StressSeedScale = STRESS_SEED_SCALE,
) -> None:
    target_media_dir = (media_dir or get_settings().media_dir).resolve()
    ensure_empty_demo_target(db, target_media_dir)
    timestamp = now or utcnow()
    created_files: list[Path] = []
    try:
        users = create_demo_users(db, timestamp, stress=True)
        active_users = [user for user in users if user.is_active]
        people = create_stress_people(db, active_users, timestamp, scale.people)
        places = create_stress_places(db, active_users, timestamp, scale.places)
        epochs = create_stress_epochs(db, active_users, timestamp, scale.epochs)
        events = create_stress_events(
            db, active_users, places, epochs, timestamp, scale.events
        )
        groups = create_stress_groups(db, active_users, timestamp, scale.groups)
        create_stress_person_place_links(
            db, active_users, people, places, timestamp
        )
        create_stress_event_participants(
            db, active_users, people, events, timestamp
        )
        create_stress_group_links(
            db, active_users, groups, people, epochs, timestamp
        )
        create_stress_media(
            db,
            active_users,
            {
                EntityType.PERSON: people,
                EntityType.PLACE: places,
                EntityType.EPOCH: epochs,
                EntityType.EVENT: events,
                EntityType.GROUP: groups,
            },
            target_media_dir,
            timestamp,
            scale.media,
            created_files,
        )
        db.commit()
    except Exception:
        db.rollback()
        for path in created_files:
            path.unlink(missing_ok=True)
        try:
            target_media_dir.rmdir()
        except OSError:
            pass
        raise


def seed_demo_data(
    db: Session,
    *,
    media_dir: Path | None = None,
    now: datetime | None = None,
) -> None:
    target_media_dir = (media_dir or get_settings().media_dir).resolve()
    ensure_empty_demo_target(db, target_media_dir)
    timestamp = now or utcnow()
    created_files: list[Path] = []
    try:
        users = create_demo_users(db, timestamp)
        active_users = [user for user in users if user.is_active]
        people = create_people(db, active_users, timestamp)
        places = create_places(db, active_users, timestamp)
        epochs = create_epochs(db, active_users, timestamp)
        events = create_events(db, active_users, places, epochs, timestamp)
        groups = create_groups(db, active_users, timestamp)
        create_person_place_links(db, active_users, people, places, timestamp)
        create_event_participants(db, active_users, people, events, timestamp)
        create_group_links(db, active_users, groups, people, epochs, timestamp)
        create_media(
            db,
            active_users,
            people,
            places,
            epochs,
            events,
            groups,
            target_media_dir,
            timestamp,
            created_files,
        )
        db.commit()
    except Exception:
        db.rollback()
        for path in created_files:
            path.unlink(missing_ok=True)
        try:
            target_media_dir.rmdir()
        except OSError:
            pass
        raise


def seed_test_data(db: Session) -> None:
    timestamp = utcnow()
    admin = UserAccount(
        username="admin",
        display_name="Admin",
        password_hash=hash_password(TEST_PASSWORD),
        is_admin=True,
        is_owner=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
    db.add(admin)
    db.flush()
    people = [
        add_entity(
            db,
            Person,
            EntityType.PERSON,
            admin,
            timestamp,
            log_creation=False,
            alias=f"Persona #{index}",
            name=f"Nome #{index}",
            surname=f"Cognome #{index}",
            sex=Sex.UNKNOWN.value,
            connotation=Connotation.UNKNOWN.value,
            description=f"Descrizione generica della persona #{index}.",
        )
        for index in range(1, 4)
    ]
    places = [
        add_entity(
            db,
            Place,
            EntityType.PLACE,
            admin,
            timestamp,
            log_creation=False,
            name=f"Luogo #{index}",
            address=(
                "Via Dimostrativa #1, 10001 Città #1"
                if index == 1
                else None
            ),
            description=f"Descrizione generica del luogo #{index}.",
        )
        for index in range(1, 3)
    ]
    epoch = add_entity(
        db,
        Epoch,
        EntityType.EPOCH,
        admin,
        timestamp,
        log_creation=False,
        name="Epoca #1",
        description="Descrizione generica dell'epoca #1.",
        start_year=2025,
        end_year=2025,
    )
    event = add_entity(
        db,
        Event,
        EntityType.EVENT,
        admin,
        timestamp,
        log_creation=False,
        epoch_id=epoch.id,
        place_id=places[1].id,
        title="Evento #1",
        description="Descrizione generica dell'evento #1.",
        year=2025,
        month=8,
        day=None,
    )
    groups = [
        add_entity(
            db,
            SocialGroup,
            EntityType.GROUP,
            admin,
            timestamp,
            log_creation=False,
            name=f"Cerchia #{index}",
            description=(
                "Descrizione generica della cerchia #1."
                if index == 1
                else None
            ),
        )
        for index in range(1, 3)
    ]
    db.add(
        SocialGroupPerson(
            group_id=groups[0].id,
            person_id=people[0].id,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=admin.id,
            updated_by=admin.id,
        )
    )
    db.add(
        SocialGroupEpoch(
            group_id=groups[0].id,
            epoch_id=epoch.id,
            created_at=timestamp,
            updated_at=timestamp,
            created_by=admin.id,
            updated_by=admin.id,
        )
    )
    roles = ("Guida", "Organizzatore", None)
    for person, role in zip(people, roles, strict=True):
        db.add(
            PersonEvent(
                person_id=person.id,
                event_id=event.id,
                role=role,
                motivation="Motivazione generica." if role else None,
                created_at=timestamp,
                updated_at=timestamp,
                created_by=admin.id,
                updated_by=admin.id,
            )
        )
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load anonymized development data")
    parser.add_argument(
        "--profile",
        choices=("demo", "stress"),
        default="demo",
        help="Dataset size to load (default: demo)",
    )
    args = parser.parse_args()
    try:
        with SessionLocal() as db:
            if args.profile == "stress":
                seed_stress_data(db)
            else:
                seed_demo_data(db)
    except SeedDataError as exc:
        raise SystemExit(str(exc)) from exc
    if args.profile == "stress":
        print(
            "Seeded anonymized stress data: 5,060 entities, 30,330 relationships, "
            "and 300 media files. "
            f"Shared password: {DEMO_PASSWORD}"
        )
    else:
        print(
            "Seeded anonymized demo data. Accounts: admin, admin2, "
            f"utente1-utente6. Shared password: {DEMO_PASSWORD}"
        )


if __name__ == "__main__":
    main()
