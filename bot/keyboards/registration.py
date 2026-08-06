"""Inline keyboards for the /start registration flow. Every button carries
its own answer as callback_data — CourtDuo has no free-text messaging
between users, and this flow doesn't need free text from the adult either
beyond the player name lookup itself (CLAUDE.md, "No free-text messaging
between users. Ever.").
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.formatting import format_position
from bot.i18n import t
from db.models import AccountRole


def role_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for role in AccountRole:
        builder.button(text=t(f"role.{role.value}", lang), callback_data=f"role:{role.value}")
    builder.adjust(1)
    return builder.as_markup()


def _club_label(club: str | None, lang: str) -> str:
    return club or t("common.unknown_club", lang)


def search_results_keyboard(lang: str, matches: list[dict]) -> InlineKeyboardMarkup:
    """One button per unique full name found, indexed into `matches` (the
    same list the FSM stores). Names shared by more than one player
    collapse into a single "pick by PZT ID" button rather than listing
    every candidate here (CLAUDE.md's registration step 5 is a distinct
    disambiguation step, not part of this list).
    """
    builder = InlineKeyboardBuilder()
    seen_names: set[str] = set()
    for idx, match in enumerate(matches):
        name = match["full_name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        group = [m for m in matches if m["full_name"] == name]
        if len(group) == 1:
            label = t(
                "registration.player_option",
                lang,
                name=name,
                club=_club_label(match["club"], lang),
                position=format_position(match["position"], lang),
            )
            builder.button(text=label, callback_data=f"player:{idx}")
        else:
            label = t("registration.player_group_option", lang, name=name, count=len(group))
            builder.button(text=label, callback_data=f"group:{idx}")
    builder.adjust(1)
    return builder.as_markup()


def group_disambiguation_keyboard(lang: str, matches: list[dict], group: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for match in group:
        idx = matches.index(match)
        label = t(
            "registration.player_option_with_id",
            lang,
            name=match["full_name"],
            club=_club_label(match["club"], lang),
            position=format_position(match["position"], lang),
            pzt_id=match["pzt_id"],
        )
        builder.button(text=label, callback_data=f"player:{idx}")
    builder.adjust(1)
    return builder.as_markup()


def add_another_or_done_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("registration.add_another", lang), callback_data="add_another")
    builder.button(text=t("registration.done", lang), callback_data="done")
    builder.adjust(1)
    return builder.as_markup()
