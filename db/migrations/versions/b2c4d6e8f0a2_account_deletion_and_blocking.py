"""account deletion and blocking

CLAUDE.md step 12 ("Account deletion and blocking"):

- `blocked_pzt_ids`: a standalone table, not a column on `accounts`,
  because blocking must survive the very deletion this migration also
  supports -- an `accounts` row for a blocked-and-deleted pzt_id no longer
  exists to carry a flag. Written only by a human at psql (see
  docs/RUNBOOK.md); the bot only ever reads it.
- `invitations.inviter_name_snapshot` / `invitee_name_snapshot`: a name
  snapshot taken only when that side's account is deleted, so a
  still-open invitation (a confirmed match that CLAUDE.md step 12
  deliberately does not cancel) can keep showing who the other player was
  without an evergreen dependency on `players.full_name`. Purged once the
  tournament finishes -- see db.models.invitations' module docstring.

Revision ID: b2c4d6e8f0a2
Revises: 05998f03f043
Create Date: 2026-08-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c4d6e8f0a2'
down_revision: Union[str, Sequence[str], None] = '05998f03f043'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'blocked_pzt_ids',
        sa.Column('pzt_id', sa.String(), nullable=False),
        sa.Column('blocked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('pzt_id'),
    )

    op.add_column('invitations', sa.Column('inviter_name_snapshot', sa.String(), nullable=True))
    op.add_column('invitations', sa.Column('invitee_name_snapshot', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('invitations', 'invitee_name_snapshot')
    op.drop_column('invitations', 'inviter_name_snapshot')
    op.drop_table('blocked_pzt_ids')
