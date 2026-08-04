"""Add indexes for paginated pullable queries.

Revision ID: 0011_pullable_query_indexes
Revises: 0010_place_people_activity
"""

from __future__ import annotations

from alembic import op


revision = "0011_pullable_query_indexes"
down_revision = "0010_place_people_activity"
branch_labels = None
depends_on = None


INDEX_SQL = {
    "ix_pullable_created_at_id": "create index ix_pullable_created_at_id on pullable (created_at desc, id desc)",
    "ix_pullable_updated_at_id": "create index ix_pullable_updated_at_id on pullable (updated_at desc, id desc)",
    "ix_person_alias_nocase_id": "create index ix_person_alias_nocase_id on person (alias collate nocase, id)",
    "ix_place_name_nocase_id": "create index ix_place_name_nocase_id on place (name collate nocase, id)",
    "ix_epoch_name_nocase_id": "create index ix_epoch_name_nocase_id on epoch (name collate nocase, id)",
    "ix_event_title_nocase_id": "create index ix_event_title_nocase_id on event (title collate nocase, id)",
    "ix_social_group_name_nocase_id": "create index ix_social_group_name_nocase_id on social_group (name collate nocase, id)",
    "ix_event_date_id": "create index ix_event_date_id on event (year desc, coalesce(month, 1) desc, coalesce(day, 1) desc, id desc)",
    "ix_event_place_date_id": "create index ix_event_place_date_id on event (place_id, year desc, coalesce(month, 1) desc, coalesce(day, 1) desc, id desc)",
    "ix_event_epoch_date_id": "create index ix_event_epoch_date_id on event (epoch_id, year desc, coalesce(month, 1) desc, coalesce(day, 1) desc, id desc)",
    "ix_person_event_event_person": "create index ix_person_event_event_person on person_event (event_id, person_id)",
    "ix_person_place_place_person": "create index ix_person_place_place_person on person_place (place_id, person_id)",
}


def verify_foreign_keys() -> None:
    violations = op.get_bind().exec_driver_sql("pragma foreign_key_check").all()
    if violations:
        raise RuntimeError(f"Foreign-key violations after query-index migration: {violations}")


def upgrade() -> None:
    for statement in INDEX_SQL.values():
        op.execute(statement)
    verify_foreign_keys()


def downgrade() -> None:
    for name in reversed(tuple(INDEX_SQL)):
        op.drop_index(name)
    verify_foreign_keys()
