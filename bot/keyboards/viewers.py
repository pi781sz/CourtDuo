"""Inline keyboards for the Podgląd (read-only viewers) menu (CLAUDE.md,
"Identity", step 10). Reachable only via /podglad -- deliberately not
added to the persistent reply keyboard, see bot.handlers.viewers's module
docstring.

Every button here either manages the player's own grants (create/revoke)
or, for a viewer watching more than one player, picks which player's
Moje deble to open. None of them let a viewer act on the watched player's
behalf -- there is no accept/reject/cancel button anywhere in this module.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from bot.invite_friend import telegram_share_url
from core.text import display_name
from db.models import Account, AccountViewer


class ViewerCreateInviteCallback(CallbackData, prefix="vwmk"):
    pass


class ViewerRevokeCallback(CallbackData, prefix="vwrv"):
    viewer_id: int


class ViewerChooseAccountCallback(CallbackData, prefix="vwchs"):
    account_id: int


def podglad_menu_keyboard(viewers: list[AccountViewer], lang: str) -> InlineKeyboardMarkup:
    """The Podgląd screen's buttons: one "revoke" per active viewer, plus
    a "create a new invite" button unless the account is already at the
    3-viewer cap (CLAUDE.md step 10: the create button simply isn't shown
    at the limit -- the accompanying text explains why, see
    bot.handlers.viewers).
    """
    builder = InlineKeyboardBuilder()
    for index, viewer in enumerate(viewers, start=1):
        builder.button(
            text=t("viewer.revoke_button", lang, index=index),
            callback_data=ViewerRevokeCallback(viewer_id=viewer.id),
        )
    if len(viewers) < 3:
        builder.button(text=t("viewer.create_button", lang), callback_data=ViewerCreateInviteCallback())
    builder.adjust(1)
    return builder.as_markup()


def viewer_invite_share_keyboard(link: str, lang: str) -> InlineKeyboardMarkup:
    """One Telegram share button for the freshly created invite link --
    the token is meant for one specific person the player picks
    themselves (CLAUDE.md step 10: "send to whoever they choose"), so this
    reuses bot.keyboards.invite_friend's contact-picker pattern rather
    than a WhatsApp button too: WhatsApp's share sheet needs a plain text
    message it can prefill, and this link is a t.me URL, best handed over
    via Telegram's own forward-to-contact sheet.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text=t("viewer.invite_share_button", lang),
        url=telegram_share_url(link, t("viewer.invite_share_text", lang, link=link)),
    )
    builder.adjust(1)
    return builder.as_markup()


def viewer_chooser_keyboard(accounts: list[Account], lang: str) -> InlineKeyboardMarkup:
    """CLAUDE.md step 10: a viewer_telegram_id may hold active grants from
    more than one player. Shown only when there is more than one to choose
    from -- bot.handlers.viewers renders directly otherwise."""
    builder = InlineKeyboardBuilder()
    for account in accounts:
        builder.button(
            text=display_name(account.full_name), callback_data=ViewerChooseAccountCallback(account_id=account.id)
        )
    builder.adjust(1)
    return builder.as_markup()
