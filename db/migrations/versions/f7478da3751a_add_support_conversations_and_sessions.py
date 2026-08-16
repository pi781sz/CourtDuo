"""add support_conversations and support_operator_sessions

CLAUDE.md, "Operations" > "Support": the open conversation on both sides
of /pomoc. `support_conversations` holds one row per player Telegram id
-- whether their plain text right now should be relayed to support, lazily
expired after 30 minutes of inactivity. `support_operator_sessions` holds
one row per operator currently in an open reply conversation with a
player, lazily expired after 60 minutes. Both are tables rather than FSM
state or an in-memory dict for the same reason `support_threads` and
`alarm_state` already are: the bot runs under `Restart=always` and the
Dispatcher uses `MemoryStorage`, so anything kept only in memory would
silently reroute a child's next message after every restart. Neither
table stores a message body -- same as `support_threads`.

Revision ID: f7478da3751a
Revises: e1c3a5b7d9f2
Create Date: 2026-08-16 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7478da3751a'
down_revision: Union[str, Sequence[str], None] = 'e1c3a5b7d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
        sa.PrimaryKeyConstraint('operator_telegram_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('support_operator_sessions')
    op.drop_table('support_conversations')
