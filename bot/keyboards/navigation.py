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

Step 12.2 removed the one exception this module used to carry:
find_partner_keyboard put an inline "Znajdź partnera" button on Moje
deble's own summary/empty screens, and moje_deble_summary_keyboard put the
same button on the non-empty summary -- both duplicated the persistent
reply keyboard's own label, which live testing found sitting directly
underneath it on screen at the same time. Neither function offers that
button any more; bot.handlers.moje_deble sends no inline keyboard at all
for the empty state, and moje_deble_summary_keyboard now carries only
buttons that act on a specific entry (one "Usuń" per stranded match).
FindPartnerCallback itself stays defined and handled
(bot.handlers.navigation.handle_find_partner) purely so a message sent
before this change, still carrying the old button, keeps working when
tapped -- no keyboard in this codebase emits it any more.

invitation_sent_keyboard (step 8.7) is the one exception that remains: the
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
from bot.keyboards.invitations import ReleaseMatchCallback


class FindPartnerCallback(CallbackData, prefix="fpart"):
    pass


class MojeDebleCallback(CallbackData, prefix="mdeble"):
    pass


def moje_deble_summary_keyboard(
    lang: str, release_invitation_ids: list[int] | None = None
) -> InlineKeyboardMarkup | None:
    """CLAUDE.md step 12.1, PROBLEM 4, pared back by step 12.2: one "Usuń"
    button per stranded match (a confirmed pairing whose partner deleted
    their CourtDuo account), reusing ReleaseMatchCallback unchanged. Step
    12.1's own version also carried a "Znajdź partnera" button; step 12.2
    removed it -- it duplicated the persistent reply keyboard's own label,
    visible on screen at the same time as this one. Navigation lives on
    the persistent keyboard only; an inline keyboard here carries nothing
    but buttons that act on this message's own specific entries. Returns
    None -- "no inline keyboard" -- when there is nothing stranded to
    act on.
    """
    release_ids = list(release_invitation_ids or ())
    if not release_ids:
        return None
    builder = InlineKeyboardBuilder()
    for invitation_id in release_ids:
        builder.button(
            text=t("deletion.release_button", lang),
            callback_data=ReleaseMatchCallback(invitation_id=invitation_id),
        )
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
