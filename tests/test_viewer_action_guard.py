"""Tests for bot.middlewares.viewer_guard.ViewerActionGuardMiddleware
(CLAUDE.md, "Identity", step 10, WHAT A VIEWER CANNOT DO: "A viewer
callback for any action must be rejected server-side even if a button
were somehow present."). Every action callback in the app is exercised
here directly -- constructed and packed exactly as a spoofed client would,
never by tapping a real button -- to prove the guard, not any individual
handler's own account-is-None branch, is what stops a pure viewer.

Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.invitations import (
    AcceptInvitationCallback,
    CancelInvitationCallback,
    CancelSendCallback,
    ConfirmSendCallback,
    NotAttendingCallback,
    RejectInvitationCallback,
)
from bot.keyboards.navigation import FindPartnerCallback, MojeDebleCallback
from bot.keyboards.partner_selection import PartnerSelectCallback
from bot.keyboards.pending_external_invites import SendPendingExternalInviteCallback
from bot.keyboards.tournament_search import (
    CategorySelectCallback,
    ChangeCategoryCallback,
    ChangePlaceCallback,
    ShowAllTournamentsCallback,
    TournamentSelectCallback,
)
from bot.keyboards.viewers import ViewerChooseAccountCallback, ViewerCreateInviteCallback, ViewerRevokeCallback
from bot.middlewares.viewer_guard import ViewerActionGuardMiddleware
from bot.viewers import bind_viewer, create_invite_token
from db.models import Account, Player

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

# Every action callback the app defines, packed exactly as a spoofed
# client-supplied payload would be -- field values are arbitrary, since
# the guard only ever looks at the prefix.
_ACTION_CALLBACK_DATA = [
    ConfirmSendCallback().pack(),
    CancelSendCallback().pack(),
    AcceptInvitationCallback(invitation_id=1).pack(),
    RejectInvitationCallback(invitation_id=1).pack(),
    NotAttendingCallback(invitation_id=1).pack(),
    CancelInvitationCallback(invitation_id=1).pack(),
    PartnerSelectCallback(pzt_id="ABC1234").pack(),
    SendPendingExternalInviteCallback(tournament_guid="g-1", invitee_pzt_id="ABC1234").pack(),
    CategorySelectCallback(category="MLODZICY").pack(),
    TournamentSelectCallback(guid="g-1").pack(),
    ShowAllTournamentsCallback().pack(),
    ChangePlaceCallback().pack(),
    ChangeCategoryCallback().pack(),
    ViewerCreateInviteCallback().pack(),
    ViewerRevokeCallback(viewer_id=1).pack(),
    FindPartnerCallback().pack(),
    MojeDebleCallback().pack(),
]


async def _add_account(session: AsyncSession, pzt_id: str, telegram_id: int) -> Account:
    session.add(Player(pzt_id=pzt_id, full_name="Testowy Gracz", club=None, age_category=None, gender=None))
    await session.flush()
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name="Testowy Gracz", gender="M")
    session.add(account)
    await session.flush()
    return account


async def _make_viewer(session: AsyncSession, watched_pzt_id: str, watched_telegram_id: int, viewer_telegram_id: int) -> None:
    account = await _add_account(session, watched_pzt_id, watched_telegram_id)
    token = await create_invite_token(session, account)
    await bind_viewer(session, viewer_telegram_id, token.token, _NOW)


def _make_callback(telegram_id: int, data: str) -> MagicMock:
    callback = MagicMock(spec=CallbackQuery)
    callback.from_user = MagicMock(id=telegram_id)
    callback.data = data
    callback.answer = AsyncMock()
    return callback


async def _run_guard(session: AsyncSession, telegram_id: int, data: str):
    handler = AsyncMock(return_value="handled")
    callback = _make_callback(telegram_id, data)
    middleware = ViewerActionGuardMiddleware()
    result = await middleware(handler, callback, {"session": session})
    return handler, callback, result


async def test_every_action_callback_is_blocked_for_a_pure_viewer(db_session: AsyncSession):
    await _make_viewer(db_session, "GRD0001", 800001, 810001)

    for data in _ACTION_CALLBACK_DATA:
        handler, callback, result = await _run_guard(db_session, 810001, data)
        handler.assert_not_awaited()
        callback.answer.assert_awaited_once()
        assert result is None


async def test_the_viewer_choose_account_callback_is_allowed_through(db_session: AsyncSession):
    await _make_viewer(db_session, "GRD0002", 800002, 810002)

    handler, callback, result = await _run_guard(
        db_session, 810002, ViewerChooseAccountCallback(account_id=1).pack()
    )

    handler.assert_awaited_once()
    callback.answer.assert_not_awaited()
    assert result == "handled"


async def test_action_callbacks_pass_through_for_a_telegram_id_with_no_viewer_grant_at_all(db_session: AsyncSession):
    # An ordinary, unregistered stranger -- not a viewer of anyone -- must
    # not be blocked by this guard; whatever the target handler does with
    # a missing account is that handler's own business.
    handler, callback, result = await _run_guard(db_session, 820001, ConfirmSendCallback().pack())

    handler.assert_awaited_once()
    callback.answer.assert_not_awaited()


async def test_action_callbacks_pass_through_for_a_registered_players_own_account(db_session: AsyncSession):
    # CLAUDE.md step 10: a viewer_telegram_id may also be a registered
    # player in their own right -- when they act through their own
    # account, the guard must not interfere, even though the same
    # telegram_id also holds an active viewer grant elsewhere.
    await _add_account(db_session, "GRD0003", 830001)
    await _make_viewer(db_session, "GRD0004", 800004, 830001)

    handler, callback, result = await _run_guard(
        db_session, 830001, AcceptInvitationCallback(invitation_id=1).pack()
    )

    handler.assert_awaited_once()
    callback.answer.assert_not_awaited()


async def test_ignores_non_callback_events(db_session: AsyncSession):
    handler = AsyncMock(return_value="handled")
    middleware = ViewerActionGuardMiddleware()

    result = await middleware(handler, MagicMock(spec=["text"]), {"session": db_session})

    handler.assert_awaited_once()
    assert result == "handled"
