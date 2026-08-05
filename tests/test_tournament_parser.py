"""Tests for scrapers.tournaments.parser against synthetic PZT-shaped HTML.

The HTML below is hand-written to match the field list and label wording
in CLAUDE.md's "Data sources" section; it is not scraped data and contains
no real player, club, or organiser names.
"""

from __future__ import annotations

from scrapers.tournaments.models import AgeCategory, Gender, PlayType
from scrapers.tournaments.parser import parse_category_page

SAMPLE_PAGE = """
<html><body>
<div class="tournamentList">

  <div class="tournamentRow">
    <div class="tournamentName">OTK Skrzatow o Puchar Testowy</div>
    <div>Ranga: 3</div>
    <div>Od: 2026.08.07 Do: 2026.08.09</div>
    <div>Organizator: KT Testowy Klub</div>
    <div>Miejsce: ul. Sportowa 1, 00-000 Warszawa</div>
    <div>Wojewodztwo: mazowieckie</div>
    <div>Termin zgloszen: 2026.07.31</div>
    <div>Termin odwolan: 2026.08.05</div>
    <div>Dyrektor turnieju: Jan Kowalski, tel. 500600700, email: jan@example.pl</div>
    <div>Wpisowe: 60 zl</div>
    <div>Nawierzchnia: maczka ceglana</div>
    <div>Liczba kortow: 6</div>
    <div class="rozgrywki">
      Rozgrywki:
      Kategoria: U12 Typ: Gra pojedyncza; Chlopcy; do 2 przegranych setow
      Kategoria: U12 Typ: Gra podwojna; Chlopcy; best of 3
      Kategoria: U12 Typ: Gra pojedyncza; Dziewczeta; do 2 przegranych setow
    </div>
    <a href="Wyniki.aspx?ID=3fa85f64-5717-4562-b3fc-2c963f66afa6">Wyniki</a>
  </div>

  <div class="tournamentRow">
    <div class="tournamentName">WTK Mlodzikow bez debla</div>
    <div>Ranga: 5</div>
    <div>Od: 2026.09.01 Do: 2026.09.03</div>
    <div>Organizator: Inny Klub</div>
    <div>Miejsce: ul. Inna 2, 10-000 Krakow</div>
    <div>Wojewodztwo: malopolskie</div>
    <div>Termin zgloszen: 2026.08.20</div>
    <div>Termin odwolan: 2026.08.28</div>
    <div>Dyrektor turnieju: Anna Nowak, tel. 111222333, email: anna@example.pl</div>
    <div>Wpisowe: 50 zl</div>
    <div>Nawierzchnia: twarda</div>
    <div>Liczba kortow: 4</div>
    <div class="rozgrywki">
      Rozgrywki:
      Kategoria: U14 Typ: Gra pojedyncza; Chlopcy; do 2 przegranych setow
    </div>
    <a href="Wyniki.aspx?ID=9c858901-8a57-4791-81fe-4c455b099bc9">Wyniki</a>
  </div>

</div>
</body></html>
""".replace("zgloszen", "zgłoszeń").replace(
    "odwolan", "odwołań"
).replace("Wojewodztwo", "Województwo").replace(
    "Kortow", "Kortów"
).replace("kortow", "kortów").replace(
    "Chlopcy", "Chłopcy"
).replace("Dziewczeta", "Dziewczęta").replace(
    "podwojna", "podwójna"
).replace("zl", "zł").replace("maczka", "mączka")


def test_parses_both_tournaments():
    tournaments = parse_category_page(SAMPLE_PAGE, AgeCategory.SKRZATY, "https://example/test")
    assert len(tournaments) == 2


def test_first_tournament_fields():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.SKRZATY, "https://example/test")[0]
    assert t.type_prefix == "OTK"
    assert "Skrzatow" in t.name
    assert t.ranga == 3
    assert t.date_from.isoformat() == "2026-08-07"
    assert t.date_to.isoformat() == "2026-08-09"
    assert t.entry_deadline.isoformat() == "2026-07-31"
    assert t.withdrawal_deadline.isoformat() == "2026-08-05"
    assert t.organiser == "KT Testowy Klub"
    assert t.wojewodztwo == "mazowieckie"
    assert t.court_count == 6
    assert t.guid == "3fa85f64-5717-4562-b3fc-2c963f66afa6"
    assert t.director.name == "Jan Kowalski"
    assert t.director.phone == "500600700"
    assert t.director.email == "jan@example.pl"


def test_events_modeled_separately_with_doubles_detected():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.SKRZATY, "https://example/test")[0]
    assert len(t.events) == 3
    assert t.has_doubles is True
    doubles = t.doubles_events
    assert len(doubles) == 1
    assert doubles[0].play_type is PlayType.DOUBLES
    assert doubles[0].gender is Gender.BOYS


def test_tournament_without_doubles_event_is_flagged():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.SKRZATY, "https://example/test")[1]
    assert t.has_doubles is False
    assert len(t.events) == 1
    assert t.events[0].play_type is PlayType.SINGLES


def test_to_dict_is_json_serializable():
    import json

    tournaments = parse_category_page(SAMPLE_PAGE, AgeCategory.SKRZATY, "https://example/test")
    json.dumps([t.to_dict() for t in tournaments], ensure_ascii=False)


def test_empty_page_logs_and_returns_empty():
    assert parse_category_page("<html><body>nothing here</body></html>", AgeCategory.KADECI, "u") == []
