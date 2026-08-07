"""Temporary stand-in for step 5's real tournament-place search.

TODO(step 5): delete this file once the real place-search handler
(matching tournaments as buttons, see CLAUDE.md "Tournament selection")
lands — see bot/tournament_search.py's docstring for the hand-off this
replaces.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from bot.i18n import t
from bot.lang import DEFAULT_LANG
from bot.states import TournamentSearch

router = Router(name="tournament_search_stub")


@router.message(TournamentSearch.waiting_place)
async def handle_place_stub(message: Message) -> None:
    await message.answer(t("_temp_.tournament_search_stub", DEFAULT_LANG))
