"""Add the profile activity lookup index.

Revision ID: 0002_audit_activity_index
Revises: 0001_initial
"""

from alembic import op

revision = "0002_audit_activity_index"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_audit_log_actor_created_at",
        "audit_log",
        ["actor_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_actor_created_at", table_name="audit_log")
