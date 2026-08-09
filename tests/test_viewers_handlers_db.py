"""End-to-end tests for the Podgląd menu and the read-only Moje deble a
viewer opens (CLAUDE.md, "Identity", step 10 -- allowlisted test
feature). Needs a real Postgres -- see tests/conftest.py, skipped cleanly
when TEST_DATABASE_URL is unset. Invented telegram ids/names/pzt_ids only
-- never a real PZT id (CLAUDE.md rule 4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.moje_deble import handle_moje_deble_button_press, handle_moje_deble_command
from bot.handlers.start import handle_start
from bot.handlers.viewers import (
    handle_podglad,
    handle_viewer_choose_account,
    handle_viewer_create_invite,
    handle_viewer_revoke,
)
from bot.keyboards.viewers import ViewerChooseAccountCallback, ViewerRevokeCallback
from db import crud
from db.models import Account, Player

_NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _make_message(telegram_id: int) -> MagicMock:
    message = MagicMock()
    message.from_user = MagicMock(id=telegram_id, full_name="Rodzic Testowy")
    message.answer = AsyncMock()
    return message


def _make_callback(telegram_id: int) -> MagicMock:
    callback = MagicMock()
    callback.from_user = MagicMock(id=telegram_id, full_name="Rodzic Testowy")
    callback.message = MagicMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="courtduo_test_bot"))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    return bot


async def _add_account(session: AsyncSession, pzt_id: str, telegram_id: int, full_name: str = "Testowy Gracz") -> Account:
    session.add(Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=None, gender=None))
    await session.flush()
    account = Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="M")
    session.add(account)
    await session.flush()
    return account


def _texts(mock_answer: AsyncMock) -> list[str]:
    return [call.args[0] for call in mock_answer.call_args_list]


# --- allowlist gating -----------------------------------------------------------


async def test_podglad_is_invisible_for_a_non_allowlisted_account(db_session: AsyncSession, monkeypatch):
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "SOMEONEELSE")
    await _add_account(db_session, "VHD0001", 700001)
    message = _make_message(700001)

    await handle_podglad(message, db_session)

    message.answer.assert_not_awaited()


async def test_podglad_is_invisible_for_an_unregistered_telegram_id(db_session: AsyncSession, monkeypatch):
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "VHD0002")
    message = _make_message(700002)

    await handle_podglad(message, db_session)

    message.answer.assert_not_awaited()


async def test_podglad_shows_the_menu_for_an_allowlisted_account(db_session: AsyncSession, monkeypatch):
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "vhd0003")  # lowercase -- matched case-insensitively
    await _add_account(db_session, "VHD0003", 700003)
    message = _make_message(700003)

    await handle_podglad(message, db_session)

    message.answer.assert_awaited_once()
    text = _texts(message.answer)[0]
    assert "Podgląd" in text


async def test_create_invite_is_refused_for_a_non_allowlisted_account_even_by_direct_callback(
    db_session: AsyncSession, monkeypatch
):
    # WHAT A VIEWER CANNOT DO / the allowlist gate: re-checked inside the
    # callback handler itself, not just the /podglad menu that would
    # normally have shown the button.
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "SOMEONEELSE")
    await _add_account(db_session, "VHD0004", 700004)
    callback = _make_callback(700004)
    bot = _make_bot()

    await handle_viewer_create_invite(callback, db_session, bot)

    callback.message.answer.assert_not_awaited()
    bot.get_me.assert_not_awaited()


# --- create / revoke round trip --------------------------------------------------


def _extract_link(button) -> str:
    """WhatsApp's button URL-encodes the whole share text (which embeds
    the link); Telegram's carries the link directly as its own `url`
    query param -- see bot.invite_friend, reused unchanged by the viewer
    share flow (CLAUDE.md step 10.1, PROBLEM 3)."""
    return parse_qs(urlparse(button.url).query)["url"][0]


async def test_create_invite_shares_the_link_via_whatsapp_and_telegram_not_shown_as_text(
    db_session: AsyncSession, monkeypatch
):
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "VHD0005")
    await _add_account(db_session, "VHD0005", 700005, full_name="Nowak Adam")
    callback = _make_callback(700005)
    bot = _make_bot()

    await handle_viewer_create_invite(callback, db_session, bot)

    callback.message.answer.assert_awaited_once()
    text, kwargs = callback.message.answer.call_args.args[0], callback.message.answer.call_args.kwargs
    # CLAUDE.md step 10.1, PROBLEM 3: "share the link instead of showing
    # it" -- the message text carries no raw link and no player name, only
    # the buttons do (a share message may be forwarded to anyone).
    assert "https://t.me/" not in text
    assert "Adam" not in text
    assert "Wyślij link z dostępem przez" in text

    markup = kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert [button.text for button in buttons] == ["WhatsApp", "Telegram"]

    telegram_link = _extract_link(buttons[1])
    assert telegram_link.startswith("https://t.me/courtduo_test_bot?start=")
    assert "Adam" not in buttons[0].url  # the WhatsApp share text either

    token = telegram_link.split("start=")[1]
    viewer_message = _make_message(710005)
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=710005, user_id=710005))
    await handle_start(viewer_message, state, db_session, bot, CommandObject(args=token))

    # CLAUDE.md step 10.1, PROBLEM 4: the grant notification's new wording.
    bot.send_message.assert_awaited_once()
    push_call = bot.send_message.await_args
    assert push_call.args[0] == 700005
    assert push_call.args[1] == "Rodzic Testowy ma teraz dostęp do podglądu Twojego konta CourtDuo."
    assert await crud.count_active_viewers(db_session, (await crud.get_account_by_pzt_id(db_session, "VHD0005")).id) == 1

    # CLAUDE.md step 10.1, PROBLEM 1: the freshly-bound viewer (no player
    # account of their own) gets the viewer-only keyboard, not the full one.
    viewer_message.answer.assert_awaited()
    bind_markup = viewer_message.answer.call_args_list[0].kwargs["reply_markup"]
    assert isinstance(bind_markup, ReplyKeyboardMarkup)
    rows = [[button.text for button in row] for row in bind_markup.keyboard]
    assert rows == [["Moje deble"]]


async def test_create_invite_is_refused_at_the_three_viewer_cap(db_session: AsyncSession, monkeypatch):
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "VHD0006")
    account = await _add_account(db_session, "VHD0006", 700006)
    for i in range(3):
        await crud.add_viewer(db_session, account.id, 720000 + i)

    callback = _make_callback(700006)
    await handle_viewer_create_invite(callback, db_session, _make_bot())

    assert _texts(callback.message.answer) == [
        "Masz już maksymalną liczbę 3 osób z dostępem podglądu. Odwołaj jedną z nich, aby dodać nową."
    ]


async def test_revoke_takes_effect_and_the_player_gets_a_confirmation(db_session: AsyncSession, monkeypatch):
    monkeypatch.setenv("VIEWER_ALLOWLIST_PZT_IDS", "VHD0007")
    account = await _add_account(db_session, "VHD0007", 700007)
    await crud.add_viewer(db_session, account.id, 730001)
    viewer = (await crud.get_active_viewers_for_account(db_session, account.id))[0]

    callback = _make_callback(700007)
    await handle_viewer_revoke(callback, ViewerRevokeCallback(viewer_id=viewer.id), db_session)

    texts = _texts(callback.message.answer)
    assert "Odwołano dostęp." in texts
    assert await crud.count_active_viewers(db_session, account.id) == 0


# --- read-only Moje deble --------------------------------------------------------


async def test_a_pure_viewer_gets_the_read_only_moje_deble_via_the_command(db_session: AsyncSession):
    watched = await _add_account(db_session, "VHD0008", 700008, full_name="Szewczyk Jagoda")
    await crud.add_viewer(db_session, watched.id, 740001)

    message = _make_message(740001)
    await handle_moje_deble_command(message, db_session)

    message.answer.assert_awaited_once()
    call = message.answer.call_args
    assert "Podgląd: Jagoda Szewczyk" in call.args[0]
    # No inline action buttons on the read-only screen itself -- but
    # (CLAUDE.md step 10.1, PROBLEM 1) a pure viewer's persistent reply
    # keyboard must be the viewer-only one, never the full player one.
    markup = call.kwargs.get("reply_markup")
    assert isinstance(markup, ReplyKeyboardMarkup)
    rows = [[button.text for button in row] for row in markup.keyboard]
    assert rows == [["Moje deble"]]


async def test_read_only_moje_deble_via_the_keyboard_label_press_too(db_session: AsyncSession):
    watched = await _add_account(db_session, "VHD0009", 700009, full_name="Nowak Marek")
    await crud.add_viewer(db_session, watched.id, 740002)

    message = _make_message(740002)
    await handle_moje_deble_button_press(message, db_session)

    message.answer.assert_awaited_once()
    assert "Podgląd: Marek Nowak" in message.answer.call_args.args[0]


async def test_an_unregistered_non_viewer_still_gets_the_ordinary_not_registered_message(db_session: AsyncSession):
    message = _make_message(750001)
    await handle_moje_deble_command(message, db_session)

    message.answer.assert_awaited_once()
    assert message.answer.call_args.args[0] == "Zacznij od komendy /start, aby się zarejestrować."


async def test_a_revoked_viewer_sees_nothing_immediately(db_session: AsyncSession):
    watched = await _add_account(db_session, "VHD0010", 700010)
    await crud.add_viewer(db_session, watched.id, 740003)
    viewer = (await crud.get_active_viewers_for_account(db_session, watched.id))[0]
    await crud.revoke_viewer(db_session, watched.id, viewer.id, _NOW)

    message = _make_message(740003)
    await handle_moje_deble_command(message, db_session)

    # Falls all the way through to the ordinary not-registered message --
    # nothing about the formerly-watched player is shown.
    assert message.answer.call_args.args[0] == "Zacznij od komendy /start, aby się zarejestrować."


async def test_a_viewer_watching_two_players_gets_a_chooser(db_session: AsyncSession):
    first = await _add_account(db_session, "VHD0011", 700011, full_name="Nowak Ola")
    second = await _add_account(db_session, "VHD0012", 700012, full_name="Kowalski Jan")
    await crud.add_viewer(db_session, first.id, 740004)
    await crud.add_viewer(db_session, second.id, 740004)

    message = _make_message(740004)
    await handle_moje_deble_command(message, db_session)

    message.answer.assert_awaited_once()
    call = message.answer.call_args
    assert call.args[0] == "Wybierz, czyje deble chcesz zobaczyć:"
    markup = call.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert {button.text for button in buttons} == {"Ola Nowak", "Jan Kowalski"}

    chosen_button = next(b for b in buttons if b.text == "Ola Nowak")
    callback_data = ViewerChooseAccountCallback.unpack(chosen_button.callback_data)
    callback = _make_callback(740004)
    await handle_viewer_choose_account(callback, callback_data, db_session)

    callback.message.answer.assert_awaited_once()
    assert "Podgląd: Ola Nowak" in callback.message.answer.call_args.args[0]
    # CLAUDE.md step 10.1, PROBLEM 1: 740004 has no CourtDuo account of its
    # own -- the viewer-only keyboard, not the full one.
    markup = callback.message.answer.call_args.kwargs["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert [[button.text for button in row] for row in markup.keyboard] == [["Moje deble"]]


async def test_choose_account_callback_refuses_an_account_the_tapper_does_not_watch(db_session: AsyncSession):
    watched = await _add_account(db_session, "VHD0013", 700013)
    other = await _add_account(db_session, "VHD0014", 700014)
    await crud.add_viewer(db_session, watched.id, 740005)

    callback = _make_callback(740005)
    await handle_viewer_choose_account(callback, ViewerChooseAccountCallback(account_id=other.id), db_session)

    callback.message.answer.assert_not_awaited()


async def test_a_viewer_who_is_also_a_registered_player_gets_their_own_moje_deble(db_session: AsyncSession):
    # CLAUDE.md step 10: their own account and their viewer role are
    # independent -- using the bot normally, they are always themselves.
    await _add_account(db_session, "VHD0015", 700015, full_name="Testowy Widz")
    watched = await _add_account(db_session, "VHD0016", 700016, full_name="Kowalski Jan")
    await crud.add_viewer(db_session, watched.id, 700015)

    message = _make_message(700015)
    await handle_moje_deble_command(message, db_session)

    # Their own (empty) Moje deble, not the read-only view of who they watch.
    message.answer.assert_awaited_once()
    text = message.answer.call_args.args[0]
    assert "Podgląd" not in text
    assert text == "Nie masz jeszcze żadnych zaproszeń."


async def test_a_registered_player_viewer_keeps_their_own_keyboard_while_watching_someone_else(
    db_session: AsyncSession,
):
    # CLAUDE.md step 10.1: "the only thing offered is the read-only view
    # and a way back to their own account" -- for a registered player,
    # that "way back" is simply never touching their own already-full
    # keyboard in the first place (bot.handlers.moje_deble routes them
    # back to their own account first, regardless of the viewer role).
    own = await _add_account(db_session, "VHD0017", 700017, full_name="Testowy Widz")
    watched = await _add_account(db_session, "VHD0018", 700018, full_name="Kowalski Jan")
    await crud.add_viewer(db_session, watched.id, own.telegram_id)

    callback = _make_callback(own.telegram_id)
    await handle_viewer_choose_account(
        callback, ViewerChooseAccountCallback(account_id=watched.id), db_session
    )

    callback.message.answer.assert_awaited_once()
    assert "Podgląd: Jan Kowalski" in callback.message.answer.call_args.args[0]
    assert callback.message.answer.call_args.kwargs.get("reply_markup") is None
