"""add account_viewers.viewer_display_name

CLAUDE.md step 10.2, PROBLEM 3: the Podgląd list must show who a viewer
grant belongs to, not just a numbered slot and a date. Captures the
viewer's Telegram display name once, at bind time
(bot.viewers.bind_viewer) -- nullable, since grants made before this
column existed never captured one and the list falls back to the plain
numbered form for those.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-08-09 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('account_viewers', sa.Column('viewer_display_name', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('account_viewers', 'viewer_display_name')
