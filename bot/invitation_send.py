"""Hand-off point into build order step 7 ("Invitation send / accept /
reject with atomic locking" -- not built yet). start_invitation_send() is
the single entry point step 6 (bot.partner_selection) calls once a partner
has been resolved and every pre-invitation check in CLAUDE.md's
"Pre-invitation checks" has passed.

For now it just sends a temporary stub reply. Step 7 replaces this
function's body with the real invitation-creation flow (the confirmation
screen, the "cannot be cancelled" warning, and the actual Invitation row)
and deletes the _temp_ pl.json key below, same as step 6 did for step 5's
stub.

TODO(step 7): by the time this is called, FSM state already carries
tournament_guid, category and partner_pzt_id (see
bot.partner_selection.handle_partner_candidate) -- everything the real
invitation-creation transaction needs to look up the tournament, its
Gra podwójna event, the inviter's account and the chosen partner.
"""

from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.i18n import t


async def start_invitation_send(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(t("_temp_.invitation_send_stub", lang))
