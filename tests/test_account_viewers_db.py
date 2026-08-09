"""bot.viewers and its db.crud functions: token issuance, binding,
revocation, and notification forwarding (CLAUDE.md, "Identity", step 10).
Needs a real Postgres -- see tests/conftest.py, skipped cleanly when
TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from bot.viewers import ViewerBindOutcome, bind_viewer, create_invite_token, forward_to_viewers, generate_token, invite_link
from db import crud
from db.models import Account, Player

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


async def _add_account(session: AsyncSession, pzt_id: str, telegram_id: int) -> Account:
    session.add(Player(pzt_id=pzt_id, full_name="Testowy Gracz", club=None, age_category=None, gender=None))
    await session.flush()
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name="Testowy Gracz", gender="M")
    session.add(account)
    await session.flush()
    return account


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    return bot


# --- pure helpers -----------------------------------------------------------------


def test_invite_link_never_hardcodes_the_bot_username():
    assert invite_link("courtduo_test_bot", "tok123") == "https://t.me/courtduo_test_bot?start=tok123"


def test_generate_token_is_unique_and_url_safe():
    a, b = generate_token(), generate_token()
    assert a != b
    assert all(c.isalnum() or c in "-_" for c in a)


# --- create_invite_token ------------------------------------------------------------


async def test_create_invite_token_is_refused_at_the_three_viewer_cap(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0001", 900001)
    for i in range(3):
        token = await create_invite_token(db_session, account)
        assert token is not None
        await crud.add_viewer(db_session, account.id, 910000 + i)

    assert await create_invite_token(db_session, account) is None


# --- bind_viewer --------------------------------------------------------------------


async def test_bind_viewer_with_a_valid_token_grants_access(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0002", 900002)
    token = await create_invite_token(db_session, account)

    result = await bind_viewer(db_session, 920001, token.token, _NOW)

    assert result.outcome is ViewerBindOutcome.BOUND
    assert result.watched_account.id == account.id
    assert await crud.count_active_viewers(db_session, account.id) == 1


async def test_bind_viewer_token_is_single_use(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0003", 900003)
    token = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 920002, token.token, _NOW)

    second = await bind_viewer(db_session, 920003, token.token, _NOW)

    assert second.outcome is ViewerBindOutcome.INVALID
    assert await crud.count_active_viewers(db_session, account.id) == 1
    assert await crud.get_active_viewer_grants_for_telegram_id(db_session, 920003) == []


async def test_bind_viewer_expired_token_is_invalid_and_changes_nothing(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0004", 900004)
    token = await create_invite_token(db_session, account)
    past_expiry = token.expires_at + timedelta(seconds=1)

    result = await bind_viewer(db_session, 920004, token.token, past_expiry)

    assert result.outcome is ViewerBindOutcome.INVALID
    assert await crud.count_active_viewers(db_session, account.id) == 0


async def test_bind_viewer_unknown_token_is_invalid(db_session: AsyncSession):
    result = await bind_viewer(db_session, 920005, "does-not-exist-at-all", _NOW)

    assert result.outcome is ViewerBindOutcome.INVALID
    assert result.watched_account is None


async def test_bind_viewer_refuses_a_fourth_viewer_even_with_an_unconsumed_token(db_session: AsyncSession):
    # Two outstanding tokens for the same account, both unconsumed until
    # now -- CLAUDE.md's 3-viewer cap must hold even though
    # create_invite_token's own check passed for each of them individually.
    account = await _add_account(db_session, "VWR0005", 900005)
    for i in range(3):
        token = await create_invite_token(db_session, account)
        await bind_viewer(db_session, 930000 + i, token.token, _NOW)
    assert await crud.count_active_viewers(db_session, account.id) == 3

    fourth_token = await crud.create_viewer_invite_token(
        db_session, account.id, "manual-fourth-token", _NOW + timedelta(hours=1)
    )

    result = await bind_viewer(db_session, 930099, fourth_token.token, _NOW)

    assert result.outcome is ViewerBindOutcome.INVALID
    assert await crud.count_active_viewers(db_session, account.id) == 3
    # The token is still burned even though the bind was refused (CLAUDE.md:
    # "The token is consumed" -- an attempt is an attempt).
    refetched = await crud.get_viewer_invite_token(db_session, "manual-fourth-token")
    assert refetched.consumed_at is not None


async def test_binding_an_already_active_viewer_again_is_a_harmless_noop(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0006", 900006)
    first_token = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 940001, first_token.token, _NOW)
    second_token = await create_invite_token(db_session, account)

    result = await bind_viewer(db_session, 940001, second_token.token, _NOW)

    assert result.outcome is ViewerBindOutcome.BOUND
    assert await crud.count_active_viewers(db_session, account.id) == 1


# --- revoke_viewer --------------------------------------------------------------------


async def test_revoke_viewer_takes_effect_immediately(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0007", 900007)
    token = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 950001, token.token, _NOW)
    viewer = (await crud.get_active_viewers_for_account(db_session, account.id))[0]

    revoked = await crud.revoke_viewer(db_session, account.id, viewer.id, _NOW)

    assert revoked is not None
    assert await crud.count_active_viewers(db_session, account.id) == 0
    assert await crud.get_active_viewer_grants_for_telegram_id(db_session, 950001) == []


async def test_revoke_viewer_refuses_a_grant_belonging_to_another_account(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0008", 900008)
    other_account = await _add_account(db_session, "VWR0009", 900009)
    token = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 960001, token.token, _NOW)
    viewer = (await crud.get_active_viewers_for_account(db_session, account.id))[0]

    result = await crud.revoke_viewer(db_session, other_account.id, viewer.id, _NOW)

    assert result is None
    assert await crud.count_active_viewers(db_session, account.id) == 1


async def test_a_revoked_viewer_slot_can_be_re_granted(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0010", 900010)
    first_token = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 965001, first_token.token, _NOW)
    viewer = (await crud.get_active_viewers_for_account(db_session, account.id))[0]
    await crud.revoke_viewer(db_session, account.id, viewer.id, _NOW)

    second_token = await create_invite_token(db_session, account)
    result = await bind_viewer(db_session, 965001, second_token.token, _NOW)

    assert result.outcome is ViewerBindOutcome.BOUND
    assert await crud.count_active_viewers(db_session, account.id) == 1


# --- forward_to_viewers --------------------------------------------------------------


async def test_forward_to_viewers_sends_verbatim_text_with_no_buttons(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0011", 900011)
    token = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 970001, token.token, _NOW)

    bot = _make_bot()
    await forward_to_viewers(bot, db_session, account.id, "hello viewer")

    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    chat_id = call.args[0] if call.args else call.kwargs["chat_id"]
    text = call.args[1] if len(call.args) > 1 else call.kwargs["text"]
    assert chat_id == 970001
    assert text == "hello viewer"
    assert call.kwargs.get("reply_markup") is None


async def test_forward_to_viewers_skips_a_revoked_viewer(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0012", 900012)
    token1 = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 980001, token1.token, _NOW)
    token2 = await create_invite_token(db_session, account)
    await bind_viewer(db_session, 980002, token2.token, _NOW)
    to_revoke = next(
        v for v in await crud.get_active_viewers_for_account(db_session, account.id) if v.viewer_telegram_id == 980002
    )
    await crud.revoke_viewer(db_session, account.id, to_revoke.id, _NOW)

    bot = _make_bot()
    await forward_to_viewers(bot, db_session, account.id, "still active only")

    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    chat_id = call.args[0] if call.args else call.kwargs["chat_id"]
    assert chat_id == 980001


async def test_forward_to_viewers_is_a_noop_with_no_active_viewers(db_session: AsyncSession):
    account = await _add_account(db_session, "VWR0013", 900013)

    bot = _make_bot()
    await forward_to_viewers(bot, db_session, account.id, "nobody watching")

    bot.send_message.assert_not_awaited()
