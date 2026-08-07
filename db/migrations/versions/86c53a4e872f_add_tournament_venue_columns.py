"""add tournament venue columns

Step 4.5: the bot needs a town to match a typed place against, and the
only location column that existed (wojewodztwo) is a województwo — 16
regions, far too coarse (CLAUDE.md, "Tournament selection"). PZT's
"Miejsce turnieju" row carries the actual address; venue_city is the town
extracted from it by scrapers.tournaments.parser.extract_city, venue_address
keeps the raw string for display. Both nullable — PZT sometimes omits the
row, and the extraction can fail to find anything usable.

Revision ID: 86c53a4e872f
Revises: b94dad12cd8d
Create Date: 2026-08-07 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '86c53a4e872f'
down_revision: Union[str, Sequence[str], None] = 'b94dad12cd8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tournaments', sa.Column('venue_address', sa.String(), nullable=True))
    op.add_column('tournaments', sa.Column('venue_city', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tournaments', 'venue_city')
    op.drop_column('tournaments', 'venue_address')
