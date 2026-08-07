"""Hand-off point into build order step 5 ("Tournament selection by
place" — not built yet). start_tournament_search() is the single entry
point step 4 calls after a successful registration and on /start for an
already-registered player.

For now it just asks for a place and parks the conversation in
TournamentSearch.waiting_place, where bot/handlers/tournament_search.py
has a temporary stub reply. Step 5 replaces this function's body with
the real place lookup and deletes that stub.
"""

from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.i18n import t
from bot.states import TournamentSearch


async def start_tournament_search(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(t("tournament_search.ask_place", lang))
    await state.set_state(TournamentSearch.waiting_place)
