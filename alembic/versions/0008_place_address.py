"""Add an optional address to places.

Revision ID: 0008_place_address
Revises: 0007_epoch_partial_dates
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_place_address"
down_revision = "0007_epoch_partial_dates"
branch_labels = None
depends_on = None


def verify_foreign_keys() -> None:
    violations = op.get_bind().exec_driver_sql("pragma foreign_key_check").all()
    if violations:
        raise RuntimeError(
            f"Foreign-key violations after place-address migration: {violations}"
        )


def upgrade() -> None:
    with op.batch_alter_table("place", recreate="always") as batch:
        batch.add_column(sa.Column("address", sa.String(length=500), nullable=True))
        batch.create_check_constraint(
            "ck_place_address_length",
            "address is null or length(address) <= 500",
        )
    verify_foreign_keys()


def downgrade() -> None:
    with op.batch_alter_table("place", recreate="always") as batch:
        batch.drop_constraint("ck_place_address_length", type_="check")
        batch.drop_column("address")
    verify_foreign_keys()
