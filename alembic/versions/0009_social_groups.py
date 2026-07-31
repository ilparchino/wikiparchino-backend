"""Add pullable social groups and their memberships.

Revision ID: 0009_social_groups
Revises: 0008_place_address
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_social_groups"
down_revision = "0008_place_address"
branch_labels = None
depends_on = None

OLD_ENTITY_TYPES = ("person", "place", "epoch", "event")
NEW_ENTITY_TYPES = (*OLD_ENTITY_TYPES, "group")
OLD_ACTIONS = (
    "create",
    "update",
    "delete",
    "replace_participants",
    "replace_places",
    "upload_media",
    "delete_media",
)
NEW_ACTIONS = (*OLD_ACTIONS, "replace_group_people", "replace_group_epochs")


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def recreate_activity_checks(
    entity_types: tuple[str, ...],
    actions: tuple[str, ...],
) -> None:
    with op.batch_alter_table(
        "activity_log",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.drop_constraint("ck_activity_log_entity_type", type_="check")
        batch.drop_constraint("ck_activity_log_action", type_="check")
        batch.create_check_constraint(
            "ck_activity_log_entity_type",
            f"entity_type in ({quoted(entity_types)})",
        )
        batch.create_check_constraint(
            "ck_activity_log_action",
            f"action in ({quoted(actions)})",
        )


def verify_foreign_keys() -> None:
    violations = op.get_bind().exec_driver_sql("pragma foreign_key_check").all()
    if violations:
        raise RuntimeError(
            f"Foreign-key violations after social-group migration: {violations}"
        )


def upgrade() -> None:
    op.create_table(
        "social_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["id"],
            ["pullable.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for table_name, target_table, target_column in (
        ("social_group_person", "person", "person_id"),
        ("social_group_epoch", "epoch", "epoch_id"),
    ):
        op.create_table(
            table_name,
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column(target_column, sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(
                ["group_id"],
                ["social_group.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                [target_column],
                [f"{target_table}.id"],
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
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
            sa.PrimaryKeyConstraint("group_id", target_column),
        )
        op.create_index(
            f"ix_{table_name}_{target_column}",
            table_name,
            [target_column],
        )
    recreate_activity_checks(NEW_ENTITY_TYPES, NEW_ACTIONS)
    verify_foreign_keys()


def downgrade() -> None:
    connection = op.get_bind()
    has_group_data = connection.exec_driver_sql(
        "select 1 from social_group limit 1"
    ).first()
    has_group_activity = connection.exec_driver_sql(
        "select 1 from activity_log "
        "where entity_type = 'group' "
        "or action in ('replace_group_people', 'replace_group_epochs') limit 1"
    ).first()
    if has_group_data or has_group_activity:
        raise RuntimeError(
            "Cannot downgrade 0009_social_groups while Cerchia data or activity exists"
        )

    recreate_activity_checks(OLD_ENTITY_TYPES, OLD_ACTIONS)
    op.drop_table("social_group_epoch")
    op.drop_table("social_group_person")
    op.drop_table("social_group")
    verify_foreign_keys()
