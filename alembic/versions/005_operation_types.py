"""add operation_types and target_endpoint_id

Revision ID: 005
Revises: 004
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agent_endpoints', sa.Column('operation_types', postgresql.JSONB(), nullable=False, server_default='[]'))
    op.add_column('routing_rules', sa.Column('target_endpoint_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('routing_rules', 'target_endpoint_id')
    op.drop_column('agent_endpoints', 'operation_types')
