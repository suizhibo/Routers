"""add request_tracking table

Revision ID: 268bc936a8b4
Revises: 98c78a39358b
Create Date: 2026-05-05 18:53:45.758891
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "268bc936a8b4"
down_revision: Union[str, None] = "98c78a39358b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_tracking",
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column("user_subject", sa.String(length=255), nullable=False),
        sa.Column("agent_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("request_id"),
    )


def downgrade() -> None:
    op.drop_table("request_tracking")
