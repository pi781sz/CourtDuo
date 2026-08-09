"""The persistent reply keyboard (CLAUDE.md, step 8.4, made genuinely
persistent by step 8.5) and the one inline button that survives alongside
it.

Step 8.2's inline [Menu] button — attached to every terminal message so a
player always had a way back — is gone: persistent_menu_keyboard() takes
its place. Step 8.4 attached it once, on /start, on the assumption that a
reply keyboard stays visible under every later message once Telegram has
shown it once; live testing found real gaps in that assumption -- entry
points other than /start (the /moje_deble fallback before an account
exists, unprompted invitation pushes) never sent it at all. Step 8.5 fixed
that by re-attaching it on every plain-text message a session can
plausibly start from, not only /start's own greeting -- see CLAUDE.md,
"Navigation", for exactly which messages that is and why messages that
already need an inline keyboard of their own are skipped (Telegram allows
only one `reply_markup` per message).

find_partner_keyboard is the one exception, kept for bot.handlers.moje_deble:
its own summary/empty state still needs a single "Znajdź partnera" button
rather than "Moje deble" too, since tapping "Moje deble" there would just
point back at the screen already on screen.

invitation_sent_keyboard (step 8.7) is a second, narrower exception: the
persistent reply keyboard can be collapsed by the player, and Telegram
remembers that per chat regardless of is_persistent, so it cannot be the
only way back to Moje deble. The one screen a player has just acted on and
is most likely to want to check -- "Zaproszenie zostało wysłane" -- gets
its own inline [Moje deble] button, reusing MojeDebleCallback and its
existing handler unchanged. Deliberately not added to any other message:
CLAUDE.md step 8.2 already established that mid-flow inline clutter is
worse than the dead end it solves.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot.i18n import t


class FindPartnerCallback(CallbackData, prefix="fpart"):
    pass


class MojeDebleCallback(CallbackData, prefix="mdeble"):
    pass


def find_partner_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang), callback_data=FindPartnerCallback())
    builder.adjust(1)
    return builder.as_markup()


def persistent_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """CLAUDE.md step 8.4: [Znajdź partnera] alone on its own row, [Moje
    deble] and [Zaproś na CourtDuo] sharing the next -- resize_keyboard so
    it doesn't take up the whole screen, is_persistent so it doesn't hide
    itself after one tap."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang))
    builder.button(text=t("common.moje_deble_button", lang))
    builder.button(text=t("common.invite_button", lang))
    builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def invitation_sent_keyboard(lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 8.7: belt-and-braces inline [Moje deble] button for
    the "Zaproszenie zostało wysłane" screen -- see the module docstring."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.moje_deble_button", lang), callback_data=MojeDebleCallback())
    builder.adjust(1)
    return builder.as_markup()
