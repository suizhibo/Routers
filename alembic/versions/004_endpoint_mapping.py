"""add param_mapping and session_config to agent_endpoints

Revision ID: 004
Revises: 98c78a39358b
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004'
down_revision: Union[str, None] = '268bc936a8b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_endpoints', sa.Column('param_mapping', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('agent_endpoints', sa.Column('session_config', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_endpoints', 'session_config')
    op.drop_column('agent_endpoints', 'param_mapping')
