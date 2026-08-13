"""The Telegram plumbing of account deletion and match release (CLAUDE.md
step 12, "Account deletion and blocking"). Two independent two-step
confirmation flows sharing one router:

- /usun_konto: a player deletes their own CourtDuo account.
- "Zwolnij parę": the player left behind by a deleted partner's account
  manually frees a still-ACCEPTED match (CLAUDE.md: "Do NOT cancel the
  match and do NOT free the other player to invite somebody else
  automatically ... Give the remaining player one manual escape").

Same order-of-operations discipline as bot.handlers.invitations: commit
the transaction, *then* push whatever it implies, and never let a push
failure undo a decision that already committed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.account_deletion import delete_account
from bot.account_deletion_text import (
    confirm_screen_text,
    explain_screen_text,
    partner_notified_text,
    pending_cancelled_by_deletion_text,
    release_confirm_text,
    release_done_text,
)
from bot.i18n import t
from bot.invitation_engine import release_deleted_partner_match
from bot.keyboards.account_deletion import (
    DeleteAccountAbortCallback,
    DeleteAccountConfirmCallback,
    DeleteAccountStartCallback,
    delete_account_confirm_keyboard,
    delete_account_explain_keyboard,
)
from bot.keyboards.invitations import (
    ReleaseMatchAbortCallback,
    ReleaseMatchCallback,
    ReleaseMatchConfirmCallback,
    release_match_confirm_keyboard,
)
from bot.keyboards.navigation import persistent_menu_keyboard
from bot.lang import lang_for
from bot.notifications import push
from bot.tournament_search import label_for_tournament
from bot.viewers import forward_to_viewers
from db import crud
from entitlements import can_use_viewers

logger = logging.getLogger(__name__)

router = Router(name="account_deletion")

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today():
    # Mirrors bot.handlers.moje_deble's helper of the same shape.
    return datetime.now(timezone.utc).astimezone(_WARSAW_TZ).date()


def _other_pzt_id(invitation, deleted_pzt_id: str) -> str:
    return invitation.invitee_pzt_id if invitation.inviter_pzt_id == deleted_pzt_id else invitation.inviter_pzt_id


# --- Self-service deletion ------------------------------------------------------


@router.message(Command("usun_konto"))
async def handle_usun_konto(message: Message, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    if account is None:
        # Same fallback as every other command a Telegram id with no
        # CourtDuo account of its own can type -- there's nothing to
        # delete, so point them at /start instead of leaving a dead end.
        await message.answer(t("moje_deble.not_registered", lang), reply_markup=persistent_menu_keyboard(lang))
        return
    await message.answer(
        explain_screen_text(account.gender, lang), reply_markup=delete_account_explain_keyboard(lang)
    )


@router.callback_query(DeleteAccountStartCallback.filter())
async def handle_delete_account_start(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    await callback.answer()
    if account is None:
        return
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear delete-account explain buttons: %s", exc)
    await callback.message.answer(confirm_screen_text(lang), reply_markup=delete_account_confirm_keyboard(lang))


@router.callback_query(DeleteAccountAbortCallback.filter())
async def handle_delete_account_abort(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear delete-account buttons: %s", exc)
    await callback.answer()
    if account is None:
        return
    await callback.message.answer(
        t("deletion.aborted", lang), reply_markup=persistent_menu_keyboard(lang, can_use_viewers(account))
    )


@router.callback_query(DeleteAccountConfirmCallback.filter())
async def handle_delete_account_confirm(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear delete-account confirm buttons: %s", exc)
    await callback.answer()
    if account is None:
        # Already deleted (a double-tap on a stale confirm button, or the
        # account vanished between screens) -- nothing left to do.
        return
    lang = lang_for(account)

    result = await delete_account(session, account, _warsaw_today())
    await session.commit()

    await callback.message.answer(t("deletion.done", lang))

    for invitation in result.cancelled_sent:
        # The deleted player was the inviter here, so `other_account` is
        # the invitee -- the one whose chat carries the original
        # invitation_answer_keyboard message, remembered on
        # invitee_message_id (CLAUDE.md step 8.6).
        other_account = await crud.get_account_by_pzt_id(session, invitation.invitee_pzt_id)
        if other_account is None:
            continue
        other_lang = other_account.lang or lang
        text = pending_cancelled_by_deletion_text(
            result.deleted_full_name, result.deleted_gender, label_for_tournament(invitation.tournament), other_lang
        )
        await push(
            bot,
            other_account.telegram_id,
            text,
            reply_markup=persistent_menu_keyboard(other_lang, can_use_viewers(other_account)),
        )
        await forward_to_viewers(bot, session, other_account.id, text)
        if invitation.invitee_message_id is not None:
            # Same best-effort tidy-up bot.handlers.invitations.handle_cancel
            # does for a step 8.6 withdrawal: strips the three answer
            # buttons off the invitee's original notification so a
            # cancelled-by-deletion invitation can't still be tapped from
            # the screen it first arrived on. The engine's own re-check is
            # what actually prevents a stale answer, this is cosmetic.
            try:
                await bot.edit_message_reply_markup(
                    chat_id=other_account.telegram_id, message_id=invitation.invitee_message_id, reply_markup=None
                )
            except TelegramAPIError as exc:
                logger.info("Could not clear cancelled-by-deletion invitation's original buttons: %s", exc)

    for invitation in result.cancelled_received:
        # The deleted player was the invitee here -- the original
        # answer-keyboard message lived in *their* now-gone chat, so
        # there's nothing left to strip. `other_account` is the inviter.
        other_account = await crud.get_account_by_pzt_id(session, invitation.inviter_pzt_id)
        if other_account is None:
            continue
        other_lang = other_account.lang or lang
        text = pending_cancelled_by_deletion_text(
            result.deleted_full_name, result.deleted_gender, label_for_tournament(invitation.tournament), other_lang
        )
        await push(
            bot,
            other_account.telegram_id,
            text,
            reply_markup=persistent_menu_keyboard(other_lang, can_use_viewers(other_account)),
        )
        await forward_to_viewers(bot, session, other_account.id, text)

    for invitation in result.confirmed_matches:
        other_pzt_id = _other_pzt_id(invitation, result.deleted_pzt_id)
        other_account = await crud.get_account_by_pzt_id(session, other_pzt_id)
        if other_account is None:
            continue
        other_lang = other_account.lang or lang
        text = partner_notified_text(result.deleted_full_name, result.deleted_gender, other_lang)
        await push(
            bot,
            other_account.telegram_id,
            text,
            reply_markup=persistent_menu_keyboard(other_lang, can_use_viewers(other_account)),
        )
        await forward_to_viewers(bot, session, other_account.id, text)


# --- Releasing a match after a partner's account deletion ------------------------


@router.callback_query(ReleaseMatchCallback.filter())
async def handle_release_match_start(
    callback: CallbackQuery, callback_data: ReleaseMatchCallback, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    await callback.answer()
    if account is None:
        return
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear release-match buttons: %s", exc)
    await callback.message.answer(
        release_confirm_text(account.gender, lang),
        reply_markup=release_match_confirm_keyboard(callback_data.invitation_id, lang),
    )


@router.callback_query(ReleaseMatchAbortCallback.filter())
async def handle_release_match_abort(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear release-match confirm buttons: %s", exc)
    await callback.answer()
    if account is None:
        return
    await callback.message.answer(
        t("deletion.release_aborted", lang), reply_markup=persistent_menu_keyboard(lang, can_use_viewers(account))
    )


@router.callback_query(ReleaseMatchConfirmCallback.filter())
async def handle_release_match_confirm(
    callback: CallbackQuery, callback_data: ReleaseMatchConfirmCallback, session: AsyncSession, bot: Bot
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear release-match confirm buttons: %s", exc)
    await callback.answer()
    if account is None:
        await callback.message.answer(t("invitation.no_longer_valid", lang))
        return

    result = await release_deleted_partner_match(session, callback_data.invitation_id, account.pzt_id)

    if result.failure is not None:
        # NOT_FOUND / NOT_YOURS / NOT_ACCEPTED / PARTNER_NOT_DELETED all
        # mean the same thing to the player: a stale button on a row that
        # no longer qualifies -- one neutral message, no detail needed.
        await session.commit()
        await callback.message.answer(
            t("invitation.no_longer_valid", lang),
            reply_markup=persistent_menu_keyboard(lang, can_use_viewers(account)),
        )
        return

    invitation = result.invitation
    tournament = await crud.get_tournament_by_guid(session, invitation.tournament_guid)
    label = label_for_tournament(tournament)
    await session.commit()

    message_text = release_done_text(account.gender, label, lang)
    await callback.message.answer(
        message_text, reply_markup=persistent_menu_keyboard(lang, can_use_viewers(account))
    )
    await forward_to_viewers(bot, session, account.id, message_text)
