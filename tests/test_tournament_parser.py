"""Tests for scrapers.tournaments.parser against real PZT markup.

The HTML fixtures below reproduce the actual CSS classes/structure PZT
renders on Tournament.aspx?CategoryID=... (verified against a live fetch),
trimmed to the fields CourtDuo keeps. No player names appear anywhere in
this file.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scrapers.tournaments.models import AgeCategory, Gender, PlayType, Tournament
from scrapers.tournaments.parser import extract_city, find_tournament_html_at, parse_category_page

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
    assert t.wojewodztwo == "lubuskie"
    assert t.guid == "C949F78A-765D-4A49-8D2B-18267DB752F3"
    assert t.venue_address == "65-001 Zielona Gora, Testowa 1"
    assert t.venue_city == "Zielona Gora"


def test_venue_address_absent_returns_none_without_crashing():
    t = parse_category_page(SAMPLE_PAGE, AgeCategory.JUNIORZY, "https://example/test")[1]
    assert t.venue_address is None
    assert t.venue_city is None


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
    for removed in ("director", "entry_fee", "court_surface", "court_count", "organiser"):
        assert not hasattr(t, removed)
    payload = json.dumps(t.to_dict(), ensure_ascii=False)
    assert "director" not in payload
    assert "entry_fee" not in payload
    assert "court_surface" not in payload
    assert "court_count" not in payload
    assert "organiser" not in payload


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
        wojewodztwo=None,
        entry_deadline=None,
        withdrawal_deadline=None,
    )
    assert t.search_closes_at is None


# Mirrors the four broken U18 blocks: tournAppTopCent_B renders with no
# "Od:"/"Do:" text at all (e.g. emoji-laden names on some group-play
# tournaments break PZT's normal date block), but tournAppTopRightConDate
# still carries the ISO start date, so date_from should fall back to it.
TOURNAMENT_MISSING_PRIMARY_DATE = """
<div class="tournAppContainer_B">
  <div class="tournAppTopMain1_B">
    <div class="tournAppTopMain2_B">
      <div class="tournAppTop_B" onclick="ToggleDisplay(5);">
        <div class="tournAppTopLeft_B_1">
          <div class="tournAppTopLeft_B">
            <div class="tournAppStatus_B"><div class="tournAppStatusNo"></div></div>
            <div class="tournAppName_B">WTK - \U0001F44BU18 chl\U0001F3BEdz\U0001F600Uniejow\U0001F600turniej grupowy\U0001F947\U0001F948\U0001F949</div>
            <div class="tournAppRang_B_main">
              <div class="tournAppRang_B"><div class="tournAppRangCount">4</div><div class="tournAppRangContent">Ranga</div></div>
            </div>
          </div>
          <div class="tournAppTopCent_B"></div>
          <div class="tournAppTopRightConDate">Turniej gł.: 2026-08-07</div>
        </div>
      </div>
    </div>
  </div>
  <div class="tournAppContent_B" id="d5">
    <div id="ctl00_dTournDetails5">
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Termin zgłoszeń</div>
        <div class="tournAppContentColR_B">2026-07-20 23:59</div>
      </div>
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColLBn_B">Rozgrywki</div>
        <div class="tournAppContentColR_B dtlEvent">
          <table><tbody>
            <tr><td><div class="dDtlEventsMainCont1"><span class="tournAppEventsDescLeft">Kategoria: </span>Juniorzy - do 18 lat<br><div class="tournAppEventsDescLeft">Typ: </div><div class="tournAppEventsDescRight">Gra podwójna; Chłopcy; Grupowo-pucharowy 16 Uwagi: Losowanie WKS-WZT Łódź, korty 1-4</div></div></td></tr>
          </tbody></table>
        </div>
      </div>
      <a href="/TournamentResults.aspx?TournamentID=aa11bb22-3344-5566-7788-99aabbccddee" target="_blank">Szczegóły turnieju</a>
    </div>
  </div>
