"""Add place-owned person relationship activity.

Revision ID: 0010_place_people_activity
Revises: 0009_social_groups
"""

from __future__ import annotations

from alembic import op


revision = "0010_place_people_activity"
down_revision = "0009_social_groups"
branch_labels = None
depends_on = None

OLD_ACTIONS = (
    "create",
    "update",
    "delete",
    "replace_participants",
    "replace_places",
    "replace_group_people",
    "replace_group_epochs",
    "upload_media",
    "delete_media",
)
NEW_ACTIONS = (*OLD_ACTIONS, "replace_people")


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
            f"Foreign-key violations after place-people activity migration: {violations}"
        )


def upgrade() -> None:
    recreate_action_check(NEW_ACTIONS)
    verify_foreign_keys()


def downgrade() -> None:
    has_place_people_activity = op.get_bind().exec_driver_sql(
        "select 1 from activity_log where action = 'replace_people' limit 1"
    ).first()
    if has_place_people_activity:
        raise RuntimeError(
            "Cannot downgrade 0010_place_people_activity while replace_people activity exists"
        )
    recreate_action_check(OLD_ACTIONS)
    verify_foreign_keys()
