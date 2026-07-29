"""Add persistent maintenance windows.

Revision ID: 0005_maintenance_mode
Revises: 0004_admin_security_events
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_maintenance_mode"
down_revision = "0004_admin_security_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_window",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("open_slot", sa.Integer(), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sessions_revoked_count", sa.Integer(), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "telegram_schedule_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("telegram_schedule_message_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_end_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_end_message_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "starts_at >= announced_at",
            name="ck_maintenance_window_start_after_announcement",
        ),
        sa.CheckConstraint(
            "message is null or length(message) <= 500",
            name="ck_maintenance_window_message_length",
        ),
        sa.CheckConstraint(
            "(ended_at is null and open_slot = 1) or "
            "(ended_at is not null and open_slot is null)",
            name="ck_maintenance_window_open_slot",
        ),
        sa.CheckConstraint(
            "ended_at is null or ended_at >= announced_at",
            name="ck_maintenance_window_end_after_announcement",
        ),
        sa.CheckConstraint(
            "(sessions_revoked_at is null and sessions_revoked_count is null) or "
            "(sessions_revoked_at is not null and sessions_revoked_count >= 0)",
            name="ck_maintenance_window_session_revocation",
        ),
        sa.UniqueConstraint("open_slot", name="uq_maintenance_window_open_slot"),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_maintenance_window_announced_at",
        "maintenance_window",
        ["announced_at"],
    )


def downgrade() -> None:
    op.drop_table("maintenance_window")
