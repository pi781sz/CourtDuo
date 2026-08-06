"""Tests for scrapers.rankings.parser.

These fixtures were NOT captured from a live fetch (see the module
docstring in scrapers/rankings/parser.py — this environment has no
network path to portal.pzt.pl) so they model plausible PZT markup: a
plain GridView-style <table> with a Polish header row and player rows
linking to a profile page that carries the PZT id in its query string.
All names below are invented for testing; none are real players.
"""

from __future__ import annotations

from scrapers.rankings.models import RankingList, Sort
from scrapers.rankings.parser import find_entry_html_at, parse_ranking_index, parse_ranking_page

RANKING_INDEX_PAGE = """
<html><body>
<div class="rankingLists">
  <a href="/Ranking.aspx?RCatID=M&Sort=LP&Year=2026&Month=8">lista 8 / 2026</a>
  <a href="/Ranking.aspx?RCatID=M&Sort=LP&Year=2026&Month=7">lista 7 / 2026</a>
  <a href="/Ranking.aspx?RCatID=M&Sort=LP&Year=2026&Month=6">lista 6 / 2026</a>
</div>
</body></html>
"""

RANKING_LP_PAGE = """
<html><body>
<table id="ctl00_gvRanking">
  <tr><th>L.p.</th><th>Zawodnik</th><th>Rok ur.</th><th>Klub</th><th>Pkt</th></tr>
  <tr>
    <td>1</td>
    <td><a href="/Player.aspx?ZawodnikID=100234">Testowski Jan</a></td>
    <td>2012</td>
    <td>KT Przykładowo</td>
    <td>340,50</td>
  </tr>
  <tr>
    <td>2</td>
    <td><a href="/Player.aspx?ZawodnikID=100777">Wzorcowy Adam</a></td>
    <td>2013</td>
    <td>UKS Demo Warszawa</td>
    <td>310</td>
  </tr>
</table>
</body></html>
"""

RANKING_A_PAGE = """
<html><body>
<table id="ctl00_gvRankingAlfa">
  <tr><th>Nazwisko i imię</th><th>Rok ur.</th><th>Klub</th></tr>
  <tr>
    <td><a href="/Player.aspx?ZawodnikID=100777">Wzorcowy Adam</a></td>
    <td>2013</td>
    <td>UKS Demo Warszawa</td>
  </tr>
  <tr>
    <td><a href="/Player.aspx?ZawodnikID=100234">Testowski Jan</a></td>
    <td>2012</td>
    <td>KT Przykładowo</td>
  </tr>
</table>
</body></html>
"""

# Models a leading caption row before the real header row, plus a sort
# indicator glyph on the actively-sorted column's header ("L.p. ▲") -- the
# working theory for why a live Sort=LP fetch was reported as returning "No
# ranking table found" while Sort=A on the same list worked (see the
# _find_ranking_table docstring in scrapers/rankings/parser.py). Names are
# invented, none are real players.
RANKING_LP_PAGE_WITH_CAPTION_ROW = """
<html><body>
<table id="ctl00_gvRanking">
  <tr><th colspan="5">Ranking Juniorzy Chłopcy - Sierpień 2026</th></tr>
  <tr><th>L.p. ▲</th><th>Zawodnik</th><th>Rok ur.</th><th>Klub</th><th>Pkt</th></tr>
  <tr>
    <td>1</td>
    <td><a href="/Player.aspx?ZawodnikID=100234">Testowski Jan</a></td>
    <td>2012</td>
    <td>KT Przykładowo</td>
    <td>340,50</td>
  </tr>
  <tr>
    <td>2</td>
    <td><a href="/Player.aspx?ZawodnikID=100777">Wzorcowy Adam</a></td>
    <td>2013</td>
    <td>UKS Demo Warszawa</td>
    <td>310</td>
  </tr>
</table>
</body></html>
"""

# Models PZT nesting an ITF ranking badge as a further descendant of the
# same name link -- Node.text() defaults to deep=True with no separator,
# so reading the whole cell/link concatenates the two with no boundary
# ("Błuś AleksanderMiejsce 77 na listach ITF 18"). Invented name.
RANKING_LP_PAGE_WITH_ITF_BADGE = """
<html><body>
<table id="ctl00_gvRanking">
  <tr><th>L.p.</th><th>Zawodnik</th><th>Rok ur.</th><th>Klub</th><th>Pkt</th></tr>
  <tr>
    <td>1</td>
    <td>
      <a href="/Player.aspx?ZawodnikID=100999">Błuś Aleksander<span class="itfBadge">Miejsce 77 na listach ITF 18</span></a>
    </td>
    <td>2011</td>
    <td>TKS Przykładowo</td>
    <td>420</td>
  </tr>
</table>
</body></html>
"""


def test_parse_ranking_index_returns_most_recent_period():
    assert parse_ranking_index(RANKING_INDEX_PAGE) == (2026, 8)


