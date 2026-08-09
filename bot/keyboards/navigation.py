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

viewer_menu_keyboard (step 10.1) is the reply keyboard for the other side
of "whose account is in play" (CLAUDE.md, "Identity"): a Telegram account
with no CourtDuo player account of its own, holding only a read-only
viewer grant. It never gets persistent_menu_keyboard -- Znajdź partnera
and Zaproś na CourtDuo both start flows a viewer cannot complete -- only
the one label that already opens the read-only Moje deble a viewer is
allowed to see. A registered player who is also a viewer is never shown
this keyboard: their own flows keep persistent_menu_keyboard unchanged
(CLAUDE.md: "using the bot normally, they are always themselves"), and
tapping "Moje deble" there already resolves to their own account first
(bot.handlers.moje_deble), which doubles as their way back whenever they
were last looking at someone else's read-only view.
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


def persistent_menu_keyboard(lang: str, show_podglad: bool = False) -> ReplyKeyboardMarkup:
    """CLAUDE.md step 8.4: [Znajdź partnera] alone on its own row, [Moje
    deble] and [Zaproś na CourtDuo] sharing the next -- resize_keyboard so
    it doesn't take up the whole screen, is_persistent so it doesn't hide
    itself after one tap.

    CLAUDE.md step 10.2: `show_podglad` adds a fourth row, [Podgląd konta],
    for accounts entitlements.can_use_viewers allows -- the caller decides
    that, this function just lays the button out. Everyone else's keyboard
    is unchanged: three buttons, exactly as before.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text=t("common.find_partner_button", lang))
    builder.button(text=t("common.moje_deble_button", lang))
    builder.button(text=t("common.invite_button", lang))
    if show_podglad:
        builder.button(text=t("common.podglad_button", lang))
        builder.adjust(1, 2, 1)
    else:
        builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def invitation_sent_keyboard(lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 8.7: belt-and-braces inline [Moje deble] button for
    the "Zaproszenie zostało wysłane" screen -- see the module docstring."""
    builder = InlineKeyboardBuilder()
    builder.button(text=t("common.moje_deble_button", lang), callback_data=MojeDebleCallback())
    builder.adjust(1)
    return builder.as_markup()


def viewer_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """CLAUDE.md step 10.1: the reply keyboard for a Telegram account that
    has no CourtDuo player account of its own -- see the module docstring
    for why this is a separate keyboard rather than persistent_menu_keyboard
    with a button hidden."""
    builder = ReplyKeyboardBuilder()
    builder.button(text=t("common.moje_deble_button", lang))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
