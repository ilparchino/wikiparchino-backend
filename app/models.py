from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class Connotation(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class EntityType(StrEnum):
    PERSON = "person"
    PLACE = "place"
    EVENT = "event"
    EPOCH = "epoch"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class AttributionMixin(TimestampMixin):
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True
    )


class UserAccount(Base, TimestampMixin):
    __tablename__ = "user_account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UserSession(Base):
    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[UserAccount] = relationship()


class Pullable(Base, AttributionMixin):
    __tablename__ = "pullable"
    __table_args__ = (CheckConstraint("rarity > 0", name="ck_pullable_rarity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rarity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)


class PullableEntityMixin:
    id: Mapped[int]
    pullable: Mapped[Pullable]

    @property
    def rarity(self) -> float:
        return self.pullable.rarity

    @property
    def created_at(self) -> datetime:
        return self.pullable.created_at

    @property
    def updated_at(self) -> datetime:
        return self.pullable.updated_at

    @property
    def created_by(self) -> int | None:
        return self.pullable.created_by

    @property
    def updated_by(self) -> int | None:
        return self.pullable.updated_by


class Person(Base, PullableEntityMixin):
    __tablename__ = "person"
    __table_args__ = (
        CheckConstraint("sex in ('male', 'female', 'other', 'unknown')", name="ck_person_sex"),
        CheckConstraint(
            "connotation in ('positive', 'negative', 'neutral', 'unknown')", name="ck_person_connotation"
        ),
    )

    id: Mapped[int] = mapped_column(
        ForeignKey("pullable.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    surname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sex: Mapped[str] = mapped_column(String(20), default=Sex.UNKNOWN.value, nullable=False)
    connotation: Mapped[str] = mapped_column(String(20), default=Connotation.UNKNOWN.value, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    pullable: Mapped[Pullable] = relationship()


class Place(Base, PullableEntityMixin):
    __tablename__ = "place"

    id: Mapped[int] = mapped_column(
        ForeignKey("pullable.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    pullable: Mapped[Pullable] = relationship()


class Epoch(Base, PullableEntityMixin):
    __tablename__ = "epoch"

    id: Mapped[int] = mapped_column(
        ForeignKey("pullable.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    pullable: Mapped[Pullable] = relationship()


class Event(Base, PullableEntityMixin):
    __tablename__ = "event"
    __table_args__ = (
        CheckConstraint("year is null or year >= 1900", name="ck_event_year_min"),
        CheckConstraint("month is null or (month between 1 and 12)", name="ck_event_month_range"),
        CheckConstraint("day is null or (day between 1 and 31)", name="ck_event_day_range"),
        CheckConstraint("month is null or year is not null", name="ck_event_month_requires_year"),
        CheckConstraint("day is null or month is not null", name="ck_event_day_requires_month"),
    )

    id: Mapped[int] = mapped_column(
        ForeignKey("pullable.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    epoch_id: Mapped[int] = mapped_column(ForeignKey("epoch.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)
    place_id: Mapped[int] = mapped_column(ForeignKey("place.id", ondelete="RESTRICT", onupdate="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day: Mapped[int | None] = mapped_column(Integer, nullable=True)

    epoch: Mapped[Epoch] = relationship()
    place: Mapped[Place] = relationship()
    pullable: Mapped[Pullable] = relationship()


class PersonPlace(Base, AttributionMixin):
    __tablename__ = "person_place"

    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    place_id: Mapped[int] = mapped_column(
        ForeignKey("place.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    person: Mapped[Person] = relationship()
    place: Mapped[Place] = relationship()


class PersonEvent(Base, AttributionMixin):
    __tablename__ = "person_event"
    __table_args__ = (
        CheckConstraint("role is null or length(role) <= 255", name="ck_person_event_role_length"),
    )

    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    event_id: Mapped[int] = mapped_column(
        ForeignKey("event.id", ondelete="CASCADE", onupdate="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    person: Mapped[Person] = relationship()
    event: Mapped[Event] = relationship()


class MediaAsset(Base):
    __tablename__ = "media_asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pullable_id: Mapped[int] = mapped_column(ForeignKey("pullable.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    disk_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True
    )

    pullable: Mapped[Pullable] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL", onupdate="CASCADE"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
