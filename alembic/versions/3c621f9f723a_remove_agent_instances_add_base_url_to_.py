"""remove agent_instances, add base_url to agents

Revision ID: 3c621f9f723a
Revises: 1f5dcd2c842f
Create Date: 2026-05-06 22:10:19.594174
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3c621f9f723a'
down_revision: Union[str, None] = '1f5dcd2c842f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('agent_instances')
    op.add_column('agents', sa.Column('base_url', sa.String(length=2048), nullable=False))


def downgrade() -> None:
    op.drop_column('agents', 'base_url')
    op.create_table('agent_instances',
        sa.Column('agent_id', sa.String(length=255), nullable=False),
        sa.Column('instance_id', sa.String(length=255), nullable=False),
        sa.Column('base_url', sa.String(length=2048), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('agent_id', 'instance_id')
    )
