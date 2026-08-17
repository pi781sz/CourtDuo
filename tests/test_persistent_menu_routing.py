"""End-to-end proof that the persistent reply keyboard's exact-text
handlers (CLAUDE.md step 8.4) win over state-scoped handlers when a tap
arrives mid another flow, and that real typed input (a place, a partner
name) is never swallowed by them. Feeds real aiogram Update objects
through the actual production Dispatcher (bot.main.build_dispatcher), so
this proves the real router registration order rather than just that each
handler function works in isolation when called directly. Needs a real
Postgres -- see tests/conftest.py, skipped cleanly when TEST_DATABASE_URL
is unset. Invented telegram ids/names/pzt_ids only.

The Dispatcher is built exactly once at import time, module-level: every
feature router (bot.handlers.navigation, .moje_deble, ...) is a
module-level singleton that aiogram permanently attaches to the first
Dispatcher that includes it, so a second build_dispatcher() call anywhere
in the same process raises. _SwappableSessionFactory lets each test still
point that one Dispatcher at its own fresh schema (tests/conftest.py's
db_sessionmaker fixture, function-scoped so tables reset between tests).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote

from aiogram import Bot
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Chat, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.main import build_dispatcher
from bot.states import PartnerSelection, TournamentSearch
from db.models import Account, AgeCategory, Player, Tournament

_TOKEN = "123456:ABCDEF1234567890abcdef1234567890ABC"


class _SwappableSessionFactory:
    """Stands in for the async_sessionmaker bot.middlewares.db.DbSessionMiddleware
    calls on every update. DbSessionMiddleware only ever calls
    `self._session_factory()` -- it never checks the type -- so this duck-types
    as one while letting each test point it at its own fresh schema."""

    current: async_sessionmaker | None = None

    def __call__(self):
        assert self.current is not None, "no test has set _session_factory.current yet"
        return self.current()


_session_factory = _SwappableSessionFactory()
_dispatcher = build_dispatcher(session_factory=_session_factory)


def _make_bot() -> Bot:
    bot = Bot(token=_TOKEN)
    # No real network calls -- bot.session is what Bot.__call__ awaits for
    # every API method (send_message, get_me, ...), so replacing it lets
    # every handler run for real without ever reaching api.telegram.org.
    bot.session = AsyncMock(return_value=MagicMock(username="courtduo_test_bot"))
    return bot


def _make_update(telegram_id: int, text: str, update_id: int) -> Update:
    chat = Chat(id=telegram_id, type="private")
    user = User(id=telegram_id, is_bot=False, first_name="Test")
    message = Message(message_id=update_id, date=datetime.now(timezone.utc), chat=chat, from_user=user, text=text)
    return Update(update_id=update_id, message=message)


def _sent_texts(bot: Bot) -> list[str]:
    """Every SendMessage's text out of bot.session's call log -- other API
    methods (GetMe, ...) don't carry a .text attribute at all."""
    texts = []
    for call in bot.session.await_args_list:
        method = call.args[1]
        text = getattr(method, "text", None)
        if text is not None:
            texts.append(text)
    return texts


def _sent_button_urls(bot: Bot) -> list[str]:
    """Every inline URL button's url out of bot.session's SendMessage call
    log -- the share link now lives on the WhatsApp/Telegram buttons, not
    in message text (CLAUDE.md step 8.5, PROBLEM 2: SMS's copyable-text
    fallback is gone)."""
    urls = []
    for call in bot.session.await_args_list:
        method = call.args[1]
        markup = getattr(method, "reply_markup", None)
        if markup is None or not hasattr(markup, "inline_keyboard"):
            continue
        for row in markup.inline_keyboard:
            for button in row:
                if button.url is not None:
                    urls.append(button.url)
    return urls


async def _add_account(session: AsyncSession, telegram_id: int, pzt_id: str, full_name: str) -> None:
    session.add(Player(pzt_id=pzt_id, full_name=full_name, club=None, age_category=None, gender=None))
    await session.flush()
    session.add(Account(telegram_id=telegram_id, pzt_id=pzt_id, full_name=full_name, gender="M", lang="pl"))
    await session.flush()
    await session.commit()


