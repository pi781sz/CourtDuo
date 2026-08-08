"""Tournament selection: age category first, then place (CLAUDE.md,
"Tournament selection"; build order step 5, revised by step 5.1). Pure
matching/labelling/pagination logic lives here so it can be unit-tested
without a database or Telegram; bot/handlers/tournament_search.py wires
the real category/place-typing/button-tapping handlers around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from bot.i18n import t
from core.text import fold_diacritics
from db.models import AgeCategory, Tournament

PAGE_SIZE = 8
MIN_PLACE_LENGTH = 3

# Display order for the four category buttons (CLAUDE.md step 5.1: "all
# four are always offered", never filtered or reordered by the player's
# own age).
CATEGORY_ORDER: tuple[AgeCategory, ...] = (
    AgeCategory.SKRZATY,
    AgeCategory.MLODZICY,
    AgeCategory.KADECI,
    AgeCategory.JUNIORZY,
)


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


def category_short_label(category: AgeCategory, lang: str) -> str:
    """"U12"/"U14"/"U16"/"U18" — from locales/<lang>.json, never the enum
    member name (CLAUDE.md step 5.1: "do not use the enum member names
    SKRZATY/MLODZICY/KADECI/JUNIORZY")."""
    return t(f"tournament_search.category_short.U{category.value}", lang)


def category_is_available(counts: dict[AgeCategory, int], category: AgeCategory) -> bool:
    return counts.get(category, 0) > 0


def meets_min_place_length(place: str) -> bool:
    return len(place.strip()) >= MIN_PLACE_LENGTH


def place_name(venue_city: str | None, wojewodztwo: str | None) -> str:
    """The ~1-in-100 tournaments PZT gives no venue_city fall back to
    wojewodztwo (CLAUDE.md, "Tournament selection")."""
    return venue_city or wojewodztwo or ""


def tournament_label(option: TournamentOption) -> str:
    """"<venue_city> — <YYYY.MM.DD>"."""
    return f"{place_name(option.venue_city, option.wojewodztwo)} — {option.date_from:%Y.%m.%d}"


def selection_confirmation_text(
    venue_city: str | None, wojewodztwo: str | None, category: AgeCategory, date_from: date, lang: str
) -> str:
    """The step 5.1 fix-2 confirmation: town, age category and date
    together in one message, so a player can never mistake which
    tournament they picked before it feeds an invitation that cannot be
    cancelled."""
    return t(
        "tournament_search.selected",
        lang,
        place=place_name(venue_city, wojewodztwo),
        category=category_short_label(category, lang),
        date=f"{date_from:%Y.%m.%d}",
    )


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
