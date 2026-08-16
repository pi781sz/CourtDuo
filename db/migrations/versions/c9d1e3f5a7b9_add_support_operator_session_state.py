"""add support_operator_sessions.state

Live testing found an open operator session silently keep delivering to
its remembered player even after a second player's message came in --
CLAUDE.md, "Operations" > "Support", "A SUSPENDED SESSION, FAILING
CLOSED". `state` ('open' / 'suspended', nullable so a row written before
this column existed reads as NULL and is treated as "open") is what lets
bot.middlewares.support_conversation fail closed instead: a message from
a player other than the one an operator's open session names now flips
that session to 'suspended', and a suspended session delivers nothing
until the operator explicitly taps a "Reply: {name}" button again.

Revision ID: c9d1e3f5a7b9
Revises: f7478da3751a
Create Date: 2026-08-16 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d1e3f5a7b9'
down_revision: Union[str, Sequence[str], None] = 'f7478da3751a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('support_operator_sessions', sa.Column('state', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('support_operator_sessions', 'state')
