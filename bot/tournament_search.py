"""Tournament selection by place (CLAUDE.md, "Tournament selection";
build order step 5). start_tournament_search() is the entry point step 4
calls after a successful registration and on /start for an already
registered player; bot/handlers/tournament_search.py wires the real
place-typing and button-tapping handlers around the pure functions below,
so the matching/labelling/pagination logic can be unit-tested without a
database or Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.i18n import t
from bot.states import TournamentSearch
from core.text import fold_diacritics
from db.models import Tournament

PAGE_SIZE = 8
MIN_PLACE_LENGTH = 3


async def start_tournament_search(message: Message, state: FSMContext, lang: str) -> None:
    await message.answer(t("tournament_search.ask_place", lang))
    await state.set_state(TournamentSearch.waiting_place)


@dataclass(frozen=True)
class TournamentOption:
    """The fields a tournament button needs, independent of the ORM row —
    lets match_by_place/tournament_label/paginate be unit-tested with
    invented data and no database."""

    guid: str
    date_from: date
    venue_city: str | None
    wojewodztwo: str | None


def to_option(tournament: Tournament) -> TournamentOption:
    return TournamentOption(
        guid=tournament.guid,
        date_from=tournament.date_from,
        venue_city=tournament.venue_city,
        wojewodztwo=tournament.wojewodztwo,
    )


def meets_min_place_length(place: str) -> bool:
    return len(place.strip()) >= MIN_PLACE_LENGTH


def tournament_label(option: TournamentOption) -> str:
    """"<venue_city> — <YYYY.MM.DD>", falling back to wojewodztwo for the
    ~1-in-100 tournaments PZT gives no venue_city (CLAUDE.md, "Tournament
    selection")."""
    place = option.venue_city or option.wojewodztwo or ""
    return f"{place} — {option.date_from:%Y.%m.%d}"


def match_by_place(options: list[TournamentOption], place: str) -> list[TournamentOption]:
    """Diacritic-insensitive substring match of `place` against each
    option's venue_city or wojewodztwo, checked separately (CLAUDE.md,
    "Tournament selection") so e.g. a query spanning a city/województwo
    boundary can't false-match. Caller must have already enforced
    meets_min_place_length."""
    folded_place = fold_diacritics(place)
    matches = []
    for option in options:
        city_match = folded_place in fold_diacritics(option.venue_city or "")
        region_match = folded_place in fold_diacritics(option.wojewodztwo or "")
        if city_match or region_match:
            matches.append(option)
    return matches


def paginate(options: list[TournamentOption], offset: int) -> tuple[list[TournamentOption], bool]:
    """Returns (this page of at most PAGE_SIZE options, whether more remain)."""
    page = options[offset : offset + PAGE_SIZE]
    has_more = offset + PAGE_SIZE < len(options)
    return page, has_more
