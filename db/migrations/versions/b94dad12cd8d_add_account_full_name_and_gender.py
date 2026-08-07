"""add account full_name and gender

Step 4, "Registration by PZT ID": accounts.full_name/gender are a
snapshot taken at registration time (from the players/rankings tables),
not a live join — a player who drops off every monthly ranking list
keeps the name/gender they registered with. See db/models/accounts.py
and bot/registration.py.

Pre-launch, accounts is guaranteed empty (the previous migration,
b7b3692b9b12, deleted every row and no bot handler has created one
since), so both columns can be added NOT NULL directly with no backfill
step.

Revision ID: b94dad12cd8d
Revises: b7b3692b9b12
Create Date: 2026-08-07 08:07:04.356392

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b94dad12cd8d'
down_revision: Union[str, Sequence[str], None] = 'b7b3692b9b12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('accounts', sa.Column('full_name', sa.String(), nullable=False))
    op.add_column('accounts', sa.Column('gender', sa.String(length=1), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('accounts', 'gender')
    op.drop_column('accounts', 'full_name')
