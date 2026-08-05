"""Tests for scrapers.tournaments.parser against real PZT markup.

The HTML fixtures below reproduce the actual CSS classes/structure PZT
renders on Tournament.aspx?CategoryID=... (verified against a live fetch),
trimmed to the fields CourtDuo keeps and with organiser/venue details
genericised. No player names appear anywhere in this file.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scrapers.tournaments.models import AgeCategory, Gender, PlayType, Tournament
from scrapers.tournaments.parser import parse_category_page

# Mirrors a real tournament block: Termin odwołań as a table
# (.tournAppContentColR_B_p0 / td.tournAppContentTdEntryFee), a
# "Miejsce rozgrywek" row with a województwo, and both a singles and a
# doubles event.
TOURNAMENT_WITH_TABLE_ODWOLANIA = """
<div class="tournAppContainer_B">
  <div class="tournAppTopMain1_B">
    <div class="tournAppTopMain2_B">
      <div class="tournAppTop_B" onclick="ToggleDisplay(3);">
        <div class="tournAppTopLeft_B_1">
          <div class="tournAppTopLeft_B">
            <div class="tournAppStatus_B"><div class="tournAppStatusNo"></div></div>
            <div class="tournAppName_B">OTK - OTK U18 o Puchar KT Testowy (grupowo-pucharowy)</div>
            <div class="tournAppRang_B_main">
              <div class="tournAppRang_B"><div class="tournAppRangCount">3</div><div class="tournAppRangContent">Ranga</div></div>
            </div>
          </div>
          <div class="tournAppTopCent_B">
            <span style="margin-right: 20px;">Od: 2026.08.07</span>
            Do: 2026.08.09
          </div>
          <div id="ctl00_dClubName" class="tournAppClubName_B">
            <div class="tournAppPlaceOfGameL_B">Organizator:</div>
            <div class="tournAppPlaceOfGameR_B">Klub Tenisowy Testowy</div>
          </div>
          <div id="ctl00_dPlaceOfGame" class="tournAppPlaceOfGame_B">
            <div class="tournAppPlaceOfGameL_B">Miejsce turnieju:</div>
            <div class="tournAppPlaceOfGameR_B">65-001 Zielona Gora, Testowa 1</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="tournAppContent_B" id="d3">
    <div id="ctl00_dTournDetails">
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Miejsce turnieju</div>
        <div class="tournAppContentColR_B">65-001 Zielona Gora, Testowa 1</div>
      </div>
      <div id="ctl00_pnlCourtPlaceOfGame">
        <div class="tournAppContentRow2_B">
          <div class="tournAppContentColLBn_B">Miejsce rozgrywek</div>
          <div class="tournAppContentColR_B dtlEvent">
            <table><tbody>
              <tr><td><div class="dDtlEvents_B"><div style="float:left;"> (lubuskie)</div></div></td></tr>
              <tr><td><div class="dDtlEvents_B"><div style="float:left;">65-762 Zielona Gora al. Testowa 1 (lubuskie)</div></div></td></tr>
            </tbody></table>
          </div>
        </div>
      </div>
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Termin zgłoszeń</div>
        <div class="tournAppContentColR_B">2026-07-31 23:59</div>
      </div>
      <div id="ctl00_dCancelDeadline" class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Termin odwołań</div>
        <div class="tournAppContentColR_B_p0">
          <table><tbody><tr>
            <td class="tournAppContentTdEntryFee">2026-08-03 (poniedziałek)<br>godz. 23:59</td>
            <td class="tournAppContentTdEntryFeeDescR">Odwołania wyłącznie za pomocą portalu TPO.</td>
          </tr></tbody></table>
        </div>
      </div>
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColLBn_B">Rozgrywki</div>
        <div class="tournAppContentColR_B dtlEvent">
          <table><tbody>
            <tr><td><div class="dDtlEventsMainCont1"><span class="tournAppEventsDescLeft">Kategoria: </span>Juniorzy - do 18 lat<br><div class="tournAppEventsDescLeft">Typ: </div><div class="tournAppEventsDescRight">Gra pojedyncza; Dziewczęta; Grupy - kazdy z kazdym 8</div></div></td></tr>
            <tr><td><div class="dDtlEventsMainCont1"><span class="tournAppEventsDescLeft">Kategoria: </span>Juniorzy - do 18 lat<br><div class="tournAppEventsDescLeft">Typ: </div><div class="tournAppEventsDescRight">Gra podwójna; Chłopcy; Grupowo-pucharowy 16</div></div></td></tr>
          </tbody></table>
        </div>
      </div>
      <a href="/TournamentResults.aspx?TournamentID=C949F78A-765D-4A49-8D2B-18267DB752F3" target="_blank">Szczegóły turnieju</a>
    </div>
  </div>
