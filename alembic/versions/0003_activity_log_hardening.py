"""Harden activity history and prevent relevant SQLite ID reuse.

Revision ID: 0003_activity_log_hardening
Revises: 0002_audit_activity_index
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_activity_log_hardening"
down_revision = "0002_audit_activity_index"
branch_labels = None
depends_on = None

ENTITY_TYPES = ("person", "place", "epoch", "event")
ACTIVITY_ACTIONS = (
    "create",
    "update",
    "delete",
    "replace_participants",
    "replace_places",
    "upload_media",
    "delete_media",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def validate_existing_activity() -> None:
    connection = op.get_bind()
    invalid_types = connection.execute(
        sa.text(
            f"select distinct entity_type from audit_log "
            f"where entity_type not in ({quoted(ENTITY_TYPES)})"
        )
    ).scalars().all()
    invalid_actions = connection.execute(
        sa.text(
            f"select distinct action from audit_log "
            f"where action not in ({quoted(ACTIVITY_ACTIONS)})"
        )
    ).scalars().all()
    if invalid_types or invalid_actions:
        details = []
        if invalid_types:
            details.append(f"entity types: {', '.join(sorted(invalid_types))}")
        if invalid_actions:
            details.append(f"actions: {', '.join(sorted(invalid_actions))}")
        raise RuntimeError(
            "Cannot migrate activity history with unsupported " + "; ".join(details)
        )


def create_pullable(table_name: str, *, autoincrement: bool) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rarity", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("rarity > 0", name="ck_pullable_rarity_positive"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sqlite_autoincrement=autoincrement,
    )


def create_media_asset(table_name: str, *, autoincrement: bool) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pullable_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("disk_path", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["pullable_id"],
            ["pullable.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sqlite_autoincrement=autoincrement,
    )


def create_activity_log(table_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"entity_type in ({quoted(ENTITY_TYPES)})",
            name="ck_activity_log_entity_type",
        ),
        sa.CheckConstraint(
            f"action in ({quoted(ACTIVITY_ACTIONS)})",
            name="ck_activity_log_action",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sqlite_autoincrement=True,
    )


def create_audit_log(table_name: str) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
    )


def verify_foreign_keys() -> None:
    violations = op.get_bind().exec_driver_sql("pragma foreign_key_check").all()
    if violations:
        raise RuntimeError(f"Foreign-key violations after activity migration: {violations}")


def upgrade() -> None:
    validate_existing_activity()

    create_pullable("_new_pullable", autoincrement=True)
    op.execute(
        "insert into _new_pullable "
        "(id, rarity, created_at, updated_at, created_by, updated_by) "
        "select id, rarity, created_at, updated_at, created_by, updated_by from pullable"
    )
    op.drop_table("pullable")
    op.rename_table("_new_pullable", "pullable")

    create_media_asset("_new_media_asset", autoincrement=True)
    op.execute(
        "insert into _new_media_asset "
        "(id, pullable_id, filename, content_type, disk_path, created_at, created_by) "
        "select id, pullable_id, filename, content_type, disk_path, created_at, created_by "
        "from media_asset"
    )
    op.drop_table("media_asset")
    op.rename_table("_new_media_asset", "media_asset")
    op.create_index("ix_media_asset_pullable_id", "media_asset", ["pullable_id"])

    create_activity_log("activity_log")
    op.execute(
        "insert into activity_log "
        "(id, actor_user_id, entity_type, entity_id, action, payload_json, occurred_at) "
        "select id, actor_user_id, entity_type, entity_id, action, payload_json, created_at "
        "from audit_log"
    )
    op.drop_table("audit_log")
    op.create_index(
        "ix_activity_log_actor_occurred_at",
        "activity_log",
        ["actor_user_id", "occurred_at"],
    )
    verify_foreign_keys()


def downgrade() -> None:
    create_audit_log("audit_log")
    op.execute(
        "insert into audit_log "
        "(id, actor_user_id, entity_type, entity_id, action, payload_json, created_at) "
        "select id, actor_user_id, entity_type, entity_id, action, payload_json, occurred_at "
        "from activity_log"
    )
    op.drop_table("activity_log")
    op.create_index(
        "ix_audit_log_actor_created_at",
        "audit_log",
        ["actor_user_id", "created_at"],
    )

    create_media_asset("_old_media_asset", autoincrement=False)
    op.execute(
        "insert into _old_media_asset "
        "(id, pullable_id, filename, content_type, disk_path, created_at, created_by) "
        "select id, pullable_id, filename, content_type, disk_path, created_at, created_by "
        "from media_asset"
    )
    op.drop_table("media_asset")
    op.rename_table("_old_media_asset", "media_asset")
    op.create_index("ix_media_asset_pullable_id", "media_asset", ["pullable_id"])

    create_pullable("_old_pullable", autoincrement=False)
    op.execute(
        "insert into _old_pullable "
        "(id, rarity, created_at, updated_at, created_by, updated_by) "
        "select id, rarity, created_at, updated_at, created_by, updated_by from pullable"
    )
    op.drop_table("pullable")
    op.rename_table("_old_pullable", "pullable")
    verify_foreign_keys()
