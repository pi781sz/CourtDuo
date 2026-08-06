"""Parses PZT ranking pages (Ranking.aspx?RCatID=...) and the ranking index.

Unlike scrapers.tournaments.parser, these selectors were NOT verified
against a live fetch — this environment has no network path to
portal.pzt.pl (outbound access is allowlisted and PZT isn't on it). The
approach below is deliberately defensive as a result:

- The ranking table itself is found by matching its header row's TEXT
  against known Polish column labels ("Zawodnik", "Klub", "Pkt", ...),
  not by CSS class. This sidesteps the exact problem CLAUDE.md flags for
  the tournament page — PZT rendering a "_light" (or any other) class
  variant — because no class name is involved in locating the table at
  all. If PZT wraps the real table in extra markup this still won't find
  it, which is what --dump-html / --dump-index-html are for (see
  __main__.py): run them against the live page and adjust
  _HEADER_FIELD_SYNONYMS / _find_ranking_table accordingly.
- The PZT ID is read from the query string of the player's row link
  (e.g. an href containing "...ID=12345"), since CLAUDE.md notes the
  alphabetical roster is the player lookup table and there's no need to
  scrape profile pages — the id just needs to travel with the row, not
  resolve to anything. A header column literally labelled an ID variant
  is preferred when present; the href is the fallback.

As with the tournament parser: if a page's shape doesn't match at all,
log and return no rows rather than writing garbage (see CLAUDE.md,
"Scraping etiquette").
"""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote

from selectolax.parser import HTMLParser, Node

from .models import RankingEntry, RankingList, Sort

logger = logging.getLogger(__name__)

_LISTA_RE = re.compile(r"lista\s+(\d{1,2})\s*/\s*(\d{4})", re.IGNORECASE)

_ID_PARAM_RE = re.compile(r"[?&][A-Za-z]*[Ii][Dd]=([^&#\"']+)")

