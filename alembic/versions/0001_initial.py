"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps(include_attribution: bool = True) -> list[sa.Column]:
    columns: list[sa.Column] = [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]
    if include_attribution:
        columns.extend(
            [
                sa.Column("created_by", sa.Integer(), nullable=True),
                sa.Column("updated_by", sa.Integer(), nullable=True),
            ]
        )
    return columns


def attribution_fks() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["user_account.id"], ondelete="SET NULL", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["user_account.id"], ondelete="SET NULL", onupdate="CASCADE"),
    ]


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=80), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_account_username", "user_account", ["username"], unique=True)

    op.create_table(
        "user_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE", onupdate="CASCADE"),
    )
    op.create_index("ix_user_session_token_hash", "user_session", ["token_hash"], unique=True)

    op.create_table(
        "pullable",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rarity", sa.Float(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("rarity > 0", name="ck_pullable_rarity_positive"),
        *attribution_fks(),
    )

    op.create_table(
        "person",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("surname", sa.String(length=255), nullable=True),
        sa.Column("sex", sa.String(length=20), nullable=False),
        sa.Column("connotation", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint("sex in ('male', 'female', 'other', 'unknown')", name="ck_person_sex"),
        sa.CheckConstraint(
            "connotation in ('positive', 'negative', 'neutral', 'unknown')", name="ck_person_connotation"
        ),
        sa.ForeignKeyConstraint(["id"], ["pullable.id"], ondelete="CASCADE", onupdate="CASCADE"),
    )

    op.create_table(
        "place",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["id"], ["pullable.id"], ondelete="CASCADE", onupdate="CASCADE"),
    )

    op.create_table(
        "epoch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["id"], ["pullable.id"], ondelete="CASCADE", onupdate="CASCADE"),
    )

    op.create_table(
        "event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("epoch_id", sa.Integer(), nullable=False),
        sa.Column("place_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("day", sa.Integer(), nullable=True),
        sa.CheckConstraint("year is null or year >= 1900", name="ck_event_year_min"),
        sa.CheckConstraint("month is null or (month between 1 and 12)", name="ck_event_month_range"),
        sa.CheckConstraint("day is null or (day between 1 and 31)", name="ck_event_day_range"),
        sa.CheckConstraint("month is null or year is not null", name="ck_event_month_requires_year"),
        sa.CheckConstraint("day is null or month is not null", name="ck_event_day_requires_month"),
        sa.ForeignKeyConstraint(["id"], ["pullable.id"], ondelete="CASCADE", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["epoch_id"], ["epoch.id"], ondelete="RESTRICT", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["place.id"], ondelete="RESTRICT", onupdate="CASCADE"),
    )

    op.create_table(
        "person_place",
        sa.Column("person_id", sa.Integer(), primary_key=True),
        sa.Column("place_id", sa.Integer(), primary_key=True),
        sa.Column("motivation", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"], ondelete="CASCADE", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["place_id"], ["place.id"], ondelete="CASCADE", onupdate="CASCADE"),
        *attribution_fks(),
    )

    op.create_table(
        "person_event",
        sa.Column("person_id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), primary_key=True),
        sa.Column("role", sa.String(length=255), nullable=True),
        sa.Column("motivation", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["person_id"], ["person.id"], ondelete="CASCADE", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["event.id"], ondelete="CASCADE", onupdate="CASCADE"),
        *attribution_fks(),
        sa.CheckConstraint("role is null or length(role) <= 255", name="ck_person_event_role_length"),
    )

    op.create_table(
        "media_asset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pullable_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("disk_path", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["pullable_id"], ["pullable.id"], ondelete="CASCADE", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user_account.id"], ondelete="SET NULL", onupdate="CASCADE"),
    )
    op.create_index("ix_media_asset_pullable_id", "media_asset", ["pullable_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_account.id"], ondelete="SET NULL", onupdate="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_index("ix_media_asset_pullable_id", table_name="media_asset")
    op.drop_table("media_asset")
    op.drop_table("person_event")
    op.drop_table("person_place")
    op.drop_table("event")
    op.drop_table("epoch")
    op.drop_table("place")
    op.drop_table("person")
    op.drop_table("pullable")
    op.drop_index("ix_user_session_token_hash", table_name="user_session")
    op.drop_table("user_session")
    op.drop_index("ix_user_account_username", table_name="user_account")
    op.drop_table("user_account")
