"""The "Zaproś na CourtDuo" persistent-keyboard label (CLAUDE.md step 8.4,
CHANGE 2, dropped down to two share channels by step 8.5): a generic
invite, unattached to any tournament or named player -- that's build
order step 9's pending_external_invites flow, and its "they joined"
callback, neither of which this touches.

No account is required to use it (nothing here needs one beyond the
interface language), so it works even mid-registration, before the typed
PZT id has been checked.

The link is built from the bot's own username, fetched at runtime via
get_me() -- never hardcoded, so the same code is correct for both the test
and production bots. The bot never sees, stores or handles a phone number
here (CLAUDE.md, non-negotiable rule 2): the recipient is chosen in the
player's own phone/app when they tap Share.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import all_translations, t
from bot.invite_friend import share_link, share_text
from bot.keyboards.invite_friend import share_keyboard
from bot.lang import lang_for
from db import crud

router = Router(name="invite_friend")


@router.message(F.text.in_(all_translations("common.invite_button")))
async def handle_invite_friend(message: Message, session: AsyncSession, bot: Bot) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)

    me = await bot.get_me()
    link = share_link(me.username)
    text = share_text(link, lang)

    await message.answer(t("invite_friend.message", lang), reply_markup=share_keyboard(link, text, lang))
