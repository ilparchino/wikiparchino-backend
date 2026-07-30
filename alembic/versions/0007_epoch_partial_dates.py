"""Add epoch partial dates and Gregorian date constraints.

Revision ID: 0007_epoch_partial_dates
Revises: 0006_protected_owner
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "0007_epoch_partial_dates"
down_revision = "0006_protected_owner"
branch_labels = None
depends_on = None


def valid_day_expression(year: str, month: str, day: str) -> str:
    return (
        f"{day} is null or {day} <= case "
        f"when {month} = 2 then "
        f"case when {year} % 400 = 0 or "
        f"({year} % 4 = 0 and {year} % 100 != 0) then 29 else 28 end "
        f"when {month} in (4, 6, 9, 11) then 30 "
        "else 31 end"
    )


def validate_existing_event_dates() -> None:
    invalid_ids = op.get_bind().execute(
        sa.text(
            "select id from event where day is not null and not ("
            + valid_day_expression("year", "month", "day")
            + ") order by id"
        )
    ).scalars().all()
    if invalid_ids:
        rendered = ", ".join(str(value) for value in invalid_ids)
        raise RuntimeError(
            "Cannot add Gregorian date validation; invalid event IDs: "
            f"{rendered}. Correct these dates before running the migration."
        )


def verify_foreign_keys() -> None:
    violations = op.get_bind().exec_driver_sql("pragma foreign_key_check").all()
    if violations:
        raise RuntimeError(
            f"Foreign-key violations after partial-date migration: {violations}"
        )


def add_epoch_constraints(batch: Any) -> None:
    for prefix in ("start", "end"):
        batch.create_check_constraint(
            f"ck_epoch_{prefix}_year_min",
            f"{prefix}_year is null or {prefix}_year >= 1900",
        )
        batch.create_check_constraint(
            f"ck_epoch_{prefix}_month_range",
            f"{prefix}_month is null or {prefix}_month between 1 and 12",
        )
        batch.create_check_constraint(
            f"ck_epoch_{prefix}_day_range",
            f"{prefix}_day is null or {prefix}_day between 1 and 31",
        )
        batch.create_check_constraint(
            f"ck_epoch_{prefix}_month_requires_year",
            f"{prefix}_month is null or {prefix}_year is not null",
        )
        batch.create_check_constraint(
            f"ck_epoch_{prefix}_day_requires_month",
            f"{prefix}_day is null or {prefix}_month is not null",
        )
        batch.create_check_constraint(
            f"ck_epoch_{prefix}_day_valid_for_month",
            valid_day_expression(
                f"{prefix}_year",
                f"{prefix}_month",
                f"{prefix}_day",
            ),
        )
    batch.create_check_constraint(
        "ck_epoch_date_order",
        "start_year is null or end_year is null or "
        "(start_year * 10000 + coalesce(start_month, 1) * 100 + "
        "coalesce(start_day, 1)) <= "
        "(end_year * 10000 + coalesce(end_month, 12) * 100 + "
        "case "
        "when end_day is not null then end_day "
        "when end_month is null then 31 "
        "when end_month = 2 then "
        "case when end_year % 400 = 0 or "
        "(end_year % 4 = 0 and end_year % 100 != 0) then 29 else 28 end "
        "when end_month in (4, 6, 9, 11) then 30 "
        "else 31 end)",
    )


def upgrade() -> None:
    validate_existing_event_dates()

    with op.batch_alter_table("epoch", recreate="always") as batch:
        batch.add_column(sa.Column("start_year", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("start_month", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("start_day", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("end_year", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("end_month", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("end_day", sa.Integer(), nullable=True))
        add_epoch_constraints(batch)

    with op.batch_alter_table("event", recreate="always") as batch:
        batch.create_check_constraint(
            "ck_event_day_valid_for_month",
            valid_day_expression("year", "month", "day"),
        )

    verify_foreign_keys()


def downgrade() -> None:
    with op.batch_alter_table("event", recreate="always") as batch:
        batch.drop_constraint("ck_event_day_valid_for_month", type_="check")

    with op.batch_alter_table("epoch", recreate="always") as batch:
        batch.drop_constraint("ck_epoch_date_order", type_="check")
        for prefix in ("start", "end"):
            batch.drop_constraint(
                f"ck_epoch_{prefix}_day_valid_for_month",
                type_="check",
            )
            batch.drop_constraint(
                f"ck_epoch_{prefix}_day_requires_month",
                type_="check",
            )
            batch.drop_constraint(
                f"ck_epoch_{prefix}_month_requires_year",
                type_="check",
            )
            batch.drop_constraint(
                f"ck_epoch_{prefix}_day_range",
                type_="check",
            )
            batch.drop_constraint(
                f"ck_epoch_{prefix}_month_range",
                type_="check",
            )
            batch.drop_constraint(
                f"ck_epoch_{prefix}_year_min",
                type_="check",
            )
        batch.drop_column("end_day")
        batch.drop_column("end_month")
        batch.drop_column("end_year")
        batch.drop_column("start_day")
        batch.drop_column("start_month")
        batch.drop_column("start_year")

    verify_foreign_keys()
