from __future__ import annotations

from datetime import datetime
from typing import TypeVar

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    Epoch,
    Event,
    Person,
    PersonEvent,
    Place,
    Pullable,
    UserAccount,
    utcnow,
)
from app.security import hash_password

DEMO_PASSWORD = "admin"
EntityT = TypeVar("EntityT", Person, Place, Epoch, Event)


def upsert_user(
    db: Session, username: str, display_name: str, is_admin: bool = False
) -> UserAccount:
    user = db.query(UserAccount).filter(UserAccount.username == username).first()
    if user is None:
        user = UserAccount(
            username=username,
            display_name=display_name,
            password_hash=hash_password(DEMO_PASSWORD),
            is_admin=is_admin,
        )
        db.add(user)
        db.flush()
    return user


def add_entity(
    db: Session,
    model: type[EntityT],
    actor_id: int | None,
    rarity: float = 1.0,
    **values,
) -> EntityT:
    timestamp: datetime = utcnow()
    pullable = Pullable(
        rarity=rarity,
        created_at=timestamp,
        updated_at=timestamp,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(pullable)
    db.flush()
    item = model(id=pullable.id, **values)
    db.add(item)
    db.flush()
    return item


def seed_demo_data(db: Session) -> None:
    users = [("admin", "Admin", True)]
    actor = None
    for username, display_name, is_admin in users:
        user = upsert_user(db, username, display_name, is_admin)
        actor = actor or user
    db.flush()
    actor_id = actor.id if actor else None

    if db.query(Person).count() > 0:
        db.commit()
        return

    relationship_metadata = {"created_by": actor_id, "updated_by": actor_id}

    p1 = add_entity(
        db,
        Person,
        actor_id,
        alias="Dino",
        name="Riccardo Pedone",
        sex="male",
        connotation="positive",
        description="Il custode ufficiale delle Parchino.",
    )
    p2 = add_entity(
        db,
        Person,
        actor_id,
        alias="Wat",
        name="Matteo Sestini",
        sex="male",
        connotation="positive",
        description="Il dittatore del Parchino.",
    )
    p3 = add_entity(
        db,
        Person,
        actor_id,
        alias="Leo",
        name="Leonardo Tecchi",
        sex="male",
        connotation="positive",
        description="Il calciatore/psicologo/quartierista del Parchino.",
    )
    place1 = add_entity(
        db,
        Place,
        actor_id,
        name="Parchino",
        description="Dove tutto ebbe inizio.",
    )
    place2 = add_entity(
        db,
        Place,
        actor_id,
        name="Poti",
        description="La meta della villeggiatura degli aretini.",
    )
    epoch = add_entity(
        db,
        Epoch,
        actor_id,
        name="Post-Covid",
        description="L'epoca successiva alla pandemia.",
    )

    e1 = add_entity(
        db,
        Event,
        actor_id,
        epoch_id=epoch.id,
        place_id=place2.id,
        title="APPoti APPiedi",
        description="La faticosa scampagnata verso Poti.",
        year=2025,
        month=8,
    )

    db.add_all(
        [
            PersonEvent(
                person_id=p1.id,
                event_id=e1.id,
                role="Guida",
                motivation="Ci ha sapientemente guidato attraverso la selva oscura per raggiungere Poti.",
                **relationship_metadata,
            ),
            PersonEvent(
                person_id=p2.id,
                event_id=e1.id,
                role="Condottiero",
                motivation="Ha guidato il gruppo con fermezza e determinazione.",
                **relationship_metadata,
            ),
            PersonEvent(
                person_id=p3.id,
                event_id=e1.id,
                role="Compagno di viaggio",
                motivation="Ha contribuito a rendere il viaggio più piacevole e divertente.",
                **relationship_metadata,
            ),
        ]
    )

    db.commit()


def main() -> None:
    with SessionLocal() as db:
        seed_demo_data(db)
    print("Seeded demo data. Password for demo accounts:", DEMO_PASSWORD)


if __name__ == "__main__":
    main()
