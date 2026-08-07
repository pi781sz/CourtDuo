"""invitation-only schema

Replaces the browse/waiting-pool matching engine (searches, requests,
matches, account_players, accounts.role) with the invitation-only model:
one Telegram account is one PZT player, and a player invites another
named player directly. See CLAUDE.md.

Two invariants CLAUDE.md asks to be enforced "in the database, not only
in application code" are counts/lookups across sibling rows, not
something a plain column constraint can express, so they're implemented
as Postgres trigger functions:

- max 3 PENDING outgoing invitations per (inviter, tournament)
- at most one ACCEPTED invitation per tournament per player, whether
  they appear as inviter or invitee

Revision ID: b7b3692b9b12
Revises: ca66b6a7e38e
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7b3692b9b12'
down_revision: Union[str, Sequence[str], None] = 'ca66b6a7e38e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- drop the matching-engine tables, in FK-safe order ---
    op.drop_table('requests')
    op.drop_table('matches')
    op.drop_table('searches')
    op.drop_table('account_players')

    for enum_name in ('search_state', 'request_state'):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)

    # --- accounts: role -> pzt_id, searches_used -> invitations_used ---
    # Pre-launch: no bot handler creates an Account row yet, and the old
    # adult-manages-many-players model has no reliable 1:1 mapping onto
    # the new one-account-is-one-player identity model (an old account
    # could link zero, one, or several players via account_players).
    # Rather than guess a mapping, start accounts fresh.
    op.execute('DELETE FROM accounts')

    op.drop_column('accounts', 'role')
    sa.Enum(name='account_role').drop(op.get_bind(), checkfirst=True)

    op.alter_column('accounts', 'searches_used', new_column_name='invitations_used')

    op.add_column('accounts', sa.Column('pzt_id', sa.String(), nullable=False))
    op.create_foreign_key(
        'fk_accounts_pzt_id_players', 'accounts', 'players', ['pzt_id'], ['pzt_id'], ondelete='CASCADE'
    )
    op.create_unique_constraint('uq_accounts_pzt_id', 'accounts', ['pzt_id'])

    # --- invitations ---
    op.create_table(
        'invitations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inviter_pzt_id', sa.String(), nullable=False),
        sa.Column('invitee_pzt_id', sa.String(), nullable=False),
        sa.Column('tournament_guid', sa.String(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column(
            'state',
            sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED', 'EXPIRED', name='invitation_state'),
            server_default='PENDING',
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invitee_pzt_id'], ['players.pzt_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inviter_pzt_id'], ['players.pzt_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tournament_guid'], ['tournaments.guid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- pending_external_invites ---
    op.create_table(
        'pending_external_invites',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('inviter_pzt_id', sa.String(), nullable=False),
        sa.Column('typed_name', sa.String(), nullable=False),
        sa.Column('tournament_guid', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['inviter_pzt_id'], ['players.pzt_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tournament_guid'], ['tournaments.guid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # --- DB-level invariant: max 3 PENDING outgoing invitations per (inviter, tournament) ---
    op.execute(
        """
        CREATE FUNCTION enforce_max_pending_invitations() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'PENDING' THEN
                IF (
                    SELECT COUNT(*) FROM invitations
                    WHERE inviter_pzt_id = NEW.inviter_pzt_id
                      AND tournament_guid = NEW.tournament_guid
                      AND state = 'PENDING'
                      AND id IS DISTINCT FROM NEW.id
                ) >= 3 THEN
                    RAISE EXCEPTION 'max_pending_invitations_exceeded'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_max_pending_invitations
        BEFORE INSERT OR UPDATE ON invitations
        FOR EACH ROW EXECUTE FUNCTION enforce_max_pending_invitations();
        """
    )

    # --- DB-level invariant: at most one ACCEPTED invitation per tournament per player,
    # whether that player appears as inviter or invitee ---
    op.execute(
        """
        CREATE FUNCTION enforce_single_accepted_invitation() RETURNS trigger AS $$
        BEGIN
            IF NEW.state = 'ACCEPTED' THEN
                IF EXISTS (
                    SELECT 1 FROM invitations
                    WHERE tournament_guid = NEW.tournament_guid
                      AND state = 'ACCEPTED'
                      AND id IS DISTINCT FROM NEW.id
                      AND (
                          inviter_pzt_id IN (NEW.inviter_pzt_id, NEW.invitee_pzt_id)
                          OR invitee_pzt_id IN (NEW.inviter_pzt_id, NEW.invitee_pzt_id)
                      )
                ) THEN
                    RAISE EXCEPTION 'player_already_matched_for_tournament'
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_single_accepted_invitation
        BEFORE INSERT OR UPDATE ON invitations
        FOR EACH ROW EXECUTE FUNCTION enforce_single_accepted_invitation();
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute('DROP TRIGGER IF EXISTS trg_enforce_single_accepted_invitation ON invitations')
    op.execute('DROP FUNCTION IF EXISTS enforce_single_accepted_invitation()')
    op.execute('DROP TRIGGER IF EXISTS trg_enforce_max_pending_invitations ON invitations')
    op.execute('DROP FUNCTION IF EXISTS enforce_max_pending_invitations()')

    op.drop_table('pending_external_invites')
    op.drop_table('invitations')
    sa.Enum(name='invitation_state').drop(op.get_bind(), checkfirst=True)

    op.drop_constraint('uq_accounts_pzt_id', 'accounts', type_='unique')
    op.drop_constraint('fk_accounts_pzt_id_players', 'accounts', type_='foreignkey')
    op.drop_column('accounts', 'pzt_id')

    op.alter_column('accounts', 'invitations_used', new_column_name='searches_used')

    account_role = sa.Enum('rodzic', 'opiekun', 'trener', name='account_role')
    account_role.create(op.get_bind(), checkfirst=True)
    op.add_column('accounts', sa.Column('role', account_role, nullable=True))
    op.execute("UPDATE accounts SET role = 'rodzic' WHERE role IS NULL")
    op.alter_column('accounts', 'role', nullable=False)

    op.create_table(
        'account_players',
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('player_pzt_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_pzt_id'], ['players.pzt_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('account_id', 'player_pzt_id'),
    )
    op.create_table(
        'searches',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('player_pzt_id', sa.String(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column(
            'state',
            sa.Enum('OPEN', 'REQUESTED', 'MATCHED', 'REJECTED', 'EXPIRED', name='search_state'),
            server_default='OPEN',
            nullable=False,
        ),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['player_pzt_id'], ['players.pzt_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('player_pzt_id', 'event_id', name='uq_search_player_event'),
    )
    op.create_table(
        'matches',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('search_a_id', sa.Integer(), nullable=False),
        sa.Column('search_b_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['search_a_id'], ['searches.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['search_b_id'], ['searches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('search_a_id', name='uq_match_search_a'),
        sa.UniqueConstraint('search_b_id', name='uq_match_search_b'),
    )
    op.create_table(
        'requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('from_search_id', sa.Integer(), nullable=False),
        sa.Column('to_search_id', sa.Integer(), nullable=False),
        sa.Column(
            'state',
            sa.Enum('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED', 'CANCELLED', name='request_state'),
            server_default='PENDING',
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['from_search_id'], ['searches.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['to_search_id'], ['searches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('from_search_id', 'to_search_id', name='uq_request_pair'),
    )
