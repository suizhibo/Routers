"""add_agent_capability_description_and_rule_target_capability

Revision ID: 4e585b8eeece
Revises: 3c621f9f723a
Create Date: 2026-05-07 14:08:38.241672
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4e585b8eeece'
down_revision: Union[str, None] = '3c621f9f723a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('capability', sa.String(length=255), nullable=True))
    op.add_column('agents', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('routing_rules', sa.Column('target_capability', sa.String(length=255), nullable=True))
    op.alter_column('routing_rules', 'target_agent_id',
                    existing_type=sa.String(length=255),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('routing_rules', 'target_agent_id',
                    existing_type=sa.String(length=255),
                    nullable=False)
    op.drop_column('routing_rules', 'target_capability')
    op.drop_column('agents', 'description')
    op.drop_column('agents', 'capability')
