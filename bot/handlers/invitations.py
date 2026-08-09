"""The Telegram plumbing of the invitation flow (CLAUDE.md, "Invitation
engine"; build order step 7): five button taps, three of them from a
player who is not in a conversation at all.

The decisions live in bot.invitation_engine and the wording in
bot.invitation_text; this module resolves who is who, runs one
transaction, commits it, and then delivers the messages that transaction
implies. That order matters twice over:

- **Commit before pushing.** The invitee can tap Zatwierdź the instant the
  invitation lands, in a different update with its own session. If the
  push went out before the commit, that tap could look up an invitation
  that isn't visible yet.
- **Push after committing, and never let a push failure undo it.** A
  player who blocked the bot must not cost the other three players their
  answer, so bot.notifications.push reports failure instead of raising.
  The one case where a failed push does change the outcome is a brand new
  invitation: an invitation nobody can see must not sit 🟠 pending
  forever, so it is cancelled and the inviter is told (CLAUDE.md's "do not
  leave the inviter waiting on a 🟠 that can never resolve").

The three answer handlers carry no state filter. The invitee may be
anywhere — mid tournament search, or in no state at all — and answering an
invitation must not disturb whatever they were doing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.tournament_search import start_tournament_search
from bot.i18n import t
from bot.invitation_engine import (
    RespondFailure,
    RespondResult,
    SendFailure,
    accept_invitation,
    not_attending_invitation,
    reject_invitation,
    send_invitation,
)
from bot.invitation_text import (
    accepted_inviter_text,
    invitation_text,
    matched_text,
    not_attending_invitee_text,
    not_attending_inviter_text,
    rejected_invitee_text,
    rejected_inviter_text,
    sent_text,
)
from bot.keyboards.invitations import (
    AcceptInvitationCallback,
    CancelSendCallback,
    ConfirmSendCallback,
    NotAttendingCallback,
    RejectInvitationCallback,
    invitation_answer_keyboard,
)
from bot.lang import lang_for
from bot.notifications import push
from bot.states import InvitationSend, PartnerSelection
from bot.tournament_search import label_for_tournament
from core.text import display_name
from db import crud
from db.models import Account, Invitation, InvitationState

logger = logging.getLogger(__name__)

router = Router(name="invitations")

# Every send failure reuses the step-6 wording where the situation is the
# same one — a player should not get two different sentences for "this
# person already has a partner" depending on which check caught it.
_SEND_FAILURE_KEYS: dict[SendFailure, str] = {
    SendFailure.NOT_ENTITLED: "partner_selection.cannot_send_invitation",
    SendFailure.INVITEE_NOT_ON_COURTDUO: "invitation.invitee_not_on_courtduo",
    SendFailure.SELF_INVITE: "partner_selection.self_invite",
    SendFailure.GENDER_MISMATCH: "partner_selection.gender_mismatch",
    SendFailure.INVITER_ALREADY_MATCHED: "partner_selection.inviter_already_matched",
    SendFailure.INVITEE_ALREADY_MATCHED: "partner_selection.invitee_already_matched",
    SendFailure.ALREADY_ANSWERED: "partner_selection.already_answered",
    SendFailure.PENDING_INVITATION_EXISTS: "partner_selection.pending_invitation_exists",
    SendFailure.ALREADY_INVITED_BY_INVITEE: "invitation.already_invited_by_invitee",
    SendFailure.MAX_PENDING_REACHED: "partner_selection.max_pending_reached",
    SendFailure.TOURNAMENT_UNAVAILABLE: "tournament_search.tournament_gone",
}

# Failures that leave the player with no name worth typing: they already
# have a partner here, or the tournament itself is gone. Both send the
# player back to the top of tournament search rather than to the name
# prompt (CLAUDE.md, "Never dead-end").
_SEND_FAILURES_RESTARTING_SEARCH = frozenset(
    {SendFailure.INVITER_ALREADY_MATCHED, SendFailure.TOURNAMENT_UNAVAILABLE}
)

_RESPOND_FAILURE_KEYS: dict[RespondFailure, str] = {
    # NOT_YOURS means a callback payload naming somebody else's
    # invitation. It gets the same neutral sentence as a stale one:
    # confirming that an invitation exists would be a disclosure of its own.
    RespondFailure.NOT_FOUND: "invitation.no_longer_valid",
    RespondFailure.NOT_YOURS: "invitation.no_longer_valid",
    RespondFailure.PLAYER_ALREADY_MATCHED: "invitation.no_longer_valid",
    RespondFailure.ALREADY_ANSWERED: "invitation.already_answered",
    RespondFailure.CANCELLED_BY_MATCH: "invitation.partner_found_elsewhere",
    RespondFailure.EXPIRED: "invitation.expired",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _clear_buttons(callback: CallbackQuery) -> None:
    """Takes the tapped keyboard away so the same invitation cannot be
    answered twice. Telegram refuses to edit messages beyond a certain
    age, and an invitation can be weeks old by the time it is answered —
    that refusal is cosmetic and must not abort the answer itself.
    """
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramAPIError as exc:
        logger.info("Could not clear invitation buttons: %s", exc)


async def _participant(session: AsyncSession, pzt_id: str) -> tuple[Account | None, str]:
    """(account, display name) for one side of an invitation.

    Both sides of a stored invitation always have an account — a send is
    refused otherwise — but a name is still needed if one were ever
    deleted, so the PZT roster is the fallback rather than a crash.
    """
    account = await crud.get_account_by_pzt_id(session, pzt_id)
    if account is not None:
        return account, account.full_name
    player = await crud.get_player_by_pzt_id(session, pzt_id)
    return None, player.full_name if player is not None else pzt_id


def _other_participant(invitation: Invitation, matched_pair: tuple[str, str]) -> str | None:
    """Who to tell that a cancelled invitation is over: the player in it
    who is not part of the match that cancelled it. Returns None when both
    of its players are — the newly matched pair already know."""
    for pzt_id in (invitation.inviter_pzt_id, invitation.invitee_pzt_id):
        if pzt_id not in matched_pair:
            return pzt_id
    return None


async def _notify_cancelled(
    bot: Bot, session: AsyncSession, result: RespondResult, matched_pair: tuple[str, str], lang: str
) -> None:
    """CLAUDE.md: "Each cancelled recipient is told: 'Ten zawodnik znalazł
    już partnera.'" — for both players' cancelled invitations, incoming and
    outgoing alike."""
    for cancelled in result.cancelled:
        pzt_id = _other_participant(cancelled, matched_pair)
        if pzt_id is None:
            continue
        account, _ = await _participant(session, pzt_id)
        if account is None:
            continue
        recipient_lang = account.lang or lang
        await push(bot, account.telegram_id, t("invitation.partner_found_elsewhere", recipient_lang))


# --- Inviter: the confirmation screen ------------------------------------------


@router.callback_query(ConfirmSendCallback.filter(), InvitationSend.waiting_confirmation)
async def handle_confirm_send(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    await _clear_buttons(callback)
    await callback.answer()

    data = await state.get_data()
    tournament_guid = data.get("tournament_guid")
    partner_pzt_id = data.get("partner_pzt_id")
    tournament = await crud.get_tournament_by_guid(session, tournament_guid) if tournament_guid else None
    invitee = await crud.get_player_by_pzt_id(session, partner_pzt_id) if partner_pzt_id else None

    if account is None or tournament is None or invitee is None:
        # State lost (a bot restart clears MemoryStorage) or the tournament
        # was re-scraped away between the confirmation screen and this tap.
        # Mid-flow (CLAUDE.md step 8.2): always immediately followed by the
        # keyboarded category screen below, when there's an account to show
        # it to.
        await callback.message.answer(t("tournament_search.tournament_gone", lang))
        if account is not None:
            await start_tournament_search(callback.message, state, lang, session, account)
        return

    result = await send_invitation(session, account, tournament, invitee, _now())

    if result.failure is not None:
        name = invitee.full_name
        if result.inviter_partner_pzt_id is not None:
            _, name = await _participant(session, result.inviter_partner_pzt_id)
        await callback.message.answer(t(_SEND_FAILURE_KEYS[result.failure], lang, name=display_name(name)))
        if result.failure in _SEND_FAILURES_RESTARTING_SEARCH:
            await start_tournament_search(callback.message, state, lang, session, account)
            return
        # Everything else leaves the tournament chosen and the player free
        # to name somebody else straight away.
        await state.set_state(PartnerSelection.waiting_name)
        return

    label = label_for_tournament(tournament)
    invitation = result.invitation
    invitee_account = result.invitee_account
    await session.commit()

    delivered = await push(
        bot,
        invitee_account.telegram_id,
        invitation_text(account.full_name, label, invitee_account.lang or lang),
        reply_markup=invitation_answer_keyboard(invitation.id, invitee_account.lang or lang),
    )
    if not delivered:
        # Nobody will ever answer this one, so it must not count against
        # the inviter's three pending invitations or sit 🟠 for weeks.
        invitation.state = InvitationState.CANCELLED
        await session.commit()
        logger.warning("Invitation %s cancelled: could not be delivered", invitation.id)
        # Mid-flow (CLAUDE.md step 8.2): the message itself says to type
        # another name.
        await callback.message.answer(t("invitation.delivery_failed", lang, name=display_name(invitee.full_name)))
        await state.set_state(PartnerSelection.waiting_name)
        return

    await callback.message.answer(sent_text(invitee.full_name, label, lang))
    # CLAUDE.md allows up to three pending invitations per tournament, and
    # a rejection frees the player to invite somebody else immediately —
    # so the tournament stays chosen and the name prompt stays live.
    await state.set_state(PartnerSelection.waiting_name)


@router.callback_query(CancelSendCallback.filter(), InvitationSend.waiting_confirmation)
async def handle_cancel_send(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    await _clear_buttons(callback)
    await callback.answer()

    # Nothing was written, so there is nothing to undo — this is why the
    # confirmation screen exists. Back to the name prompt with the
    # tournament still chosen. Mid-flow (CLAUDE.md step 8.2): the next
    # thing expected is typing a name.
    await callback.message.answer(t("invitation.send_cancelled", lang))
    await callback.message.answer(t("partner_selection.ask_name", lang))
    await state.set_state(PartnerSelection.waiting_name)


# --- Invitee: the three answers ------------------------------------------------


@router.callback_query(AcceptInvitationCallback.filter())
async def handle_accept(
    callback: CallbackQuery, callback_data: AcceptInvitationCallback, session: AsyncSession, bot: Bot
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    await _clear_buttons(callback)
    await callback.answer()
    if account is None:
        await callback.message.answer(t("invitation.no_longer_valid", lang))
        return

    result = await accept_invitation(session, callback_data.invitation_id, account.pzt_id, _now())

    if result.failure is not None:
        await session.commit()
        if result.failure is RespondFailure.PLAYER_ALREADY_MATCHED and result.responder_already_matched:
            # CLAUDE.md: name the player who already has a partner only
            # when it is the person being told. Their own partner's name is
            # theirs to know; the other player's is not.
            matched = await crud.get_matched_invitation(session, account.pzt_id, result.invitation.tournament_guid)
            if matched is not None:
                partner_pzt_id = (
                    matched.invitee_pzt_id if matched.inviter_pzt_id == account.pzt_id else matched.inviter_pzt_id
                )
                _, partner_name = await _participant(session, partner_pzt_id)
                await callback.message.answer(
                    t("partner_selection.inviter_already_matched", lang, name=display_name(partner_name))
                )
                return
        await callback.message.answer(t(_RESPOND_FAILURE_KEYS[result.failure], lang))
        return

    invitation = result.invitation
    tournament = await crud.get_tournament_by_guid(session, invitation.tournament_guid)
    label = label_for_tournament(tournament)
    inviter_account, inviter_name = await _participant(session, invitation.inviter_pzt_id)
    matched_pair = (invitation.inviter_pzt_id, invitation.invitee_pzt_id)
    await session.commit()

    await callback.message.answer(matched_text(inviter_name, label, lang))
    if inviter_account is not None:
        inviter_lang = inviter_account.lang or lang
        await push(
            bot,
            inviter_account.telegram_id,
            accepted_inviter_text(account.full_name, account.gender, label, inviter_lang),
        )
    await _notify_cancelled(bot, session, result, matched_pair, lang)


# (session, invitation_id, responder_pzt_id, now) -> RespondResult
_Answer = Callable[[AsyncSession, int, str, datetime], Awaitable[RespondResult]]
# (other player's full name, invitee's gender code, tournament label, lang) -> str
_AnswerText = Callable[[str, str, str, str], str]


async def _handle_simple_answer(
    callback: CallbackQuery,
    invitation_id: int,
    session: AsyncSession,
    bot: Bot,
    answer: _Answer,
    invitee_text: _AnswerText,
    inviter_text: _AnswerText,
) -> None:
    """Odrzuć and "Nie jadę na ten turniej" differ only in which engine
    call runs and which two sentences come out; both are instant, free, and
    change nothing but the one invitation."""
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    await _clear_buttons(callback)
    await callback.answer()
    if account is None:
        await callback.message.answer(t("invitation.no_longer_valid", lang))
        return

    result = await answer(session, invitation_id, account.pzt_id, _now())
    if result.failure is not None:
        await session.commit()
        await callback.message.answer(t(_RESPOND_FAILURE_KEYS[result.failure], lang))
        return

    invitation = result.invitation
    tournament = await crud.get_tournament_by_guid(session, invitation.tournament_guid)
    label = label_for_tournament(tournament)
    inviter_account, inviter_name = await _participant(session, invitation.inviter_pzt_id)
    await session.commit()

    await callback.message.answer(invitee_text(inviter_name, account.gender, label, lang))
    if inviter_account is not None:
        inviter_lang = inviter_account.lang or lang
        await push(
            bot,
            inviter_account.telegram_id,
            inviter_text(account.full_name, account.gender, label, inviter_lang),
        )


@router.callback_query(RejectInvitationCallback.filter())
async def handle_reject(
    callback: CallbackQuery, callback_data: RejectInvitationCallback, session: AsyncSession, bot: Bot
) -> None:
    await _handle_simple_answer(
        callback,
        callback_data.invitation_id,
        session,
        bot,
        reject_invitation,
        rejected_invitee_text,
        rejected_inviter_text,
    )


@router.callback_query(NotAttendingCallback.filter())
async def handle_not_attending(
    callback: CallbackQuery, callback_data: NotAttendingCallback, session: AsyncSession, bot: Bot
) -> None:
    """CLAUDE.md's third answer. It closes this invitation and nothing
    else: no future invitation to this player for this tournament is
    blocked, hidden or filtered by it, and nothing stores it as a fact
    about the player — only as the terminal state of this one row.
    """
    await _handle_simple_answer(
        callback,
        callback_data.invitation_id,
        session,
        bot,
        not_attending_invitation,
        # Neither sentence mentions the inviter or the tournament, so both
        # ignore the arguments the rejection wording uses.
        lambda _name, gender, _label, lang: not_attending_invitee_text(gender, lang),
        lambda name, _gender, _label, lang: not_attending_inviter_text(name, lang),
    )
