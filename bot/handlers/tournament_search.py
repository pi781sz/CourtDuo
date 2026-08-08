"""Tournament selection: age category first, then place (CLAUDE.md,
"Tournament selection"; build order step 5, revised by step 5.1 and by
step 5.3). A registered player taps one of the four age-category buttons,
sees it confirmed, then types a town or województwo and gets back
tappable tournament buttons, one per matching tournament; tapping one
hands off to step 6 (partner name entry and pre-invitation checks) via
bot.partner_selection.start_partner_selection.

start_tournament_search() is the entry point step 4 calls after a
successful registration and on /start for an already registered player.

The pure matching/labelling/pagination logic lives in
bot.tournament_search so it can be unit-tested without a database; this
module is Telegram + database plumbing around it.
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
    CategorySelectCallback,
    ChangeCategoryCallback,
    ChangePlaceCallback,
    ShowAllTournamentsCallback,
    TournamentSelectCallback,
    category_keyboard,
    no_matches_keyboard,
    none_eligible_keyboard,
    results_keyboard,
)
from bot.lang import lang_for
from bot.partner_selection import start_partner_selection
from bot.states import TournamentSearch
from bot.tournament_search import (
    TournamentOption,
    cap_results,
    category_selected_text,
    match_by_place,
    meets_min_place_length,
    selection_confirmation_text,
    to_option,
)
from db import crud
from db.models import AgeCategory, Gender

router = Router(name="tournament_search")

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _warsaw_today_and_utc_now() -> tuple[datetime, datetime]:
    """(today, now) for the eligibility queries: `today` is the
    Europe/Warsaw wall-clock date the eligibility window counts from,
    `now` is the UTC instant search_closes_at compares against."""
    now = datetime.now(timezone.utc)
    return now.astimezone(_WARSAW_TZ).date(), now


async def _category_counts(session: AsyncSession, gender: Gender) -> dict[AgeCategory, int]:
    today, now = _warsaw_today_and_utc_now()
    return await crud.get_eligible_tournament_counts_by_category(session, gender, today, now)


async def _eligible_options(
    session: AsyncSession, gender: Gender, age_category: AgeCategory
) -> list[TournamentOption]:
    today, now = _warsaw_today_and_utc_now()
    tournaments = await crud.get_eligible_tournaments(session, gender, age_category, today, now)
    return [to_option(tournament) for tournament in tournaments]


async def _send_category_prompt(message: Message, session: AsyncSession, gender: Gender, lang: str) -> None:
    counts = await _category_counts(session, gender)
    await message.answer(t("tournament_search.ask_category", lang), reply_markup=category_keyboard(counts, lang))


def _results_text(capped: bool, lang: str) -> str:
    text = t("tournament_search.results", lang)
    if capped:
        text = f"{text}\n\n{t('tournament_search.too_many_results', lang)}"
    return text


async def _send_results(message: Message, options: list[TournamentOption], lang: str) -> None:
    page, capped = cap_results(options)
    keyboard = results_keyboard(page, lang)
    await message.answer(_results_text(capped, lang), reply_markup=keyboard)


async def _edit_to_results(callback: CallbackQuery, options: list[TournamentOption], lang: str) -> None:
    page, capped = cap_results(options)
    keyboard = results_keyboard(page, lang)
    await callback.message.edit_text(_results_text(capped, lang), reply_markup=keyboard)


async def start_tournament_search(
    message: Message, state: FSMContext, lang: str, session: AsyncSession, gender: Gender
) -> None:
    await state.update_data(category=None, place=None)
    await _send_category_prompt(message, session, gender, lang)
    await state.set_state(TournamentSearch.waiting_category)


@router.callback_query(CategorySelectCallback.filter(), TournamentSearch.waiting_category)
async def handle_category(
    callback: CallbackQuery, callback_data: CategorySelectCallback, state: FSMContext, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    gender = crud.gender_for_account_code(account.gender)
    category = AgeCategory[callback_data.category]

    counts = await _category_counts(session, gender)
    if not counts.get(category, 0):
        # Re-verified at tap time, not just at render time (CLAUDE.md step
        # 5.1: "Tapping it re-shows the four buttons; it must never lead
        # to the place prompt and a dead end").
        await callback.message.edit_reply_markup(reply_markup=category_keyboard(counts, lang))
        await callback.answer()
        return

    await state.update_data(category=category.name, place=None)
    await callback.message.edit_reply_markup(reply_markup=None)
    # Confirms the tapped category before asking for a place, since
    # several screens later the player would otherwise have no way of
    # knowing which category they are in (CLAUDE.md step 5.3).
    category_line = category_selected_text(category, lang)
    place_line = t("tournament_search.ask_place", lang)
    await callback.message.answer(f"{category_line}\n{place_line}")
    await state.set_state(TournamentSearch.waiting_place)
    await callback.answer()


@router.message(TournamentSearch.waiting_place)
async def handle_place(message: Message, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)
    gender = crud.gender_for_account_code(account.gender)
    place = (message.text or "").strip()

    if not meets_min_place_length(place):
        await message.answer(t("tournament_search.place_too_short", lang))
        return

    data = await state.get_data()
    category = AgeCategory[data["category"]]

    eligible = await _eligible_options(session, gender, category)
    if not eligible:
        # Zero tournaments in this category at all -- "Zmień miejscowość"
        # would just repeat this dead end, so only offer a category change
        # (CLAUDE.md step 5.3).
        await message.answer(
            t("tournament_search.none_eligible", lang, days=crud.ELIGIBILITY_WINDOW_DAYS),
            reply_markup=none_eligible_keyboard(lang),
        )
        return

    matches = match_by_place(eligible, place)
    if not matches:
        await message.answer(t("tournament_search.no_place_matches", lang), reply_markup=no_matches_keyboard(lang))
        return

    await state.update_data(place=place)
    await _send_results(message, matches, lang=lang)


@router.callback_query(ShowAllTournamentsCallback.filter(), TournamentSearch.waiting_place)
async def handle_show_all(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    gender = crud.gender_for_account_code(account.gender)

    data = await state.get_data()
    category = AgeCategory[data["category"]]

    await state.update_data(place="")
    eligible = await _eligible_options(session, gender, category)
    await _edit_to_results(callback, eligible, lang=lang)
    await callback.answer()


@router.callback_query(ChangePlaceCallback.filter(), TournamentSearch.waiting_place)
async def handle_change_place(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    # Keeps the chosen category (CLAUDE.md step 5.1, "Navigation").
    await state.update_data(place=None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("tournament_search.ask_place", lang))
    await callback.answer()


@router.callback_query(ChangeCategoryCallback.filter(), TournamentSearch.waiting_place)
async def handle_change_category(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    gender = crud.gender_for_account_code(account.gender)

    # Clears the chosen category (CLAUDE.md step 5.1, "Navigation").
    await state.update_data(category=None, place=None)
    await callback.message.edit_reply_markup(reply_markup=None)
    await _send_category_prompt(callback.message, session, gender, lang)
    await state.set_state(TournamentSearch.waiting_category)
    await callback.answer()


@router.callback_query(TournamentSelectCallback.filter(), TournamentSearch.waiting_place)
async def handle_select(
    callback: CallbackQuery, callback_data: TournamentSelectCallback, state: FSMContext, session: AsyncSession
) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)
    gender = crud.gender_for_account_code(account.gender)

    tournament = await crud.get_tournament_by_guid(session, callback_data.guid)
    await callback.message.edit_reply_markup(reply_markup=None)

    if tournament is None or tournament.date_from is None:
        # A re-scrape deleted it between listing and tap (CLAUDE.md step
        # 5.1, "the silent no-op"): say so, then re-show current results
        # instead of leaving a dead button on screen.
        await callback.answer()
        await callback.message.answer(t("tournament_search.tournament_gone", lang))
        data = await state.get_data()
        category = AgeCategory[data["category"]]
        place = data.get("place") or ""
        eligible = await _eligible_options(session, gender, category)
        if not eligible:
            await callback.message.answer(
                t("tournament_search.none_eligible", lang, days=crud.ELIGIBILITY_WINDOW_DAYS),
                reply_markup=none_eligible_keyboard(lang),
            )
            return
        options = match_by_place(eligible, place) if place else eligible
        if place and not options:
            await callback.message.answer(
                t("tournament_search.no_place_matches", lang), reply_markup=no_matches_keyboard(lang)
            )
            return
        await _send_results(callback.message, options, lang=lang)
        return

    await state.update_data(tournament_guid=tournament.guid)
    confirmation = selection_confirmation_text(
        tournament.venue_city, tournament.wojewodztwo, tournament.age_category, tournament.date_from, lang
    )
    await callback.message.answer(confirmation)
    await callback.answer()
    await start_partner_selection(callback.message, state, lang, session, account, tournament)
