"""add account_viewers and viewer_invite_tokens

Step 10 ("Read-only viewers", allowlisted test feature; see CLAUDE.md,
"Identity"): a player may grant up to 3 other Telegram accounts read-only
visibility of their own activity. `viewer_invite_tokens` holds the
single-use, 24-hour deep-link tokens a player generates from their own
account; `account_viewers` holds the resulting grants, revocable by the
player at any time.

`uq_account_viewers_active`, a partial unique index rather than a plain
UniqueConstraint, is what lets a revoked grant free up its
(account_id, viewer_telegram_id) pair for a fresh one later -- a plain
unique constraint over all rows (including revoked ones) would refuse a
re-grant to someone who was revoked in the past.

Revision ID: f1a2b3c4d5e6
Revises: e5f6a1b2c3d4
Create Date: 2026-08-09 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'viewer_invite_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_viewer_invite_tokens_token'),
    )

    op.create_table(
        'account_viewers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('viewer_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'uq_account_viewers_active',
        'account_viewers',
        ['account_id', 'viewer_telegram_id'],
        unique=True,
        postgresql_where=sa.text('revoked_at IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_account_viewers_active', table_name='account_viewers')
    op.drop_table('account_viewers')
    op.drop_table('viewer_invite_tokens')