def test_parse_ranking_index_empty_page_returns_none():
    assert parse_ranking_index("<html><body>nothing here</body></html>") is None


def test_parse_lp_page_extracts_position_and_points():
    entries = parse_ranking_page(RANKING_LP_PAGE, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test")
    assert len(entries) == 2

    first = entries[0]
    assert first.position == 1
    assert first.full_name == "Testowski Jan"
    assert first.club == "KT Przykładowo"
    assert first.birth_year == 2012
    assert first.points == 340.5
    assert first.pzt_id == "100234"
    assert first.ranking_list is RankingList.M18
    assert first.sort is Sort.RANKED


def test_parse_lp_page_integer_points_stay_int():
    entries = parse_ranking_page(RANKING_LP_PAGE, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test")
    assert entries[1].points == 310
    assert isinstance(entries[1].points, int)


def test_parse_alphabetical_page_has_no_position():
    entries = parse_ranking_page(RANKING_A_PAGE, RankingList.M18, Sort.ALPHABETICAL, 2026, 8, "https://example/test")
    assert len(entries) == 2
    assert all(e.position is None for e in entries)
    assert entries[0].full_name == "Wzorcowy Adam"
    assert entries[0].pzt_id == "100777"


def test_pzt_id_falls_back_to_row_link_when_no_id_column():
    entries = parse_ranking_page(RANKING_A_PAGE, RankingList.M18, Sort.ALPHABETICAL, 2026, 8, "https://example/test")
    assert entries[1].pzt_id == "100234"


def test_empty_page_logs_and_returns_empty():
    assert parse_ranking_page("<html><body>nothing here</body></html>", RankingList.M18, Sort.RANKED, 2026, 8, "u") == []


def test_to_dict_is_json_serializable():
    import json

    entries = parse_ranking_page(RANKING_LP_PAGE, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test")
    json.dumps([e.to_dict() for e in entries], ensure_ascii=False)


def test_find_entry_html_at_returns_row_by_index():
    first = find_entry_html_at(RANKING_LP_PAGE, 0)
    second = find_entry_html_at(RANKING_LP_PAGE, 1)
    assert first is not None and "Testowski Jan" in first
    assert second is not None and "Wzorcowy Adam" in second


def test_find_entry_html_at_out_of_range_returns_none():
    assert find_entry_html_at(RANKING_LP_PAGE, 5) is None


def test_ranking_list_url_uses_code_sort_year_month():
    url = RankingList.M12.url(Sort.ALPHABETICAL, 2026, 3)
    assert url == "https://portal.pzt.pl/Ranking.aspx?RCatID=M12&Sort=A&Year=2026&Month=3"


def test_ranking_list_metadata():
    assert RankingList.W16.age_category_label == "Kadeci"
    assert RankingList.W16.gender_label == "Dziewczęta"


def test_lp_page_with_leading_caption_row_still_finds_table():
    entries = parse_ranking_page(
        RANKING_LP_PAGE_WITH_CAPTION_ROW, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test"
    )
    assert len(entries) == 2
    assert entries[0].full_name == "Testowski Jan"
    assert entries[0].position == 1
    assert entries[0].points == 340.5
    assert entries[0].birth_year == 2012


def test_sort_indicator_glyph_on_header_does_not_break_matching():
    entries = parse_ranking_page(
        RANKING_LP_PAGE_WITH_CAPTION_ROW, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test"
    )
    assert all(e.position is not None for e in entries)


def test_itf_badge_is_stripped_from_full_name():
    entries = parse_ranking_page(
        RANKING_LP_PAGE_WITH_ITF_BADGE, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test"
    )
    assert len(entries) == 1
    assert entries[0].full_name == "Błuś Aleksander"


def test_itf_badge_is_captured_as_itf_note():
    entries = parse_ranking_page(
        RANKING_LP_PAGE_WITH_ITF_BADGE, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test"
    )
    assert entries[0].itf_note == "Miejsce 77 na listach ITF 18"


def test_name_without_itf_badge_has_no_itf_note():
    entries = parse_ranking_page(RANKING_LP_PAGE, RankingList.M18, Sort.RANKED, 2026, 8, "https://example/test")
    assert entries[0].itf_note is None


def test_itf_badge_flat_text_falls_back_to_miejsce_cut():
    flat_page = """
    <html><body>
    <table id="ctl00_gvRanking">
      <tr><th>L.p.</th><th>Zawodnik</th><th>Klub</th></tr>
      <tr>
        <td>1</td>
        <td>Kowalski AntoniMiejsce 12 na listach ITF 16</td>
        <td>MKT Przykładowo</td>
      </tr>
    </table>
    </body></html>
    """
    entries = parse_ranking_page(flat_page, RankingList.M16, Sort.RANKED, 2026, 8, "https://example/test")
    assert len(entries) == 1
    assert entries[0].full_name == "Kowalski Antoni"
    assert entries[0].itf_note == "Miejsce 12 na listach ITF 16"