async def test_moje_deble_label_wins_over_a_typed_place(db_sessionmaker: async_sessionmaker[AsyncSession]):
    _session_factory.current = db_sessionmaker
    telegram_id = 700001
    async with db_sessionmaker() as session:
        await _add_account(session, telegram_id, "RTE0001", "Testowy Gracz")

    bot = _make_bot()
    key = StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id)
    await _dispatcher.storage.set_state(key, TournamentSearch.waiting_place.state)

    # A real player would never type this exact label as a town name --
    # it must be treated as the menu tap it is, not swallowed by the place
    # handler bound to the same FSM state.
    await _dispatcher.feed_update(bot, _make_update(telegram_id, "Moje deble", update_id=1))

    assert _sent_texts(bot) == ["Nie masz jeszcze żadnych zaproszeń."]
    # The place handler must not also have fired and changed the state.
    assert await _dispatcher.storage.get_state(key) == TournamentSearch.waiting_place.state


async def test_a_typed_place_is_not_swallowed_by_the_menu_handlers(
    db_sessionmaker: async_sessionmaker[AsyncSession],
):
    _session_factory.current = db_sessionmaker
    telegram_id = 700002
    async with db_sessionmaker() as session:
        await _add_account(session, telegram_id, "RTE0002", "Testowy Gracz")

    bot = _make_bot()
    key = StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id)
    await _dispatcher.storage.set_state(key, TournamentSearch.waiting_place.state)
    await _dispatcher.storage.set_data(key, {"category": "MLODZICY"})

    await _dispatcher.feed_update(bot, _make_update(telegram_id, "Uniejów", update_id=1))

    # An ordinary town name reaches bot.handlers.tournament_search.handle_place
    # (empty DB -- "none eligible" -- rather than silence or a menu reply).
    assert _sent_texts(bot) == [
        "Nie znaleziono żadnych turniejów spełniających kryteria w najbliższych 28 dniach."
    ]


async def test_invite_label_wins_over_a_typed_partner_name(db_sessionmaker: async_sessionmaker[AsyncSession]):
    _session_factory.current = db_sessionmaker
    telegram_id = 700003
    async with db_sessionmaker() as session:
        await _add_account(session, telegram_id, "RTE0003", "Testowy Gracz")

    bot = _make_bot()
    key = StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id)
    await _dispatcher.storage.set_state(key, PartnerSelection.waiting_name.state)
    await _dispatcher.storage.set_data(key, {"tournament_guid": "whatever"})

    await _dispatcher.feed_update(bot, _make_update(telegram_id, "Zaproś na CourtDuo", update_id=1))

    texts = _sent_texts(bot)
    assert any("Zaproś zawodnika, którego znasz do CourtDuo" in text for text in texts)
    # Not misread as a (nonexistent) player's name.
    assert not any("Nie znaleziono takiego zawodnika" in text for text in texts)
    decoded_urls = [unquote(url) for url in _sent_button_urls(bot)]
    assert any("https://t.me/courtduo_test_bot" in url for url in decoded_urls)


async def test_a_typed_partner_name_is_not_swallowed_by_the_menu_handlers(
    db_sessionmaker: async_sessionmaker[AsyncSession],
):
    _session_factory.current = db_sessionmaker
    telegram_id = 700004
    async with db_sessionmaker() as session:
        await _add_account(session, telegram_id, "RTE0004", "Testowy Gracz")
        session.add(Tournament(guid="route-t1", name="Turniej testowy", age_category=AgeCategory.MLODZICY))
        await session.commit()

    bot = _make_bot()
    key = StorageKey(bot_id=bot.id, chat_id=telegram_id, user_id=telegram_id)
    await _dispatcher.storage.set_state(key, PartnerSelection.waiting_name.state)
    await _dispatcher.storage.set_data(key, {"tournament_guid": "route-t1"})

    await _dispatcher.feed_update(bot, _make_update(telegram_id, "Jan Kowalski", update_id=1))

    # Reaches bot.handlers.partner_selection.handle_partner_name for real
    # (no such player in an empty roster -- "not found", not a menu reply).
    assert _sent_texts(bot) == ["Nie znaleziono takiego zawodnika. Sprawdź pisownię i spróbuj ponownie."]
