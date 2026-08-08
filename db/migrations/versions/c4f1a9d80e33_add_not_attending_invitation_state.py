"""add NOT_ATTENDING invitation state

Build order step 7, and CLAUDE.md's "Spec change: a third invitation
response": an invitation gains a third terminal answer alongside
ACCEPTED and REJECTED.

NOT_ATTENDING is a state on one `invitations` row and nothing else. It
must never become a stored fact about a player and a tournament — no
table, no column, no flag — because it must not block, hide or filter any
future invitation to that player for that tournament (players change
their minds, enter late and withdraw). Hence this migration adds exactly
one enum label and touches nothing else.

Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction block
as long as the new label isn't *used* in the same transaction, which is
why this needs no autocommit block: the label is only written by the bot,
long after this migration commits.

Revision ID: c4f1a9d80e33
Revises: 86c53a4e872f
Create Date: 2026-08-08 09:12:41.117326

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f1a9d80e33'
down_revision: Union[str, Sequence[str], None] = '86c53a4e872f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE invitation_state ADD VALUE IF NOT EXISTS 'NOT_ATTENDING'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres cannot drop a label from an enum type, so the type is
    # rebuilt without it. Any row already answered "nie jadę na ten
    # turniej" becomes REJECTED: both are terminal, free answers that
    # close exactly one invitation and nothing else, so the invariants
    # downgraded-to code relies on still hold. Only the neutral ⚪ wording
    # the inviter saw is lost, which is display, not state.
    op.execute("UPDATE invitations SET state = 'REJECTED' WHERE state = 'NOT_ATTENDING'")
    op.execute("ALTER TYPE invitation_state RENAME TO invitation_state_old")
    sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'EXPIRED', name='invitation_state').create(op.get_bind())
    op.execute("ALTER TABLE invitations ALTER COLUMN state DROP DEFAULT")
    op.execute(
        "ALTER TABLE invitations ALTER COLUMN state TYPE invitation_state "
        "USING state::text::invitation_state"
    )
    op.execute("ALTER TABLE invitations ALTER COLUMN state SET DEFAULT 'PENDING'")
    op.execute("DROP TYPE invitation_state_old")
