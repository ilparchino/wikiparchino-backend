from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DateTuple = tuple[int, int, int]
EpochDateConflict = Literal["before", "after"]


@dataclass(frozen=True)
class PartialDate:
    year: int | None = None
    month: int | None = None
    day: int | None = None

    @property
    def is_empty(self) -> bool:
        return self.year is None and self.month is None and self.day is None


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        is_leap = year % 400 == 0 or (year % 4 == 0 and year % 100 != 0)
        return 29 if is_leap else 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31


def validate_partial_date(value: PartialDate, label: str = "La data") -> None:
    if value.is_empty:
        return
    if value.year is None:
        raise ValueError(f"{label}: l'anno è obbligatorio")
    if value.year < 1900:
        raise ValueError(f"{label}: l'anno non può essere precedente al 1900")
    if value.month is None:
        if value.day is not None:
            raise ValueError(f"{label}: il giorno richiede anche il mese")
        return
    if value.month < 1 or value.month > 12:
        raise ValueError(f"{label}: il mese deve essere compreso tra 1 e 12")
    if value.day is None:
        return
    maximum_day = days_in_month(value.year, value.month)
    if value.day < 1 or value.day > maximum_day:
        raise ValueError(
            f"{label}: il giorno deve essere compreso tra 1 e {maximum_day}"
        )


def partial_date_bounds(value: PartialDate) -> tuple[DateTuple, DateTuple]:
    validate_partial_date(value)
    if value.year is None:
        raise ValueError("Una data vuota non ha estremi confrontabili")
    if value.month is None:
        return (value.year, 1, 1), (value.year, 12, 31)
    if value.day is None:
        return (
            (value.year, value.month, 1),
            (value.year, value.month, days_in_month(value.year, value.month)),
        )
    exact = (value.year, value.month, value.day)
    return exact, exact


def definitely_before(left: PartialDate, right: PartialDate) -> bool:
    _, left_latest = partial_date_bounds(left)
    right_earliest, _ = partial_date_bounds(right)
    return left_latest < right_earliest


def definitely_after(left: PartialDate, right: PartialDate) -> bool:
    left_earliest, _ = partial_date_bounds(left)
    _, right_latest = partial_date_bounds(right)
    return left_earliest > right_latest


def validate_epoch_range(start: PartialDate, end: PartialDate) -> None:
    validate_partial_date(start, "La data di inizio")
    validate_partial_date(end, "La data di fine")
    if not start.is_empty and not end.is_empty and definitely_after(start, end):
        raise ValueError("La data di inizio non può essere successiva alla data di fine")


def event_epoch_conflict(
    event_date: PartialDate,
    epoch_start: PartialDate,
    epoch_end: PartialDate,
) -> EpochDateConflict | None:
    validate_partial_date(event_date, "La data dell'evento")
    validate_epoch_range(epoch_start, epoch_end)
    if event_date.is_empty:
        return None
    if not epoch_start.is_empty and definitely_before(event_date, epoch_start):
        return "before"
    if not epoch_end.is_empty and definitely_after(event_date, epoch_end):
        return "after"
    return None
