"""CLAUDE.md, "Registration flow": /start -> role -> player name search ->
(disambiguate if needed) -> link -> add another or done. Inline keyboard
buttons only, no free text except the player-name lookup itself.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.registration import (
    add_another_or_done_keyboard,
    group_disambiguation_keyboard,
    role_keyboard,
    search_results_keyboard,
)
from bot.lang import lang_for
from bot.player_search import search_players_by_name
from bot.states.registration import Registration
from db import crud
from db.models import AccountRole

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)

    if account is None:
        await message.answer(t("start.greeting", lang))
        await message.answer(t("start.ask_role", lang), reply_markup=role_keyboard(lang))
        await state.set_state(Registration.choosing_role)
        return

    await message.answer(t("start.greeting_returning", lang))
    await message.answer(t("start.ask_player_name", lang))
    await state.set_state(Registration.entering_player_name)


@router.callback_query(Registration.choosing_role, F.data.startswith("role:"))
async def on_role_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    role = AccountRole(callback.data.split(":", 1)[1])
    account = await crud.get_or_create_account(session, callback.from_user.id, role)
    lang = lang_for(account)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("start.ask_player_name", lang))
    await state.set_state(Registration.entering_player_name)


@router.message(Registration.entering_player_name, F.text)
async def on_player_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)

    players = await search_players_by_name(session, message.text)
    if not players:
        await message.answer(t("registration.no_matches", lang))
        return

    matches = []
    for player in players:
        ranking = await crud.get_latest_ranking_for_player(session, player.pzt_id)
        matches.append(
            {
                "pzt_id": player.pzt_id,
                "full_name": player.full_name,
                "club": player.club,
                "position": ranking.position if ranking else None,
            }
        )

    await state.update_data(search_matches=matches)
    await state.set_state(Registration.choosing_player)
    await message.answer(t("registration.choose_player", lang), reply_markup=search_results_keyboard(lang, matches))


@router.callback_query(Registration.choosing_player, F.data.startswith("group:"))
async def on_group_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    idx = int(callback.data.split(":", 1)[1])
    matches = (await state.get_data()).get("search_matches", [])
    if idx >= len(matches):
        await callback.answer(t("registration.expired_selection", lang), show_alert=True)
        return

    target_name = matches[idx]["full_name"]
    group = [m for m in matches if m["full_name"] == target_name]

    await callback.answer()
    await callback.message.edit_text(
        t("registration.choose_by_id", lang),
        reply_markup=group_disambiguation_keyboard(lang, matches, group),
    )


@router.callback_query(Registration.choosing_player, F.data.startswith("player:"))
async def on_player_chosen(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    idx = int(callback.data.split(":", 1)[1])
    matches = (await state.get_data()).get("search_matches", [])
    if idx >= len(matches) or account is None:
        await callback.answer(t("registration.expired_selection", lang), show_alert=True)
        return

    selected = matches[idx]
    await crud.link_player_to_account(session, account.id, selected["pzt_id"])

    await callback.answer()
    await callback.message.edit_text(t("registration.linked", lang, name=selected["full_name"]))
    await callback.message.answer(t("registration.what_next", lang), reply_markup=add_another_or_done_keyboard(lang))
    await state.set_state(Registration.post_link)
    await state.update_data(search_matches=[])


@router.callback_query(Registration.post_link, F.data == "add_another")
async def on_add_another(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("start.ask_player_name", lang))
    await state.set_state(Registration.entering_player_name)


@router.callback_query(Registration.post_link, F.data == "done")
async def on_done(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("registration.finished", lang))
    await state.clear()
