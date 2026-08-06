"""/moi_zawodnicy — list the players linked to the caller's account, with
a remove button per player (inline keyboard only, confirmed with a second
tap, per CLAUDE.md's no-free-text rule).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.i18n import t
from bot.keyboards.players import my_players_keyboard, remove_confirm_keyboard
from bot.lang import lang_for
from db import crud

router = Router(name="my_players")


@router.message(Command("moi_zawodnicy"))
async def cmd_my_players(message: Message, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, message.from_user.id)
    lang = lang_for(account)

    if account is None:
        await message.answer(t("my_players.no_account", lang))
        return

    players = await crud.list_account_players(session, account.id)
    if not players:
        await message.answer(t("my_players.empty", lang))
        return

    await message.answer(t("my_players.title", lang), reply_markup=my_players_keyboard(lang, players))


@router.callback_query(F.data.startswith("myplayers_remove:"))
async def on_remove_requested(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    pzt_id = callback.data.split(":", 1)[1]
    player = await crud.get_player_by_pzt_id(session, pzt_id)
    name = player.full_name if player else pzt_id

    await callback.answer()
    await callback.message.answer(
        t("my_players.confirm_remove", lang, name=name),
        reply_markup=remove_confirm_keyboard(lang, pzt_id),
    )


@router.callback_query(F.data.startswith("myplayers_remove_confirm:"))
async def on_remove_confirmed(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    pzt_id = callback.data.split(":", 1)[1]
    player = await crud.get_player_by_pzt_id(session, pzt_id)
    name = player.full_name if player else pzt_id

    if account is not None:
        await crud.unlink_player_from_account(session, account.id, pzt_id)

    await callback.answer()
    await callback.message.edit_text(t("my_players.removed", lang, name=name))


@router.callback_query(F.data == "myplayers_remove_cancel")
async def on_remove_cancelled(callback: CallbackQuery, session: AsyncSession) -> None:
    account = await crud.get_account_by_telegram_id(session, callback.from_user.id)
    lang = lang_for(account)

    await callback.answer()
    await callback.message.edit_text(t("my_players.remove_cancelled", lang))
