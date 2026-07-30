from __future__ import annotations

import pytest

from app.partial_dates import (
    PartialDate,
    definitely_after,
    definitely_before,
    event_epoch_conflict,
    partial_date_bounds,
    validate_epoch_range,
    validate_partial_date,
)


def test_partial_date_bounds_and_definite_comparisons() -> None:
    assert partial_date_bounds(PartialDate(2025)) == (
        (2025, 1, 1),
        (2025, 12, 31),
    )
    assert partial_date_bounds(PartialDate(2024, 2)) == (
        (2024, 2, 1),
        (2024, 2, 29),
    )
    assert partial_date_bounds(PartialDate(2025, 2)) == (
        (2025, 2, 1),
        (2025, 2, 28),
    )
    assert partial_date_bounds(PartialDate(2025, 7, 14)) == (
        (2025, 7, 14),
        (2025, 7, 14),
    )

    assert definitely_before(PartialDate(2024), PartialDate(2025, 3))
    assert not definitely_before(PartialDate(2025), PartialDate(2025, 3))
    assert definitely_after(PartialDate(2025, 4), PartialDate(2025, 3))
    assert not definitely_after(PartialDate(2025), PartialDate(2025, 3))


@pytest.mark.parametrize(
    "value",
    [
        PartialDate(None, 3, None),
        PartialDate(2025, None, 1),
        PartialDate(1899),
        PartialDate(2025, 13),
        PartialDate(2025, 4, 31),
        PartialDate(2025, 2, 29),
        PartialDate(1900, 2, 29),
    ],
)
def test_partial_date_validation_rejects_invalid_dates(value: PartialDate) -> None:
    with pytest.raises(ValueError):
        validate_partial_date(value)


def test_partial_date_validation_accepts_gregorian_leap_days() -> None:
    validate_partial_date(PartialDate())
    validate_partial_date(PartialDate(2000, 2, 29))
    validate_partial_date(PartialDate(2024, 2, 29))


def test_epoch_range_and_event_compatibility_are_conservative() -> None:
    validate_epoch_range(PartialDate(2025), PartialDate(2025, 3))
    validate_epoch_range(PartialDate(2025, 3), PartialDate(2025))
    with pytest.raises(ValueError):
        validate_epoch_range(PartialDate(2025, 4), PartialDate(2025, 3))

    assert event_epoch_conflict(
        PartialDate(2024),
        PartialDate(2025, 3),
        PartialDate(),
    ) == "before"
    assert event_epoch_conflict(
        PartialDate(2026),
        PartialDate(),
        PartialDate(2025, 10),
    ) == "after"
    assert event_epoch_conflict(
        PartialDate(2025),
        PartialDate(2025, 3),
        PartialDate(2025, 10),
    ) is None
    assert event_epoch_conflict(
        PartialDate(),
        PartialDate(2025),
        PartialDate(2025),
    ) is None
