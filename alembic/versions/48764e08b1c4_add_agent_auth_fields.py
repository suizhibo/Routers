"""add_agent_auth_fields

Revision ID: 48764e08b1c4
Revises: 4e585b8eeece
Create Date: 2026-05-07 15:34:41.498102
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '48764e08b1c4'
down_revision: Union[str, None] = '4e585b8eeece'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('auth_header', sa.String(length=255), nullable=True))
    op.add_column('agents', sa.Column('auth_token', sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'auth_token')
    op.drop_column('agents', 'auth_header')
