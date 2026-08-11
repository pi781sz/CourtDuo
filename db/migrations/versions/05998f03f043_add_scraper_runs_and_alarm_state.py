"""add scraper_runs and alarm_state

Staleness alarm (CLAUDE.md "Operations", formerly "Not yet built"):
`scraper_runs` gets one row per real invocation of a scraper, success or
failure, written in its own transaction separate from the data write, so
bot.staleness can tell a dead scraper from a merely-empty month.
`alarm_state` is the persistent per-scraper firing/last_sent_at pair the
alarm's state machine reads and writes -- persistent rather than
in-memory, since the service runs under Restart=always and in-memory
state would re-alert on every crash-loop restart.

`ix_scraper_runs_scraper_finished_at` orders its second column DESC to
match bot.staleness's only query shape: newest row (successful or not)
for a given scraper.

Revision ID: 05998f03f043
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05998f03f043'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'scraper_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scraper', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ok', sa.Boolean(), nullable=False),
        sa.Column('items_seen', sa.Integer(), nullable=True),
        sa.Column('items_written', sa.Integer(), nullable=True),
        sa.Column('detail', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_scraper_runs_scraper_finished_at',
        'scraper_runs',
        ['scraper', sa.text('finished_at DESC')],
        unique=False,
    )

    op.create_table(
        'alarm_state',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('firing', sa.Boolean(), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('alarm_state')
    op.drop_index('ix_scraper_runs_scraper_finished_at', table_name='scraper_runs')
    op.drop_table('scraper_runs')
