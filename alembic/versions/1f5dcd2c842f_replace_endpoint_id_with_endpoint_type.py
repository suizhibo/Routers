"""replace endpoint_id with endpoint_type

Revision ID: 1f5dcd2c842f
Revises: 005
Create Date: 2026-05-06 21:39:14.550753
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '1f5dcd2c842f'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_endpoints: replace endpoint_id with endpoint_type
    op.add_column('agent_endpoints', sa.Column('endpoint_type', sa.String(length=16), nullable=False))
    op.drop_column('agent_endpoints', 'endpoint_id')
    op.create_primary_key('agent_endpoints_pkey', 'agent_endpoints', ['agent_id', 'endpoint_type'])

    # audit_events: remove endpoint_id
    op.drop_column('audit_events', 'endpoint_id')

    # routing_rules: replace target_endpoint_id with target_endpoint_type
    op.add_column('routing_rules', sa.Column('target_endpoint_type', sa.String(length=16), nullable=True))
    op.drop_column('routing_rules', 'target_endpoint_id')


def downgrade() -> None:
    # routing_rules: restore target_endpoint_id
    op.add_column('routing_rules', sa.Column('target_endpoint_id', sa.VARCHAR(length=255), autoincrement=False, nullable=True))
    op.drop_column('routing_rules', 'target_endpoint_type')

    # audit_events: restore endpoint_id
    op.add_column('audit_events', sa.Column('endpoint_id', sa.VARCHAR(length=255), autoincrement=False, nullable=True))

    # agent_endpoints: restore endpoint_id
    op.drop_constraint('agent_endpoints_pkey', 'agent_endpoints', type_='primary')
    op.add_column('agent_endpoints', sa.Column('endpoint_id', sa.VARCHAR(length=255), autoincrement=False, nullable=False))
    op.create_primary_key('agent_endpoints_pkey', 'agent_endpoints', ['agent_id', 'endpoint_id'])
    op.drop_column('agent_endpoints', 'endpoint_type')
