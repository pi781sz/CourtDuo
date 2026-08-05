"""Data model for scraped PZT tournaments.

Events are modelled separately from tournaments (see CLAUDE.md, "Data
sources"): a tournament is the overall competition, an event is one
`Kategoria: ... Typ: ...` line inside its `Rozgrywki` block. Most
tournaments have no `Gra podwójna` event at all, and those are the only
ones this product cares about — so `Tournament.doubles_events` /
`Event.is_doubles` are the fields everything downstream keys off.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date


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
class TournamentDirector:
    name: str | None = None
    phone: str | None = None
    email: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "phone": self.phone, "email": self.email}


@dataclass
class Tournament:
    guid: str | None
    name: str
    type_prefix: str
    age_category: AgeCategory
    ranga: int | None
    date_from: date | None
    date_to: date | None
    organiser: str | None
    venue_address: str | None
    wojewodztwo: str | None
    entry_deadline: date | None
    withdrawal_deadline: date | None
    director: TournamentDirector
    entry_fee: str | None
    court_surface: str | None
    court_count: int | None
    events: list[Event] = field(default_factory=list)
    source_url: str | None = None

    @property
    def doubles_events(self) -> list[Event]:
        return [e for e in self.events if e.is_doubles]

    @property
    def has_doubles(self) -> bool:
        return len(self.doubles_events) > 0

    def to_dict(self) -> dict:
        return {
            "guid": self.guid,
            "name": self.name,
            "type_prefix": self.type_prefix,
            "age_category": self.age_category.label,
            "age_category_id": self.age_category.value,
            "ranga": self.ranga,
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "organiser": self.organiser,
            "venue_address": self.venue_address,
            "wojewodztwo": self.wojewodztwo,
            "entry_deadline": self.entry_deadline.isoformat() if self.entry_deadline else None,
            "withdrawal_deadline": self.withdrawal_deadline.isoformat() if self.withdrawal_deadline else None,
            "director": self.director.to_dict(),
            "entry_fee": self.entry_fee,
            "court_surface": self.court_surface,
            "court_count": self.court_count,
            "has_doubles": self.has_doubles,
            "events": [e.to_dict() for e in self.events],
            "source_url": self.source_url,
        }