</div>
"""

# Mirrors the plain-text Termin odwołań shape, no Miejsce rozgrywek row
# (so wojewodztwo must come back None, not crash), winter date_from for
# the UTC+1 side of the search_closes_at test, and no doubles event.
TOURNAMENT_PLAIN_ODWOLANIA_NO_WOJEWODZTWO = """
<div class="tournAppContainer_B">
  <div class="tournAppTopMain1_B">
    <div class="tournAppTopMain2_B">
      <div class="tournAppTop_B" onclick="ToggleDisplay(4);">
        <div class="tournAppTopLeft_B_1">
          <div class="tournAppTopLeft_B">
            <div class="tournAppStatus_B"><div class="tournAppStatusNo"></div></div>
            <div class="tournAppName_B">WTK Juniorow bez debla</div>
            <div class="tournAppRang_B_main">
              <div class="tournAppRang_B"><div class="tournAppRangCount">5</div><div class="tournAppRangContent">Ranga</div></div>
            </div>
          </div>
          <div class="tournAppTopCent_B">
            <span style="margin-right: 20px;">Od: 2026.01.10</span>
            Do: 2026.01.12
          </div>
          <div id="ctl00_dClubName2" class="tournAppClubName_B">
            <div class="tournAppPlaceOfGameL_B">Organizator:</div>
            <div class="tournAppPlaceOfGameR_B">Inny Klub</div>
          </div>
          <div id="ctl00_dPlaceOfGame2" class="tournAppPlaceOfGame_B">
            <div class="tournAppPlaceOfGameL_B">Miejsce turnieju:</div>
            <div class="tournAppPlaceOfGameR_B">10-000 Krakow, Inna 2</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="tournAppContent_B" id="d4">
    <div id="ctl00_dTournDetails2">
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Termin zgłoszeń</div>
        <div class="tournAppContentColR_B">2025-12-20 23:59</div>
      </div>
      <div id="ctl00_dCancelDeadline2" class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Termin odwołań</div>
        <div class="tournAppContentColR_B">2026-01-06 17:00</div>
      </div>
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColLBn_B">Rozgrywki</div>
        <div class="tournAppContentColR_B dtlEvent">
          <table><tbody>
            <tr><td><div class="dDtlEventsMainCont1"><span class="tournAppEventsDescLeft">Kategoria: </span>Juniorzy - do 18 lat<br><div class="tournAppEventsDescLeft">Typ: </div><div class="tournAppEventsDescRight">Gra pojedyncza; Chłopcy; do 2 przegranych setow</div></div></td></tr>
          </tbody></table>
        </div>
      </div>
      <a href="/TournamentResults.aspx?TournamentID=9c858901-8a57-4791-81fe-4c455b099bc9" target="_blank">Szczegóły turnieju</a>
    </div>
  </div>
