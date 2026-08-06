"""Data model for scraped PZT tournaments.

Events are modelled separately from tournaments (see CLAUDE.md, "Data
sources"): a tournament is the overall competition, an event is one
`Kategoria: ... Typ: ...` line inside its `Rozgrywki` block. Most
tournaments have no `Gra podwójna` event at all, and those are the only
ones this product cares about — so `Tournament.doubles_events` /
`Event.is_doubles` are the fields everything downstream keys off.

Director, referee, entry fee, court surface/count and ball brand are
deliberately not modelled — CourtDuo has no use for them, and entry_fee
in particular carries the organiser's bank account number, which has no
business in a public repository.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

_WARSAW_TZ = ZoneInfo("Europe/Warsaw")
_UTC = ZoneInfo("UTC")


class AgeCategory(enum.Enum):
    """The four junior categories in scope. Adult (CategoryID=19) is out of scope."""

    SKRZATY = 12
    MLODZICY = 14
    KADECI = 16
    JUNIORZY = 18

    @property
    def label(self) -> str:
        return {
            AgeCategory.SKRZATY: "Skrzaty",
            AgeCategory.MLODZICY: "Młodzicy",
            AgeCategory.KADECI: "Kadeci",
            AgeCategory.JUNIORZY: "Juniorzy",
        }[self]

    @property
    def url(self) -> str:
        return f"https://portal.pzt.pl/Tournament.aspx?CategoryID={self.value}"


class Gender(enum.Enum):
    BOYS = "Chłopcy"
    GIRLS = "Dziewczęta"


class PlayType(enum.Enum):
    SINGLES = "Gra pojedyncza"
    DOUBLES = "Gra podwójna"


# Gender + age category -> PZT ranking list code, e.g. U12 boys -> "M12".
RANKING_CODE = {
    (AgeCategory.SKRZATY, Gender.BOYS): "M12",
    (AgeCategory.SKRZATY, Gender.GIRLS): "W12",
    (AgeCategory.MLODZICY, Gender.BOYS): "M14",
    (AgeCategory.MLODZICY, Gender.GIRLS): "W14",
    (AgeCategory.KADECI, Gender.BOYS): "M16",
    (AgeCategory.KADECI, Gender.GIRLS): "W16",
    (AgeCategory.JUNIORZY, Gender.BOYS): "M18",
    (AgeCategory.JUNIORZY, Gender.GIRLS): "W18",
}


def resolve_ranking_code(age_category: AgeCategory, gender: Gender) -> str:
    return RANKING_CODE[(age_category, gender)]


@dataclass
class Event:
    """One `Kategoria: ... Typ: ...` line inside a tournament's `Rozgrywki` block."""

    category_label: str
    play_type: PlayType
    gender: Gender
    draw_format: str
    raw_text: str

    @property
    def is_doubles(self) -> bool:
        return self.play_type is PlayType.DOUBLES

    def to_dict(self) -> dict:
        return {
            "category_label": self.category_label,
            "play_type": self.play_type.value,
            "gender": self.gender.value,
            "draw_format": self.draw_format,
            "is_doubles": self.is_doubles,
            "raw_text": self.raw_text,
        }


@dataclass
class Tournament:
    guid: str | None
    name: str
    type_prefix: str
    age_category: AgeCategory
    ranga: int | None
    date_from: date | None
    date_to: date | None
    wojewodztwo: str | None
    entry_deadline: datetime | None
    withdrawal_deadline: datetime | None
    events: list[Event] = field(default_factory=list)
    source_url: str | None = None

    @property
    def doubles_events(self) -> list[Event]:
        return [e for e in self.events if e.is_doubles]

    @property
    def has_doubles(self) -> bool:
        return len(self.doubles_events) > 0

    @property
    def search_closes_at(self) -> datetime | None:
        """UTC instant at which searches for this tournament close.

        Per CLAUDE.md, "Search expiry rule": searches stay open until 10:00
        Europe/Warsaw on the tournament's start date, not the (much
        earlier) entry deadline — doubles partners are often found at the
        venue on the morning of play. Poland's UTC offset changes between
        summer and winter, so this must go through zoneinfo rather than a
        hardcoded offset.
        """
        if self.date_from is None:
            return None
        local = datetime.combine(self.date_from, time(10, 0), tzinfo=_WARSAW_TZ)
        return local.astimezone(_UTC)

    def to_dict(self) -> dict:
        closes_at = self.search_closes_at
        return {
            "guid": self.guid,
            "name": self.name,
            "type_prefix": self.type_prefix,
            "age_category": self.age_category.label,
            "age_category_id": self.age_category.value,
            "ranga": self.ranga,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "wojewodztwo": self.wojewodztwo,
            "entry_deadline": self.entry_deadline.isoformat() if self.entry_deadline else None,
            "withdrawal_deadline": self.withdrawal_deadline.isoformat() if self.withdrawal_deadline else None,
            "search_closes_at": closes_at.isoformat() if closes_at else None,
            "has_doubles": self.has_doubles,
            "events": [e.to_dict() for e in self.events],
            "source_url": self.source_url,
        }
