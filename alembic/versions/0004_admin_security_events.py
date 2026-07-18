"""Add administrator security events and global activity lookup.

Revision ID: 0004_admin_security_events
Revises: 0003_activity_log_hardening
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_admin_security_events"
down_revision = "0003_activity_log_hardening"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "user_created",
    "display_name_changed",
    "role_changed",
    "user_activated",
    "user_deactivated",
    "password_changed",
    "password_reset",
    "sessions_revoked",
    "login_succeeded",
    "login_failed",
    "login_rate_limited",
    "logout",
)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_index("ix_activity_log_occurred_at", "activity_log", ["occurred_at"])
    op.create_table(
        "security_event_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("attempted_username", sa.String(length=80), nullable=True),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"event_type in ({quoted(EVENT_TYPES)})",
            name="ck_security_event_log_type",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["user_account.id"],
            ondelete="SET NULL",
            onupdate="CASCADE",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_security_event_log_occurred_at", "security_event_log", ["occurred_at"])
    op.create_index(
        "ix_security_event_log_actor_occurred_at",
        "security_event_log",
        ["actor_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_security_event_log_target_occurred_at",
        "security_event_log",
        ["target_user_id", "occurred_at"],
    )
    op.create_index(
        "ix_security_event_log_rate_limit",
        "security_event_log",
        ["event_type", "source_ip", "attempted_username", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_table("security_event_log")
    op.drop_index("ix_activity_log_occurred_at", table_name="activity_log")
