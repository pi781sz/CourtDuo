"""Tournament selection: age category first, then place (CLAUDE.md,
"Tournament selection"; build order step 5, revised by step 5.1). Pure
matching/labelling/pagination logic lives here so it can be unit-tested
without a database or Telegram; bot/handlers/tournament_search.py wires
the real category/place-typing/button-tapping handlers around it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from bot.i18n import t
from core.text import fold_diacritics
from db.models import AgeCategory, Tournament

logger = logging.getLogger(__name__)

MAX_RESULTS = 40
MIN_PLACE_LENGTH = 3

# CLAUDE.md, "Tournament selection": the button-label prefix derived from
# `ranga`, kept as one lookup rather than scattered conditionals. Rangas 6
# and 7 (internal club events) never reach this dict -- db.crud.HIDDEN_RANGAS
# excludes them at the query itself, so they're absent from CourtDuo
# entirely rather than mapping to a prefix here. A ranga with no entry
# (NULL, or any value PZT introduces later that we don't yet know) gets no
# prefix instead of a guess.
RANGA_PREFIX: dict[int, str] = {
    1: "MP",
    2: "SS",
    3: "OTK",
    4: "MW",
    5: "WTK",
}


def ranga_prefix(ranga: int | None) -> str | None:
    if ranga is None:
        return None
    return RANGA_PREFIX.get(ranga)


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
    lets match_by_place/tournament_label/cap_results be unit-tested with
    invented data and no database."""

    guid: str
    date_from: date
    venue_city: str | None
    wojewodztwo: str | None
    ranga: int | None = None


def to_option(tournament: Tournament) -> TournamentOption:
    if tournament.ranga is None:
        # CLAUDE.md step 5.4: shown anyway, with no prefix -- hiding it
        # would risk losing a real tournament, which is worse than an
        # unlabelled one -- but it's worth knowing which guids PZT served
        # with no ranga at all.
        logger.warning("Tournament %s has no ranga; showing with no type prefix", tournament.guid)
    return TournamentOption(
        guid=tournament.guid,
        date_from=tournament.date_from,
        venue_city=tournament.venue_city,
        wojewodztwo=tournament.wojewodztwo,
        ranga=tournament.ranga,
    )


def category_short_label(category: AgeCategory, lang: str) -> str:
    """"U12"/"U14"/"U16"/"U18" — from locales/<lang>.json, never the enum
    member name (CLAUDE.md step 5.1: "do not use the enum member names
    SKRZATY/MLODZICY/KADECI/JUNIORZY")."""
    return t(f"tournament_search.category_short.U{category.value}", lang)


def category_selected_text(category: AgeCategory, lang: str) -> str:
    """The step 5.3 fix: confirms the tapped category before asking for a
    place, so the player has a way of knowing which category they're in
    several screens later."""
    return t("tournament_search.category_selected", lang, category=category_short_label(category, lang))


def category_is_available(counts: dict[AgeCategory, int], category: AgeCategory) -> bool:
    return counts.get(category, 0) > 0


def meets_min_place_length(place: str) -> bool:
    return len(place.strip()) >= MIN_PLACE_LENGTH


def place_name(venue_city: str | None, wojewodztwo: str | None) -> str:
    """The ~1-in-100 tournaments PZT gives no venue_city fall back to
    wojewodztwo (CLAUDE.md, "Tournament selection")."""
    return venue_city or wojewodztwo or ""


def tournament_label(option: TournamentOption) -> str:
    """"<prefix> <venue_city> - <DD.MM.YYYY>", e.g. "WTK Uniejów -
    22.08.2026" (CLAUDE.md step 5.4). A plain hyphen, not the em dash used
    before this step. When `ranga` carries no prefix (NULL or unmapped),
    the label simply starts with the city."""
    prefix = ranga_prefix(option.ranga)
    place = place_name(option.venue_city, option.wojewodztwo)
    date_str = f"{option.date_from:%d.%m.%Y}"
    if prefix:
        return f"{prefix} {place} - {date_str}"
    return f"{place} - {date_str}"


def label_for_tournament(tournament: Tournament) -> str:
    """tournament_label() for an ORM row, for the screens that name a
    tournament outside the results keyboard — the invitation confirmation,
    the invitation itself, and every status line in step 7.

    Deliberately not `tournament_label(to_option(t))`: to_option logs a
    warning for a NULL ranga, which belongs to rendering the results list
    once, not to every invitation message that repeats the same label.

    Unlike the results list, this runs against a row an invitation already
    points at, weeks after it was chosen — long enough for a re-scrape to
    null the date out from under it. The label is display only, so a
    missing date costs the date, never the answer the label was attached
    to.
    """
    if tournament.date_from is None:
        logger.warning("Tournament %s has no date_from; labelling it without a date", tournament.guid)
        prefix = ranga_prefix(tournament.ranga)
        place = place_name(tournament.venue_city, tournament.wojewodztwo)
        return f"{prefix} {place}" if prefix else place
    return tournament_label(
        TournamentOption(
            guid=tournament.guid,
            date_from=tournament.date_from,
            venue_city=tournament.venue_city,
            wojewodztwo=tournament.wojewodztwo,
            ranga=tournament.ranga,
        )
    )


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
        date=f"{date_from:%d.%m.%Y}",
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


def cap_results(options: list[TournamentOption]) -> tuple[list[TournamentOption], bool]:
    """Returns (options capped at MAX_RESULTS, whether the cap was hit).

    Step 5.2 ("no pagination"): a single keyboard shows every eligible
    tournament, with no "show more" paging. The cap is a guard against a
    query bug ever producing a keyboard Telegram would reject, not a real
    limit -- with age category and gender filtering, real lists are under
    15.
    """
    if len(options) <= MAX_RESULTS:
        return options, False
    return options[:MAX_RESULTS], True
