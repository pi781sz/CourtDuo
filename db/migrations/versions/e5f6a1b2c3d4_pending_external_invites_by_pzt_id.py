"""pending_external_invites keyed on invitee_pzt_id, not typed_name

Build order step 9 ("Non-user invite flow and the 'they joined'
callback"): a pending row must be matched against a newly registered
account by pzt_id when that player joins. The typed name step 6's
matching already resolved to a specific `players` row (including
disambiguation), so the row should key on that player's pzt_id rather
than re-running fuzzy name matching later. `typed_name` is dropped in
favour of `invitee_pzt_id`, FK'd to `players.pzt_id` exactly like
`inviter_pzt_id` already is.

A unique constraint on (inviter_pzt_id, invitee_pzt_id, tournament_guid)
makes storing the attempt idempotent -- CLAUDE.md step 9, PART 1: "Sending
the share message twice must not create two rows."

Revision ID: e5f6a1b2c3d4
Revises: d3a8f5b2c110
Create Date: 2026-08-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd3a8f5b2c110'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Pre-launch: nothing has written a row to this table yet (build order
    # step 9 is only being implemented now), so there is no data to migrate.
    op.drop_column('pending_external_invites', 'typed_name')
    op.add_column('pending_external_invites', sa.Column('invitee_pzt_id', sa.String(), nullable=False))
    op.create_foreign_key(
        'fk_pending_external_invites_invitee_pzt_id',
        'pending_external_invites',
        'players',
        ['invitee_pzt_id'],
        ['pzt_id'],
        ondelete='CASCADE',
    )
    op.create_unique_constraint(
        'uq_pending_external_invite_inviter_invitee_tournament',
        'pending_external_invites',
        ['inviter_pzt_id', 'invitee_pzt_id', 'tournament_guid'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'uq_pending_external_invite_inviter_invitee_tournament', 'pending_external_invites', type_='unique'
    )
    op.drop_constraint('fk_pending_external_invites_invitee_pzt_id', 'pending_external_invites', type_='foreignkey')
    op.drop_column('pending_external_invites', 'invitee_pzt_id')
    op.add_column('pending_external_invites', sa.Column('typed_name', sa.String(), nullable=False))
