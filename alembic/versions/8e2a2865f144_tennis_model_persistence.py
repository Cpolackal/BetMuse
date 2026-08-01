"""tennis model persistence

Revision ID: 8e2a2865f144
Revises: 73b6190bbdd5
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e2a2865f144'
down_revision: Union[str, Sequence[str], None] = '73b6190bbdd5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('market_snapshots', sa.Column('model_price', sa.Float(), nullable=True))
    op.add_column('market_snapshots', sa.Column('score_state', sa.String(), nullable=True))

    op.create_table(
        'match_events',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('event_id', sa.Integer(), index=True),
        sa.Column('ts', sa.DateTime(), index=True),
        sa.Column('state_json', sa.String()),
    )

    op.create_table(
        'market_links',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('ticker', sa.String(), unique=True, index=True),
        sa.Column('event_id', sa.Integer(), index=True),
        sa.Column('side', sa.Integer()),
        sa.Column('home', sa.String()),
        sa.Column('away', sa.String()),
        sa.Column('linked_at', sa.DateTime()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('market_links')
    op.drop_table('match_events')
    op.drop_column('market_snapshots', 'score_state')
    op.drop_column('market_snapshots', 'model_price')
