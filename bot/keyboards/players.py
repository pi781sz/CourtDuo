from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.i18n import t
from db.models import Player


def my_players_keyboard(lang: str, players: list[Player]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=t("my_players.remove_button", lang, name=player.full_name),
            callback_data=f"myplayers_remove:{player.pzt_id}",
        )
    builder.adjust(1)
    return builder.as_markup()


def remove_confirm_keyboard(lang: str, pzt_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("my_players.confirm_yes", lang), callback_data=f"myplayers_remove_confirm:{pzt_id}")
    builder.button(text=t("my_players.confirm_no", lang), callback_data="myplayers_remove_cancel")
    builder.adjust(2)
    return builder.as_markup()