# Column header text -> field name. Matched case-insensitively after
# whitespace normalization and stripping trailing "." / ":". Kept as sets
# of known PZT synonyms rather than a single guessed label per field,
# since Sort=LP and Sort=A pages are not assumed to use identical wording.
_HEADER_FIELD_SYNONYMS: dict[str, set[str]] = {
    "position": {"l.p.", "l.p", "lp", "poz", "poz.", "pozycja", "miejsce"},
    "pzt_id": {"id", "id zawodnika", "nr pzt", "numer pzt"},
    "full_name": {
        "zawodnik",
        "zawodniczka",
        "zawodnik/zawodniczka",
        "nazwisko i imię",
        "imię i nazwisko",
        "nazwisko",
        "gracz",
    },
    "club": {"klub"},
    "points": {"pkt", "pkt.", "punkty", "suma pkt", "suma punktów"},
    "birth_year": {"rok ur.", "rok ur", "rok urodzenia", "ur.", "rocznik"},
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _normalize_header(text: str) -> str:
    return _normalize(text).lower().rstrip(".:")


def _map_headers(header_cells: list[Node]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for i, cell in enumerate(header_cells):
        norm = _normalize_header(cell.text(strip=True))
        for field, synonyms in _HEADER_FIELD_SYNONYMS.items():
            if norm in synonyms:
                mapping[i] = field
                break
    return mapping


def _find_ranking_table(root: Node) -> tuple[Node, dict[int, str], list[Node]] | None:
    """Finds the table whose header row best matches known ranking columns.

    Scores every <table> on the page by how many header cells map to a
    known field and requires `full_name` to be among them, then returns
    the highest-scoring table along with its header mapping and data rows
    (header row excluded). Returns None if nothing on the page looks like
    a ranking table.
    """
    best: tuple[int, Node, dict[int, str], list[Node]] | None = None
    for table in root.css("table"):
        rows = table.css("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].css("th") or rows[0].css("td")
        mapping = _map_headers(header_cells)
        if "full_name" not in mapping.values():
            continue
        score = len(mapping)
        if best is None or score > best[0]:
            best = (score, table, mapping, rows[1:])
    if best is None:
        return None
    _, table, mapping, data_rows = best
    return table, mapping, data_rows


def _extract_pzt_id_from_row(row: Node) -> str | None:
    for anchor in row.css("a"):
        href = anchor.attributes.get("href") or ""
        match = _ID_PARAM_RE.search(href)
        if match:
            return unquote(match.group(1))
    return None


def _parse_int(raw: str) -> int | None:
    match = re.search(r"\d+", raw)
    if not match:
        return None
    return int(match.group(0))


def _parse_points(raw: str) -> int | float | None:
    text = raw.strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def _parse_row(
    row: Node,
    mapping: dict[int, str],
    ranking_list: RankingList,
    sort: Sort,
    year: int,
    month: int,
    source_url: str,
) -> RankingEntry | None:
    cells = row.css("td")
    if not cells:
        return None

    values: dict[str, str] = {}
    for idx, field in mapping.items():
        if idx < len(cells):
            values[field] = cells[idx].text(strip=True)

    full_name = _normalize(values.get("full_name", ""))
    if not full_name:
        return None

    pzt_id = values.get("pzt_id") or _extract_pzt_id_from_row(row)
    club = _normalize(values["club"]) if values.get("club") else None
    position = _parse_int(values["position"]) if values.get("position") else None
    points = _parse_points(values["points"]) if values.get("points") else None
    birth_year = _parse_int(values["birth_year"]) if values.get("birth_year") else None

    return RankingEntry(
        ranking_list=ranking_list,
        sort=sort,
        year=year,
        month=month,
        full_name=full_name,
        pzt_id=pzt_id,
        club=club,
        position=position,
        points=points,
        birth_year=birth_year,
        source_url=source_url,
    )


def parse_ranking_index(html: str) -> tuple[int, int] | None:
    """Finds the (year, month) of the currently published ranking list.

    PZT's index page (Ranking.aspx?RCatID=M) links to each published list
    as anchor text "lista <month> / <year>" (CLAUDE.md: publishes monthly,
    sometimes late — never guess this). Links are assumed most-recent
    first, so the first match in document order is treated as current.
    """
    tree = HTMLParser(html)
    if not tree.root:
        logger.error("Ranking index page failed to parse — empty document")
        return None
    for anchor in tree.root.css("a"):
        text = _normalize(anchor.text(strip=True))
        match = _LISTA_RE.search(text)
        if not match:
            continue
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return year, month
        logger.warning("Ranking index link had an out-of-range month, skipping: %r", text)
    logger.error("No 'lista X / YYYY' links found on ranking index page — page shape may have changed")
    return None


def parse_ranking_page(
    html: str,
    ranking_list: RankingList,
    sort: Sort,
    year: int,
    month: int,
    source_url: str,
) -> list[RankingEntry]:
    """Parses one Ranking.aspx?RCatID=...&Sort=... page into RankingEntry rows."""
    tree = HTMLParser(html)
    if not tree.root:
        logger.error("Ranking page failed to parse (%s) — empty document", source_url)
        return []

    found = _find_ranking_table(tree.root)
    if found is None:
        logger.error(
            "No ranking table found for %s Sort=%s %d/%d (%s) — page shape may have changed",
            ranking_list.code,
            sort.value,
            month,
            year,
            source_url,
        )
        return []

    _, mapping, data_rows = found
    entries = []
    for row in data_rows:
        entry = _parse_row(row, mapping, ranking_list, sort, year, month, source_url)
        if entry is None:
            text = row.text(strip=True)
            if text:
                logger.warning(
                    "Could not parse ranking row for %s Sort=%s: %.120r", ranking_list.code, sort.value, text
                )
            continue
        entries.append(entry)

    if not entries:
        logger.warning(
            "Ranking table found but zero entries parsed for %s Sort=%s %d/%d", ranking_list.code, sort.value, month, year
        )
    return entries


def find_entry_html_at(
    html: str,
    index: int = 0,
) -> str | None:
    """Returns the raw HTML of the ranking-row <tr> at `index` on a list page.

    Used by `--dump-html --index N` to inspect the exact markup PZT is
    currently rendering for a specific row (0-based, in page order,
    header row excluded), e.g. when the header-text match in
    `_find_ranking_table` stops finding the table or a row fails to
    parse.
    """
    tree = HTMLParser(html)
    if not tree.root:
        return None
    found = _find_ranking_table(tree.root)
    if found is None:
        return None
    _, _, data_rows = found
    if not 0 <= index < len(data_rows):
        return None
    return data_rows[index].html
