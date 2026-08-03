from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, field_validator, model_validator

from app.models import Connotation, EntityType, Sex
from app.partial_dates import PartialDate, validate_epoch_range, validate_partial_date
from app.security import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    validate_new_password,
)


NewPassword = Annotated[
    str,
    Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH),
    AfterValidator(validate_new_password),
]


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    is_admin: bool
    is_owner: bool

    model_config = {"from_attributes": True}


class AdminUserOut(UserOut):
    is_active: bool
    created_at: datetime
    updated_at: datetime
    active_session_count: int = 0


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    password: NewPassword
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Lo username non può essere vuoto")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Il nome visualizzato non può essere vuoto")
        return normalized


class AdminUserUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    is_admin: bool
    is_active: bool

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Il nome visualizzato non può essere vuoto")
        return normalized


class AdminPasswordResetIn(BaseModel):
    new_password: NewPassword


class AdminActivityOut(BaseModel):
    source: Literal["content", "account", "authentication"]
    action: str
    occurred_at: datetime
    actor: UserOut | None = None
    target: UserOut | None = None
    entity_type: EntityType | None = None
    entity_id: int | None = None
    title: str | None = None
    linkable: bool = False
    source_ip: str | None = None


class AdminActivityPage(BaseModel):
    items: list[AdminActivityOut]
    total: int
    page: int
    page_size: int


class AdminUserDetailOut(BaseModel):
    user: AdminUserOut
    content_activity: list[AdminActivityOut]
    account_activity: list[AdminActivityOut]


class AdminSummaryOut(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    admin_users: int
    active_sessions: int
    people: int
    places: int
    epochs: int
    events: int
    groups: int
    media: int
    activity_last_24h: int


class SessionRevocationOut(BaseModel):
    revoked_count: int


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


class MaintenanceStatusOut(BaseModel):
    state: Literal["available", "scheduled", "active"]
    server_time: datetime
    announced_at: datetime | None = None
    starts_at: datetime | None = None
    message: str | None = None
    login_allowed: bool
    api_available: bool


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    new_password: NewPassword


class ProfileActivityOut(BaseModel):
    entity_type: EntityType
    entity_id: int
    title: str
    action: Literal["created", "updated"]
    occurred_at: datetime


class ProfileOut(BaseModel):
    user: UserOut
    recent_activity: list[ProfileActivityOut]


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
    address: str | None = Field(default=None, max_length=500)
    description: str | None = None

    @field_validator("address", mode="before")
    @classmethod
    def normalize_address(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.isprintable():
            raise ValueError("L'indirizzo deve essere composto da caratteri stampabili su una sola riga")
        return normalized


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
    start_year: int | None = Field(default=None, ge=1900)
    start_month: int | None = Field(default=None, ge=1, le=12)
    start_day: int | None = Field(default=None, ge=1, le=31)
    end_year: int | None = Field(default=None, ge=1900)
    end_month: int | None = Field(default=None, ge=1, le=12)
    end_day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode="after")
    def validate_partial_dates(self) -> EpochBase:
        validate_epoch_range(
            PartialDate(self.start_year, self.start_month, self.start_day),
            PartialDate(self.end_year, self.end_month, self.end_day),
        )
        return self


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
        validate_partial_date(
            PartialDate(self.year, self.month, self.day),
            "La data dell'evento",
        )
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


class GroupBase(RarityMixin):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class GroupCreate(GroupBase):
    pass


class GroupUpdate(GroupBase):
    pass


class GroupOut(GroupBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_by: int | None = None
    updated_by: int | None = None

    model_config = {"from_attributes": True}


class GroupSummaryOut(GroupOut):
    people_count: int
    epoch_count: int


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


class PlacePersonIn(BaseModel):
    person_id: int
    motivation: str | None = None


class GroupPeopleUpdate(BaseModel):
    person_ids: list[int]


class GroupEpochsUpdate(BaseModel):
    epoch_ids: list[int]


class SearchResult(BaseModel):
    entity_type: EntityType
    id: int
    title: str
    subtitle: str | None = None


class EntitySearchResult(BaseModel):
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
