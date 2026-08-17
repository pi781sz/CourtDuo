"""drop support relay tables

The /pomoc support relay (CLAUDE.md, "Operations" > "Support") was built
and deployed to the test bot only; Piotr decided not to ship it, and the
bot is now feature-frozen. This migration removes the three tables the
relay added -- `support_threads`, `support_conversations`,
`support_operator_sessions` -- from wherever they exist.

Production never ran the three migrations that created these tables
(b2c4d6e8f0a2's chain moved straight from e1c3a5b7d9f2/f7478da3751a/
c9d1e3f5a7b9 without a deploy), so on production these DROPs are no-ops.
Test did run them, so on test this actually removes the tables. `IF
EXISTS` is what makes one migration correct for both starting states:
`alembic upgrade head` on a fresh database ends in the same schema either
way.

Revision ID: 9951879582e9
Revises: c9d1e3f5a7b9
Create Date: 2026-08-17 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9951879582e9'
down_revision: Union[str, Sequence[str], None] = 'c9d1e3f5a7b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('DROP TABLE IF EXISTS support_operator_sessions')
    op.execute('DROP TABLE IF EXISTS support_conversations')
    op.execute('DROP TABLE IF EXISTS support_threads')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'support_threads',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('operator_chat_id', sa.BigInteger(), nullable=False),
        sa.Column('operator_message_id', sa.BigInteger(), nullable=False),
        sa.Column('user_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('operator_chat_id', 'operator_message_id'),
    )
    op.create_table(
        'support_conversations',
        sa.Column('user_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('is_open', sa.Boolean(), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('user_telegram_id'),
    )
    op.create_table(
        'support_operator_sessions',
        sa.Column('operator_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('user_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('operator_telegram_id'),
    )
