"""add support_threads

CLAUDE.md, "Operations" > "Support": /pomoc relays one message to every
operator in `alarm_recipients()`, each as a separate DM. `support_threads`
holds one row per (operator_chat_id, operator_message_id) -- the delivered
copy each operator actually received -- so a native Telegram reply from
any one of them can be routed back to the right user. Deliberately holds
no message body: this table only answers "which user does this operator
message belong to", never a stored log of what a child wrote.

Revision ID: e1c3a5b7d9f2
Revises: b2c4d6e8f0a2
Create Date: 2026-08-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1c3a5b7d9f2'
down_revision: Union[str, Sequence[str], None] = 'b2c4d6e8f0a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('support_threads')
