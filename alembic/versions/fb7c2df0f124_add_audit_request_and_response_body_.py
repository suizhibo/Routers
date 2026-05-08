"""add audit request and response body columns

Revision ID: fb7c2df0f124
Revises: 48764e08b1c4
Create Date: 2026-05-08 13:09:34.086578
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'fb7c2df0f124'
down_revision: Union[str, None] = '48764e08b1c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_events', sa.Column('request_body', sa.Text(), nullable=True))
    op.add_column('audit_events', sa.Column('response_body', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_events', 'response_body')
    op.drop_column('audit_events', 'request_body')
