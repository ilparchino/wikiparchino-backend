"""Add the protected Owner account role.

Revision ID: 0006_protected_owner
Revises: 0005_maintenance_mode
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_protected_owner"
down_revision = "0005_maintenance_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_account", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "is_owner",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch.create_check_constraint(
            "ck_user_account_owner_is_active_admin",
            "not is_owner or (is_admin and is_active)",
        )
    op.create_index(
        "uq_user_account_single_owner",
        "user_account",
        ["is_owner"],
        unique=True,
        sqlite_where=sa.text("is_owner = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_account_single_owner", table_name="user_account")
    with op.batch_alter_table("user_account", recreate="always") as batch:
        batch.drop_constraint(
            "ck_user_account_owner_is_active_admin",
            type_="check",
        )
        batch.drop_column("is_owner")