</div>
"""

# No usable date anywhere: neither tournAppTopCent_B nor
# tournAppTopRightConDate parse. date_from must stay None and the parser
# must warn instead of writing garbage.
TOURNAMENT_NO_DATE_AT_ALL = """
<div class="tournAppContainer_B">
  <div class="tournAppTopMain1_B">
    <div class="tournAppTopMain2_B">
      <div class="tournAppTop_B" onclick="ToggleDisplay(6);">
        <div class="tournAppTopLeft_B_1">
          <div class="tournAppTopLeft_B">
            <div class="tournAppStatus_B"><div class="tournAppStatusNo"></div></div>
            <div class="tournAppName_B">MW Turniej bez daty</div>
            <div class="tournAppRang_B_main">
              <div class="tournAppRang_B"><div class="tournAppRangCount">7</div><div class="tournAppRangContent">Ranga</div></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="tournAppContent_B" id="d6">
    <div id="ctl00_dTournDetails6">
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColLBn_B">Rozgrywki</div>
        <div class="tournAppContentColR_B dtlEvent">
          <table><tbody>
            <tr><td><div class="dDtlEventsMainCont1"><span class="tournAppEventsDescLeft">Kategoria: </span>Juniorzy - do 18 lat<br><div class="tournAppEventsDescLeft">Typ: </div><div class="tournAppEventsDescRight">Gra pojedyncza; Chłopcy; do 2 przegranych setow</div></div></td></tr>
          </tbody></table>
        </div>
      </div>
      <a href="/TournamentResults.aspx?TournamentID=11223344-5566-7788-99aa-bbccddeeff00" target="_blank">Szczegóły turnieju</a>
    </div>
  </div>
</div>
"""


def test_draw_format_truncated_at_uwagi_marker():
    tournaments = parse_category_page(
        TOURNAMENT_MISSING_PRIMARY_DATE, AgeCategory.JUNIORZY, "https://example/test"
    )
    t = tournaments[0]
    doubles = t.doubles_events[0]
    assert doubles.draw_format == "Grupowo-pucharowy 16"
    assert "Uwagi:" in doubles.raw_text
    assert "Losowanie" in doubles.raw_text


def test_date_from_falls_back_to_top_right_con_date(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="scrapers.tournaments.parser"):
        tournaments = parse_category_page(
            TOURNAMENT_MISSING_PRIMARY_DATE, AgeCategory.JUNIORZY, "https://example/test"
        )
    t = tournaments[0]
    assert t.date_from.isoformat() == "2026-08-07"
    assert t.date_to is None
    assert any("falling back to tournAppTopRightConDate" in message for message in caplog.messages)


def test_missing_date_from_logs_warning_and_stays_none(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="scrapers.tournaments.parser"):
        tournaments = parse_category_page(TOURNAMENT_NO_DATE_AT_ALL, AgeCategory.JUNIORZY, "https://example/test")
    t = tournaments[0]
    assert t.date_from is None
    assert any("parsed with no date_from" in message for message in caplog.messages)


# Mirrors the "_light" header variant PZT renders for tournaments in
# certain statuses (e.g. tournAppStatusINPROGRESS): every header class gets
# a "_light" suffix (tournAppTopMain1_B_light, tournAppTopCent_B_light,
# etc). tournAppTopRightConDate's dDateStart is empty in this variant, so
# the fallback can't help here — date_from/date_to must come from the
# prefix-matched tournAppTopCent_B_light block itself.
TOURNAMENT_LIGHT_HEADER = """
<div class="tournAppContainer_B">
  <div class="tournAppTopMain1_B_light">
    <div class="tournAppTopMain2_B_light">
      <div class="tournAppTop_B" onclick="ToggleDisplay(7);">
        <div class="tournAppTopLeft_B_1_light">
          <div class="tournAppTopLeft_B">
            <div class="tournAppStatus_B"><div class="tournAppStatusINPROGRESS"></div></div>
            <div class="tournAppName_B">OTK Turniej w trakcie rozgrywania</div>
            <div class="tournAppRang_B_main">
              <div class="tournAppRang_B"><div class="tournAppRangCount">2</div><div class="tournAppRangContent">Ranga</div></div>
            </div>
          </div>
          <div class="tournAppTopCent_B_light">
            <span style="margin-right: 20px;">Od: 2026.09.14</span>
            Do: 2026.09.16
          </div>
          <div class="tournAppTopRightConDate"></div>
          <div id="ctl00_dClubName7" class="tournAppClubName_B_light">
            <div class="tournAppPlaceOfGameL_B">Organizator:</div>
            <div class="tournAppPlaceOfGameR_B">Klub W Trakcie</div>
          </div>
          <div id="ctl00_dPlaceOfGame7" class="tournAppPlaceOfGame_B_light">
            <div class="tournAppPlaceOfGameL_B">Miejsce turnieju:</div>
            <div class="tournAppPlaceOfGameR_B">00-001 Warszawa, Testowa 7</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="tournAppContent_B" id="d7">
    <div id="ctl00_dTournDetails7">
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColL_B">Termin zgłoszeń</div>
        <div class="tournAppContentColR_B">2026-09-01 23:59</div>
      </div>
      <div class="tournAppContentRow2_B">
        <div class="tournAppContentColLBn_B">Rozgrywki</div>
        <div class="tournAppContentColR_B dtlEvent">
          <table><tbody>
            <tr><td><div class="dDtlEventsMainCont1"><span class="tournAppEventsDescLeft">Kategoria: </span>Juniorzy - do 18 lat<br><div class="tournAppEventsDescLeft">Typ: </div><div class="tournAppEventsDescRight">Gra podwójna; Dziewczęta; Grupowo-pucharowy 16</div></div></td></tr>
          </tbody></table>
        </div>
      </div>
      <a href="/TournamentResults.aspx?TournamentID=55667788-99aa-bbcc-ddee-ff0011223344" target="_blank">Szczegóły turnieju</a>
    </div>
  </div>
