"""Add relationship pagination indexes and delta activity actions.

Revision ID: 0012_relationship_pagination
Revises: 0011_pullable_query_indexes
"""

from __future__ import annotations

from alembic import op


revision = "0012_relationship_pagination"
down_revision = "0011_pullable_query_indexes"
branch_labels = None
depends_on = None

OLD_ACTIONS = (
    "create",
    "update",
    "delete",
    "replace_participants",
    "replace_places",
    "replace_people",
    "replace_group_people",
    "replace_group_epochs",
    "upload_media",
    "delete_media",
)
DELTA_ACTIONS = (
    "change_participants",
    "change_places",
    "change_people",
    "change_group_people",
    "change_group_epochs",
)
NEW_ACTIONS = (*OLD_ACTIONS, *DELTA_ACTIONS)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def recreate_action_check(actions: tuple[str, ...]) -> None:
    with op.batch_alter_table(
        "activity_log",
        recreate="always",
        table_kwargs={"sqlite_autoincrement": True},
    ) as batch:
        batch.drop_constraint("ck_activity_log_action", type_="check")
        batch.create_check_constraint(
            "ck_activity_log_action",
            f"action in ({quoted(actions)})",
        )


def verify_foreign_keys() -> None:
    violations = op.get_bind().exec_driver_sql("pragma foreign_key_check").all()
    if violations:
        raise RuntimeError(
            f"Foreign-key violations after relationship pagination migration: {violations}"
        )


def upgrade() -> None:
    op.drop_index("ix_social_group_person_person_id", table_name="social_group_person")
    op.create_index(
        "ix_social_group_person_person_group",
        "social_group_person",
        ["person_id", "group_id"],
    )
    op.drop_index("ix_social_group_epoch_epoch_id", table_name="social_group_epoch")
    op.create_index(
        "ix_social_group_epoch_epoch_group",
        "social_group_epoch",
        ["epoch_id", "group_id"],
    )
    recreate_action_check(NEW_ACTIONS)
    verify_foreign_keys()


def downgrade() -> None:
    placeholders = ", ".join("?" for _ in DELTA_ACTIONS)
    unsupported = op.get_bind().exec_driver_sql(
        f"select action from activity_log where action in ({placeholders}) limit 1",
        DELTA_ACTIONS,
    ).first()
    if unsupported:
        raise RuntimeError(
            "Cannot downgrade 0012_relationship_pagination while delta relationship "
            f"activity '{unsupported[0]}' exists"
        )

    recreate_action_check(OLD_ACTIONS)
    op.drop_index(
        "ix_social_group_epoch_epoch_group", table_name="social_group_epoch"
    )
    op.create_index(
        "ix_social_group_epoch_epoch_id",
        "social_group_epoch",
        ["epoch_id"],
    )
    op.drop_index(
        "ix_social_group_person_person_group", table_name="social_group_person"
    )
    op.create_index(
        "ix_social_group_person_person_id",
        "social_group_person",
        ["person_id"],
    )
    verify_foreign_keys()
