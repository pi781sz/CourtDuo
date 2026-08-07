"""Hand-off point into build order step 6 ("Pre-invitation checks" and
partner-name entry — not built yet). start_partner_selection() is the
single entry point step 5 calls once a player has tapped a tournament
button.

For now it just sends a temporary stub reply. Step 6 replaces this
function's body with the real partner-name-entry flow and deletes the
_temp_ pl.json key below, same as step 5 did for step 4's stub.
"""

from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.i18n import t


async def start_partner_selection(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(t("_temp_.partner_selection_stub", lang))
