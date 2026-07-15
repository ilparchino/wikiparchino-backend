from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import Connotation, EntityType, Sex


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool

    model_config = {"from_attributes": True}


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


class RarityMixin(BaseModel):
    rarity: float = Field(default=1.0, gt=0)


class PersonBase(RarityMixin):
    alias: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    surname: str | None = Field(default=None, max_length=255)
    sex: Sex = Sex.UNKNOWN
    connotation: Connotation = Connotation.UNKNOWN
    description: str | None = None


class PersonCreate(PersonBase):
    pass


class PersonUpdate(PersonBase):
    pass


class PersonOut(PersonBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int | None = None
    updated_by: int | None = None

    model_config = {"from_attributes": True}


class PlaceBase(RarityMixin):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class PlaceCreate(PlaceBase):
    pass


class PlaceUpdate(PlaceBase):
    pass


class PlaceOut(PlaceBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int | None = None
    updated_by: int | None = None

    model_config = {"from_attributes": True}


class EpochBase(RarityMixin):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class EpochCreate(EpochBase):
    pass


class EpochUpdate(EpochBase):
    pass


class EpochOut(EpochBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int | None = None
    updated_by: int | None = None

    model_config = {"from_attributes": True}


class EventBase(RarityMixin):
    epoch_id: int
    place_id: int
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    year: int | None = Field(default=None, ge=1900)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def validate_partial_date(self) -> EventBase:
        if self.month is not None and self.year is None:
            raise ValueError("month requires year")
        if self.day is not None and self.month is None:
            raise ValueError("day requires month")
        return self


class EventCreate(EventBase):
    pass


class EventUpdate(EventBase):
    pass


class EventOut(EventBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int | None = None
    updated_by: int | None = None
    place: PlaceOut | None = None
    epoch: EpochOut | None = None

    model_config = {"from_attributes": True}


class PullableOut(BaseModel):
    id: int
    rarity: float
    created_at: datetime
    updated_at: datetime
    created_by: int | None = None
    updated_by: int | None = None

    model_config = {"from_attributes": True}


class OptionalParticipantRole(BaseModel):
    role: str | None = Field(default=None, max_length=255)

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class EventParticipantIn(OptionalParticipantRole):
    person_id: int
    motivation: str | None = None


class EventParticipantOut(EventParticipantIn):
    event_id: int
    person: PersonOut | None = None

    model_config = {"from_attributes": True}


class PersonEventOut(OptionalParticipantRole):
    person_id: int
    event_id: int
    motivation: str | None = None
    event: EventOut | None = None

    model_config = {"from_attributes": True}


class PersonPlaceIn(BaseModel):
    place_id: int
    motivation: str | None = None


class PersonPlaceOut(PersonPlaceIn):
    person_id: int
    place: PlaceOut | None = None

    model_config = {"from_attributes": True}


class PlacePersonOut(BaseModel):
    person_id: int
    place_id: int
    motivation: str | None = None
    person: PersonOut | None = None

    model_config = {"from_attributes": True}


class SearchResult(BaseModel):
    entity_type: EntityType
    id: int
    title: str
    subtitle: str | None = None


class PullResult(BaseModel):
    entity_type: EntityType
    id: int
    title: str
    rarity: float
    mode: Literal["random", "daily"]


class MediaOut(BaseModel):
    id: int
    pullable_id: int
    filename: str
    content_type: str
    created_at: datetime

    model_config = {"from_attributes": True}
