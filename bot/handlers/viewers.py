"""Podgląd: the read-only-viewers menu, and the read-only Moje deble a
viewer opens (CLAUDE.md, "Identity", step 10 -- allowlisted test
feature).

/podglad is a plain slash command, deliberately not added to the
persistent reply keyboard: CLAUDE.md's "Navigation" section pins that
keyboard to exactly three fixed actions ("the reply keyboard only ever
carries these three fixed actions"), and this is a test feature gated by
an allowlist most accounts will never satisfy -- making the reply
keyboard allowlist-aware would be a far bigger change than this feature
warrants. /moje_deble already proves a command is a legitimate,
keyboard-independent entry point on its own.

Every handler here re-checks entitlements.can_use_viewers itself rather
than trusting that the menu wasn't shown to begin with -- the same
"friendly pre-check, then re-check" doubling CLAUDE.md's invitation
engine already practices, since a callback payload can be replayed or
constructed directly.

A non-allowlisted or unregistered account gets *no reply at all* from
/podglad -- not even a refusal -- so the feature is invisible rather than
merely locked (CLAUDE.md step 10: "Everyone else's bot is unchanged").
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.viewers import (
    ViewerChooseAccountCallback,
    ViewerCreateInviteCallback,
    ViewerRevokeCallback,
    podglad_menu_keyboard,
    viewer_chooser_keyboard,
    viewer_invite_share_keyboard,
)
from bot.lang import lang_for
from bot.moje_deble import group_by_tournament, render_groups
from bot.viewers import create_invite_token, invite_link
from core.text import display_name
from db import crud
from db.models import Account
from entitlements import can_use_viewers

router = Router(name="viewers")

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today():
    # Mirrors bot.handlers.moje_deble's helper of the same shape.
    return datetime.now(timezone.utc).astimezone(_WARSAW_TZ).date()


async def _render_menu(message: Message, session: AsyncSession, account: Account, lang: str) -> None:
    viewers = await crud.get_active_viewers_for_account(session, account.id)
    lines = [t("viewer.podglad_heading", lang), "", t("viewer.podglad_intro", lang)]
    if viewers:
        lines.append("")
        lines.extend(
            t("viewer.list_item", lang, index=index, date=viewer.granted_at.strftime("%d.%m.%Y"))
            for index, viewer in enumerate(viewers, start=1)
        )
    else:
        lines.append("")
        lines.append(t("viewer.list_empty", lang))
    if len(viewers) >= crud.MAX_ACTIVE_VIEWERS:
        lines.append("")
        lines.append(t("viewer.limit_reached", lang))
    await message.answer("\n".join(lines), reply_markup=podglad_menu_keyboard(viewers, lang))


@router.message(Command("podglad"))
async def handle_podglad(message: Message, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    if account is None or not can_use_viewers(account):
        return
    await _render_menu(message, session, account, lang_for(account))


@router.callback_query(ViewerCreateInviteCallback.filter())
async def handle_viewer_create_invite(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    await callback.answer()
    if account is None or not can_use_viewers(account):
        return
    lang = lang_for(account)

    token_row = await create_invite_token(session, account)
    if token_row is None:
        await callback.message.answer(t("viewer.limit_reached", lang))
        return

    me = await bot.get_me()
    link = invite_link(me.username, token_row.token)
    await callback.message.answer(
        t("viewer.invite_created", lang, link=link), reply_markup=viewer_invite_share_keyboard(link, lang)
    )


@router.callback_query(ViewerRevokeCallback.filter())
async def handle_viewer_revoke(
    callback: CallbackQuery, callback_data: ViewerRevokeCallback, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    await callback.answer()
    if account is None or not can_use_viewers(account):
        return
    lang = lang_for(account)

    revoked = await crud.revoke_viewer(session, account.id, callback_data.viewer_id, datetime.now(timezone.utc))
    if revoked is None:
        # Stale button (already revoked, or never belonged to this
        # account) -- just re-render the current state rather than
        # claiming a fresh revocation happened.
        await _render_menu(callback.message, session, account, lang)
        return

    await callback.message.answer(t("viewer.revoked", lang))
    await _render_menu(callback.message, session, account, lang)


@router.callback_query(ViewerChooseAccountCallback.filter())
async def handle_viewer_choose_account(
    callback: CallbackQuery, callback_data: ViewerChooseAccountCallback, session: AsyncSession
) -> None:
    await callback.answer()
    # Defense in depth: the tapper must actually hold an active grant for
    # this account_id -- a callback payload is client-supplied and cannot
    # be trusted on its own, the same discipline every invitation-answer
    # handler already applies to its own invitation_id.
    grants = await crud.get_active_viewer_grants_for_telegram_id(session, callback.from_user.id)
    watched = next((grant.account for grant in grants if grant.account_id == callback_data.account_id), None)
    if watched is None:
        return
    own_account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    await render_readonly_moje_deble(callback.message, session, watched, lang_for(own_account))


async def render_readonly_moje_deble(message: Message, session: AsyncSession, watched_account: Account, lang: str) -> None:
    """CLAUDE.md step 10, WHAT A VIEWER CAN DO: "Open a read-only version
    of Moje deble." Reuses bot.moje_deble's pure grouping/rendering
    exactly as the player's own Moje deble does, keyed off the watched
    player's own pzt_id -- but with no reply_markup and no per-invitation
    follow-up messages at all, so there is no action button anywhere on
    this screen (WHAT A VIEWER CANNOT DO).
    """
    invitations = await crud.get_invitations_for_player(session, watched_account.pzt_id)
    groups = group_by_tournament(invitations, watched_account.pzt_id, _warsaw_today(), lang)
    heading = t("viewer.readonly_heading", lang, name=display_name(watched_account.full_name))

    if not groups:
        await message.answer(f"{heading}\n\n{t('moje_deble.empty', lang)}")
        return
    await message.answer(f"{heading}\n\n{render_groups(groups, lang)}")


async def render_moje_deble_for_viewer(message: Message, session: AsyncSession, telegram_id: int, lang: str) -> bool:
    """Called by bot.handlers.moje_deble when `telegram_id` has no
    account of its own. Returns False (nothing rendered, caller falls
    through to its own not-registered message) when `telegram_id` holds
    no active viewer grants either -- true for the overwhelming majority
    of unregistered chats, which must see today's unchanged behaviour.

    CLAUDE.md step 10: a viewer_telegram_id may hold grants from more than
    one player at once, so more than one watched account needs a chooser
    rather than picking one arbitrarily.
    """
    grants = await crud.get_active_viewer_grants_for_telegram_id(session, telegram_id)
    if not grants:
        return False
    if len(grants) == 1:
        await render_readonly_moje_deble(message, session, grants[0].account, lang)
        return True
    await message.answer(
        t("viewer.choose_account_prompt", lang),
        reply_markup=viewer_chooser_keyboard([grant.account for grant in grants], lang),
    )
    return True
