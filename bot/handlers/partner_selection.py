"""Partner name entry: the message handler for the typed name and the
callback handler for tapping a disambiguation button (CLAUDE.md,
"Pre-invitation checks"; build order step 6).

The hand-off entry point, start_partner_selection, lives in
bot.partner_selection rather than here, since
bot.handlers.tournament_search calls it directly once a tournament is
picked and importing this module from there would be circular. This
module is what PartnerSelection.waiting_name (the state
start_partner_selection sets) hands control to next -- the same split as
bot.handlers.tournament_search around bot.tournament_search.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.tournament_search import start_tournament_search
from bot.i18n import t
from bot.keyboards.partner_selection import PartnerSelectCallback, disambiguation_keyboard
from bot.lang import lang_for
from bot.partner_selection import (
    MatchOutcome,
    build_candidate_options,
    classify_matches,
    find_matching_players,
    handle_partner_candidate,
    split_name_tokens,
)
from bot.states import PartnerSelection
from db import crud

router = Router(name="partner_selection")


@router.message(PartnerSelection.waiting_name)
async def handle_partner_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)

    tokens = split_name_tokens(message.text or "")
    if len(tokens) < 2:
        # CLAUDE.md, "Name matching": a hard rule, not a nicety -- a
        # single-token search over the whole roster is exactly the
        # browsable directory CLAUDE.md forbids. Mid-flow (CLAUDE.md step
        # 8.2): the next thing expected is typing the name again.
        await message.answer(t("partner_selection.name_too_short", lang))
        return

    data = await state.get_data()
    tournament = await crud.get_tournament_by_guid(session, data["tournament_guid"])
    if tournament is None:
        # Re-scraped away between tournament selection and now -- CLAUDE.md,
        # "Never dead-end": there's nothing left to invite a partner to, so
        # send the player back to the top of tournament search. Mid-flow
        # (CLAUDE.md step 8.2): always immediately followed by the
        # keyboarded category screen below.
        gender = crud.gender_for_account_code(account.gender)
        await message.answer(t("tournament_search.tournament_gone", lang))
        await start_tournament_search(message, state, lang, session, gender)
        return

    matches = await find_matching_players(session, tokens)
    outcome = classify_matches(matches)

    if outcome is MatchOutcome.NOT_FOUND:
        # CLAUDE.md, "Not found": no suggestions, no "did you mean" --
        # that's discovery by another name. Mid-flow (CLAUDE.md step 8.2):
        # the next thing expected is typing again.
        await message.answer(t("partner_selection.not_found", lang))
        return
    if outcome is MatchOutcome.TOO_MANY:
        await message.answer(t("partner_selection.too_many_matches", lang))
        return
    if outcome is MatchOutcome.SINGLE:
        await handle_partner_candidate(message, state, session, lang, account, tournament, matches[0])
        return

    options = await build_candidate_options(session, matches, tournament.age_category, lang)
    await message.answer(
        t("partner_selection.disambiguation_prompt", lang, count=len(options)),
        reply_markup=disambiguation_keyboard(options),
    )


@router.callback_query(PartnerSelectCallback.filter(), PartnerSelection.waiting_name)
async def handle_partner_select(
    callback: CallbackQuery, callback_data: PartnerSelectCallback, state: FSMContext, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    await callback.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    tournament = await crud.get_tournament_by_guid(session, data["tournament_guid"])
    candidate = await crud.get_player_by_pzt_id(session, callback_data.pzt_id)
    await callback.answer()

    if tournament is None:
        gender = crud.gender_for_account_code(account.gender)
        await callback.message.answer(t("tournament_search.tournament_gone", lang))
        await start_tournament_search(callback.message, state, lang, session, gender)
        return
    if candidate is None:
        # Extremely unlikely -- the player row disappeared between the
        # disambiguation list being built and this tap. Never dead-end:
        # let the player just type the name again.
        await callback.message.answer(t("partner_selection.not_found", lang))
        return

    await handle_partner_candidate(callback.message, state, session, lang, account, tournament, candidate)
