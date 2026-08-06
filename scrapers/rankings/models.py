"""Data model for scraped PZT ranking lists.

Eight lists: the four junior categories (Skrzaty/Młodzicy/Kadeci/Juniorzy,
see scrapers.tournaments.models.AgeCategory) times two genders. PZT ranking
codes follow the pattern {M|W}{12|14|16|18} — M for Chłopcy (boys), W for
Dziewczęta (girls) — matching scrapers.tournaments.models.RANKING_CODE,
which is how CourtDuo picks a list for a given tournament event. Kept as
its own enum here so scrapers.rankings has no import-time dependency on
the tournament scraper.

Sort=A (alphabetical) is the player lookup table used for registration
(see CLAUDE.md, "Registration flow") — it has no meaningful ranking
`position`. Sort=LP (ranked order) is where `position` comes from. Both
are scraped for every list; RankingEntry.sort records which one produced
a given row.

`itf_note` holds an ITF ranking badge PZT sometimes renders next to a
player's name (see scrapers.rankings.parser) — kept separate from
`full_name` rather than discarded since it's cheap to carry along, but
it is not itself validated/parsed into a structured value.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Sort(enum.Enum):
    RANKED = "LP"
    ALPHABETICAL = "A"


class RankingList(enum.Enum):
    M12 = ("M12", "Skrzaty", "Chłopcy")
    W12 = ("W12", "Skrzaty", "Dziewczęta")
    M14 = ("M14", "Młodzicy", "Chłopcy")
    W14 = ("W14", "Młodzicy", "Dziewczęta")
    M16 = ("M16", "Kadeci", "Chłopcy")
    W16 = ("W16", "Kadeci", "Dziewczęta")
    M18 = ("M18", "Juniorzy", "Chłopcy")
    W18 = ("W18", "Juniorzy", "Dziewczęta")

    def __new__(cls, code: str, age_category_label: str, gender_label: str) -> "RankingList":
        obj = object.__new__(cls)
        obj._value_ = code
        obj.code = code
        obj.age_category_label = age_category_label
        obj.gender_label = gender_label
        return obj

    def url(self, sort: Sort, year: int, month: int) -> str:
        return (
            f"https://portal.pzt.pl/Ranking.aspx?RCatID={self.code}"
            f"&Sort={sort.value}&Year={year}&Month={month}"
        )


# PZT's index page for discovering the currently published list. Any
# RCatID works for this since PZT publishes all categories together each
# month (see CLAUDE.md, "Rankings"); RCatID=M is just the one specified.
RANKING_INDEX_URL = "https://portal.pzt.pl/Ranking.aspx?RCatID=M"


@dataclass
class RankingEntry:
    ranking_list: RankingList
    sort: Sort
    year: int
    month: int
    full_name: str
    pzt_id: str | None
    club: str | None
    position: int | None
    points: int | None
    birth_year: int | None
    itf_note: str | None
    source_url: str

    def to_dict(self) -> dict:
        return {
            "ranking_list": self.ranking_list.code,
            "age_category": self.ranking_list.age_category_label,
            "gender": self.ranking_list.gender_label,
            "sort": self.sort.value,
            "year": self.year,
            "month": self.month,
            "full_name": self.full_name,
            "pzt_id": self.pzt_id,
            "club": self.club,
            "position": self.position,
            "points": self.points,
            "birth_year": self.birth_year,
            "itf_note": self.itf_note,
            "source_url": self.source_url,
        }