</div>
"""


def test_light_header_variant_parses_both_dates():
    tournaments = parse_category_page(TOURNAMENT_LIGHT_HEADER, AgeCategory.JUNIORZY, "https://example/test")
    t = tournaments[0]
    assert t.date_from.isoformat() == "2026-09-14"
    assert t.date_to.isoformat() == "2026-09-16"


def test_find_tournament_html_at_returns_block_by_index():
    page = "<html><body>" + TOURNAMENT_WITH_TABLE_ODWOLANIA + TOURNAMENT_PLAIN_ODWOLANIA_NO_WOJEWODZTWO + "</body></html>"
    first = find_tournament_html_at(page, 0)
    second = find_tournament_html_at(page, 1)
    assert first is not None and "Puchar KT Testowy" in first
    assert second is not None and "Juniorow bez debla" in second


def test_find_tournament_html_at_out_of_range_returns_none():
    page = "<html><body>" + TOURNAMENT_WITH_TABLE_ODWOLANIA + "</body></html>"
    assert find_tournament_html_at(page, 5) is None


# extract_city -- every real "Miejsce turnieju" example verified against
# live U18 HTML on 2026-08-07 (CLAUDE.md, "Tournament selection"), plus a
# bare town with no postcode/comma and a string reducing to nothing.
def test_extract_city_strips_postcode_and_takes_town_before_comma():
    assert extract_city("99-210 Uniejów, ul. Sportowa obok Kompleksu⚽️⚽️im. Wł. Smolarka") == "Uniejów"


def test_extract_city_strips_postcode_lodz():
    assert extract_city("91-404 Łódź, Lumumby 22/26 (dojazd od ulicy Styrskiej)") == "Łódź"


def test_extract_city_zielona_gora_no_diacritics_in_source():
    assert extract_city("65-001 Zielona Gora, Wojska Polskiego 84A") == "Zielona Gora"


def test_extract_city_multiword_town_survives_intact():
    assert extract_city("05-825 Grodzisk Mazowiecki, Jowisza, Kozerki 92") == "Grodzisk Mazowiecki"


def test_extract_city_lowercase_input_title_cased():
    assert extract_city("62-010 pobiedziska, różana 4a") == "Pobiedziska"


def test_extract_city_uppercase_input_title_cased():
    assert extract_city("RYBNIK, Podmiejska 43") == "Rybnik"


def test_extract_city_bare_town_no_postcode_no_comma():
    assert extract_city("Kołobrzeg") == "Kołobrzeg"
    assert extract_city("Lublin") == "Lublin"


def test_extract_city_nothing_usable_returns_none():
    assert extract_city("12-345") is None
    assert extract_city("⚽️\U0001f600") is None