</div>
"""

SAMPLE_PAGE = (
    "<html><body><div class='tournamentList'>"
    + TOURNAMENT_WITH_TABLE_ODWOLANIA
    + TOURNAMENT_PLAIN_ODWOLANIA_NO_WOJEWODZTWO
    + "</div></body></html>"
)


def test_parses_both_tournaments():
    tournaments = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")
    assert len(tournaments) == 2


def test_first_tournament_fields():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[0]
    assert t.type_prefix == "OTK"
    assert "Puchar KT Testowy" in t.name
    assert t.ranga == 3
    assert t.date_from.isoformat() == "2026-08-07"
    assert t.date_to.isoformat() == "2026-08-09"
    assert t.organiser == "Klub Tenisowy Testowy"
    assert t.venue_address == "65-001 Zielona Gora, Testowa 1"
    assert t.wojewodztwo == "lubuskie"
    assert t.guid == "C949F78A-765D-4A49-8D2B-18267DB752F3"


def test_entry_deadline_is_a_datetime():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[0]
    assert t.entry_deadline == datetime(2026, 7, 31, 23, 59)


def test_termin_odwolan_table_shape_parsed_correctly():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[0]
    assert t.withdrawal_deadline == datetime(2026, 8, 3, 23, 59)


def test_termin_odwolan_plain_text_shape_parsed_correctly():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[1]
    assert t.withdrawal_deadline == datetime(2026, 1, 6, 17, 0)


def test_wojewodztwo_absent_returns_none_without_crashing():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[1]
    assert t.wojewodztwo is None


def test_events_modeled_separately_with_doubles_detected():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[0]
    assert len(t.events) == 2
    assert t.has_doubles is True
    doubles = t.doubles_events
    assert len(doubles) == 1
    assert doubles[0].play_type is PlayType.DOUBLES
    assert doubles[0].gender is Gender.BOYS


def test_tournament_without_doubles_event_is_flagged():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[1]
    assert t.has_doubles is False
    assert len(t.events) == 1
    assert t.events[0].play_type is PlayType.SINGLES


def test_removed_fields_are_gone_from_dataclass_and_json():
    import json

    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[0]
    for removed in ("director", "entry_fee", "court_surface", "court_count"):
        assert not hasattr(t, removed)
    payload = json.dumps(t.to_dict(), ensure_ascii=False)
    assert "director" not in payload
    assert "entry_fee" not in payload
    assert "court_surface" not in payload
    assert "court_count" not in payload


def test_to_dict_is_json_serializable():
    import json

    tournaments = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")
    json.dumps([t.to_dict() for t in tournaments], ensure_ascii=False)


def test_empty_page_logs_and_returns_empty():
    assert parse_category_page("<html><body>nothing here</body></html>", AgeCategory.KADECI, "u") == []


def test_search_closes_at_summer_is_utc_plus_2():
    # Poland is UTC+2 (CEST) in August, so 10:00 local is 08:00 UTC.
    t = Tournament(
        guid=None,
        name="test",
        type_prefix="OTK",
        age_category=AgeCategory.JUNIORZY,
        ranga=None,
        date_from=datetime(2026, 8, 7).date(),
        date_to=None,
        organiser=None,
        venue_address=None,
        wojewodztwo=None,
        entry_deadline=None,
        withdrawal_deadline=None,
    )
    closes_at = t.search_closes_at
    assert closes_at is not None
    assert closes_at.tzinfo is not None
    assert closes_at.astimezone(ZoneInfo("UTC")).isoformat() == "2026-08-07T08:00:00+00:00"


def test_search_closes_at_winter_is_utc_plus_1():
    # Poland is UTC+1 (CET) in January, so 10:00 local is 09:00 UTC.
    t = Tournament(
        guid=None,
        name="test",
        type_prefix="OTK",
        age_category=AgeCategory.JUNIORZY,
        ranga=None,
        date_from=datetime(2026, 1, 10).date(),
        date_to=None,
        organiser=None,
        venue_address=None,
        wojewodztwo=None,
        entry_deadline=None,
        withdrawal_deadline=None,
    )
    closes_at = t.search_closes_at
    assert closes_at is not None
    assert closes_at.astimezone(ZoneInfo("UTC")).isoformat() == "2026-01-10T09:00:00+00:00"


def test_search_closes_at_none_without_date_from():
    t = Tournament(
        guid=None,
        name="test",
        type_prefix="OTK",
        age_category=AgeCategory.JUNIORZY,
        ranga=None,
        date_from=None,
        date_to=None,
        organiser=None,
        venue_address=None,
        wojewodztwo=None,
        entry_deadline=None,
        withdrawal_deadline=None,
    )
    assert t.search_closes_at is None
