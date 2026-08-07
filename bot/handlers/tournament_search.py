"""Tournament selection by place (CLAUDE.md, "Tournament selection";
build order step 5). A registered player types a town or województwo and
gets back tappable tournament buttons, one per matching tournament;
tapping one hands off to step 6 via bot.partner_selection.

The pure matching/labelling/pagination logic lives in
bot.tournament_search so it can be unit-tested without a database; this
module is Telegram plumbing around it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.tournament_search import (
    ChangePlaceCallback,
    ShowAllTournamentsCallback,
    TournamentPageCallback,
    TournamentSelectCallback,
    no_matches_keyboard,
    results_keyboard,
)
from bot.lang import lang_for
from bot.partner_selection import start_partner_selection
from bot.states import TournamentSearch
from bot.tournament_search import (
    PAGE_SIZE,
    TournamentOption,
    match_by_place,
    meets_min_place_length,
    paginate,
    start_tournament_search,
    to_option,
)
from db import crud

router = Router(name="tournament_search")

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today_and_utc_now() -> tuple[datetime, datetime]:
    """(today, now) for get_eligible_tournaments: `today` is the
    Europe/Warsaw wall-clock date the 14-day window counts from,
    `now` is the UTC instant search_closes_at compares against."""
    now = datetime.now(timezone.utc)
    return now.astimezone(_WARSAW_TZ).date(), now


async def _eligible_options(session: AsyncSession, gender_code: str) -> list[TournamentOption]:
    today, now = _warsaw_today_and_utc_now()
    gender = crud.gender_for_account_code(gender_code)
    tournaments = await crud.get_eligible_tournaments(session, gender, today, now)
    return [to_option(tournament) for tournament in tournaments]


async def _send_results(message: Message, options: list[TournamentOption], offset: int, lang: str) -> None:
    page, has_more = paginate(options, offset)
    keyboard = results_keyboard(page, has_more, offset + PAGE_SIZE, lang)
    await message.answer(t("tournament_search.results", lang), reply_markup=keyboard)


async def _edit_to_results(callback: CallbackQuery, options: list[TournamentOption], offset: int, lang: str) -> None:
    page, has_more = paginate(options, offset)
    keyboard = results_keyboard(page, has_more, offset + PAGE_SIZE, lang)
    await callback.message.edit_text(t("tournament_search.results", lang), reply_markup=keyboard)


@router.message(TournamentSearch.waiting_place)
async def handle_place(message: Message, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    place = (message.text or "").strip()

    if not meets_min_place_length(place):
        await message.answer(t("tournament_search.place_too_short", lang))
        return

    eligible = await _eligible_options(session, account.gender)
    if not eligible:
        await message.answer(t("tournament_search.none_eligible", lang))
        return

    matches = match_by_place(eligible, place)
    if not matches:
        await message.answer(t("tournament_search.no_place_matches", lang), reply_markup=no_matches_keyboard(lang))
        return

    await state.update_data(place=place)
    await _send_results(message, matches, offset=0, lang=lang)


@router.callback_query(ShowAllTournamentsCallback.filter(), TournamentSearch.waiting_place)
async def handle_show_all(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    await state.update_data(place="")
    eligible = await _eligible_options(session, account.gender)
    await _edit_to_results(callback, eligible, offset=0, lang=lang)
    await callback.answer()


@router.callback_query(TournamentPageCallback.filter(), TournamentSearch.waiting_place)
async def handle_page(
    callback: CallbackQuery, callback_data: TournamentPageCallback, state: FSMContext, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    data = await state.get_data()
    place = data.get("place") or ""
    eligible = await _eligible_options(session, account.gender)
    options = match_by_place(eligible, place) if place else eligible

    await _edit_to_results(callback, options, offset=callback_data.offset, lang=lang)
    await callback.answer()


@router.callback_query(ChangePlaceCallback.filter(), TournamentSearch.waiting_place)
async def handle_change_place(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    await state.update_data(place=None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_tournament_search(callback.message, state, lang)
    await callback.answer()


@router.callback_query(TournamentSelectCallback.filter(), TournamentSearch.waiting_place)
async def handle_select(
    callback: CallbackQuery, callback_data: TournamentSelectCallback, state: FSMContext, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    tournament = await crud.get_tournament_by_guid(session, callback_data.guid)
    if tournament is None or tournament.date_from is None:
        await callback.answer()
        return

    await state.update_data(tournament_guid=tournament.guid)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("tournament_search.selected", lang, date=f"{tournament.date_from:%Y.%m.%d}"))
    await callback.answer()
    await start_partner_selection(callback.message, state, lang)
