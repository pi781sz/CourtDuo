"""add invitations.invitee_message_id

CLAUDE.md step 8.6 ("Cancel a pending invitation"): withdrawing a PENDING
invitation should, best-effort, strip the three answer buttons off the
notification the invitee already has on screen. That requires knowing
which Telegram message that was -- this column records the message id
the original push landed as (bot.handlers.invitations.handle_confirm_send).

Nullable throughout: an invitation whose push failed is cancelled with no
message to point at, and every row written before this migration has none
either. A cancel with no id here simply skips the edit -- the accept/
reject/cancel transaction's own re-check is what actually prevents a
stale tap, this column only makes the screen match reality sooner.

Revision ID: d3a8f5b2c110
Revises: c4f1a9d80e33
Create Date: 2026-08-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3a8f5b2c110'
down_revision: Union[str, Sequence[str], None] = 'c4f1a9d80e33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('invitations', sa.Column('invitee_message_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('invitations', 'invitee_message_id')
