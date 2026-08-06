"""Parses PZT ranking pages (Ranking.aspx?RCatID=...&Sort=A) and the ranking index.

Unlike scrapers.tournaments.parser, these selectors were NOT verified
against a live fetch — this environment has no network path to
portal.pzt.pl (outbound access is allowlisted and PZT isn't on it, and
that has been re-confirmed: the agent egress proxy returns a policy
403 for portal.pzt.pl). The approach below is deliberately defensive as
a result:

- The ranking table itself is found by matching its header row's TEXT
  against known Polish column labels ("Zawodnik", "Klub", ...), not by
  CSS class. This sidesteps the exact problem CLAUDE.md flags for the
  tournament page — PZT rendering a "_light" (or any other) class
  variant — because no class name is involved in locating the table at
  all. If PZT wraps the real table in extra markup this still won't find
  it, which is what --dump-html / --dump-index-html are for (see
  __main__.py): run them against the live page and adjust
  _HEADER_FIELD_SYNONYMS / _find_ranking_table accordingly.
- `_find_ranking_table` does not assume the header row is exactly
  `rows[0]` of the table — it scans the first few rows of each table for
  one that maps known columns, so a leading caption/title row PZT may
  render on some views doesn't blank out detection.
- The player-name cell also gets the same treatment for a different
  reason: PZT apparently renders an ITF ranking badge as a further
  descendant of the same name link (e.g. "Błuś Aleksander" plus a nested
  "Miejsce 77 na listach ITF 18" span). Node.text() defaults to
  `deep=True` with an empty separator, so reading the whole cell/link
  glues the two together with no boundary. `_extract_name_and_itf_note`
  reads the name node's own text only (`deep=False`) to avoid pulling in
  that descendant, with a "Miejsce" cut as a last-resort fallback for the
  case where there's no enclosing element to exclude at all.
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

from .models import RankingEntry, RankingList

logger = logging.getLogger(__name__)

_LISTA_RE = re.compile(r"lista\s+(\d{1,2})\s*/\s*(\d{4})", re.IGNORECASE)

_ID_PARAM_RE = re.compile(r"[?&][A-Za-z]*[Ii][Dd]=([^&#\"']+)")

# Column header text -> field name. Matched case-insensitively after
# whitespace normalization and stripping trailing "." / ":". Kept as sets
# of known PZT synonyms rather than a single guessed label per field,
# since page wording is not assumed exact. If a real page uses wording
# outside these sets the column is simply left unmapped rather than
# silently mis-mapped, and the unmatched header text is logged at DEBUG.
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
}

# Sort-order indicator characters PZT (or a browser rendering it) may
# append/prepend to the currently-sorted column's header text (e.g. "L.p. ▲").
_SORT_INDICATOR_CHARS = "▲▼△▽↑↓"

# How many leading rows of a table are checked for a header match before
# giving up on that table. >1 so a leading caption/title row (present on
# some views, absent on others) doesn't hide the real header from row 0.
_MAX_HEADER_ROW_SCAN = 3

_ITF_BADGE_MARKER = "Miejsce"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _normalize_header(text: str) -> str:
    stripped = text.strip(_SORT_INDICATOR_CHARS + " \t\n\r")
    return _normalize(stripped).lower().rstrip(".:")


def _map_headers(header_cells: list[Node]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for i, cell in enumerate(header_cells):
        norm = _normalize_header(cell.text(strip=True))
        matched = False
        for field, synonyms in _HEADER_FIELD_SYNONYMS.items():
            if norm in synonyms:
                mapping[i] = field
                matched = True
                break
        if not matched and norm:
            logger.debug("Ranking table header cell did not match any known field: %r", norm)
    return mapping


def _find_ranking_table(root: Node) -> tuple[Node, dict[int, str], list[Node]] | None:
    """Finds the table whose header row best matches known ranking columns.

    Scores every <table> on the page by how many header cells map to a
    known field and requires `full_name` to be among them, then returns
    the highest-scoring table along with its header mapping and data rows
    (header row excluded). Returns None if nothing on the page looks like
    a ranking table.

    The header row is not assumed to be `rows[0]`: the first
    `_MAX_HEADER_ROW_SCAN` rows of each table are checked in order and the
    first one that maps a `full_name` column wins, so a leading
    caption/title row present on only some views doesn't blank out
    detection (see module docstring).
    """
    best: tuple[int, Node, dict[int, str], list[Node]] | None = None
    for table in root.css("table"):
        rows = table.css("tr")
        if len(rows) < 2:
            continue
        for header_idx in range(min(_MAX_HEADER_ROW_SCAN, len(rows) - 1)):
            header_row = rows[header_idx]
            header_cells = header_row.css("th") or header_row.css("td")
            if not header_cells:
                continue
            mapping = _map_headers(header_cells)
            if "full_name" not in mapping.values():
                continue
            score = len(mapping)
            if best is None or score > best[0]:
                best = (score, table, mapping, rows[header_idx + 1 :])
            break
    if best is None:
        return None
    _, table, mapping, data_rows = best
    return table, mapping, data_rows


def _extract_name_and_itf_note(cell: Node) -> tuple[str, str | None]:
    """Splits a ranking name cell into the player's name and an optional ITF note.

    Reads the name node's own text (`deep=False`) rather than the full
    cell/link text, so a badge PZT renders as a descendant of the same
    node (e.g. an ITF ranking note nested inside the name link) isn't
    concatenated onto the name with no separator — see module docstring.
    Falls back to cutting at the literal "Miejsce" marker for the rare
    case where the name and badge are plain sibling text nodes with no
    enclosing element to exclude at all.
    """
    name_node = cell.css_first("a") or cell
    own_text = _normalize(name_node.text(deep=False, strip=True))
    full_text = _normalize(name_node.text(deep=True, separator=" ", strip=True))

    name = own_text or full_text
    itf_note: str | None = None

    marker_idx = name.find(_ITF_BADGE_MARKER)
    if marker_idx != -1:
        itf_note = name[marker_idx:].strip()
        name = name[:marker_idx].strip()
    elif own_text and full_text != own_text and full_text.startswith(own_text):
        remainder = full_text[len(own_text) :].strip()
        if remainder:
            itf_note = remainder

    return name, (itf_note or None)


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


def _parse_row(
    row: Node,
    mapping: dict[int, str],
    ranking_list: RankingList,
    year: int,
    month: int,
    source_url: str,
) -> RankingEntry | None:
    cells = row.css("td")
    if not cells:
        return None

    values: dict[str, str] = {}
    itf_note: str | None = None
    for idx, field in mapping.items():
        if idx >= len(cells):
            continue
        if field == "full_name":
            name, itf_note = _extract_name_and_itf_note(cells[idx])
            values[field] = name
        else:
            values[field] = cells[idx].text(strip=True)

    full_name = _normalize(values.get("full_name", ""))
    if not full_name:
        return None

    pzt_id = values.get("pzt_id") or _extract_pzt_id_from_row(row)
    club = _normalize(values["club"]) if values.get("club") else None
    position = _parse_int(values["position"]) if values.get("position") else None

    return RankingEntry(
        ranking_list=ranking_list,
        year=year,
        month=month,
        full_name=full_name,
        pzt_id=pzt_id,
        club=club,
        position=position,
        itf_note=itf_note,
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
    year: int,
    month: int,
    source_url: str,
) -> list[RankingEntry]:
    """Parses one Ranking.aspx?RCatID=...&Sort=A page into RankingEntry rows."""
    tree = HTMLParser(html)
    if not tree.root:
        logger.error("Ranking page failed to parse (%s) — empty document", source_url)
        return []

    found = _find_ranking_table(tree.root)
    if found is None:
        logger.error(
            "No ranking table found for %s %d/%d (%s) — page shape may have changed",
            ranking_list.code,
            month,
            year,
            source_url,
        )
        return []

    _, mapping, data_rows = found
    entries = []
    for row in data_rows:
        entry = _parse_row(row, mapping, ranking_list, year, month, source_url)
        if entry is None:
            text = row.text(strip=True)
            if text:
                logger.warning("Could not parse ranking row for %s: %.120r", ranking_list.code, text)
            continue
        entries.append(entry)

    if not entries:
        logger.warning("Ranking table found but zero entries parsed for %s %d/%d", ranking_list.code, month, year)
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
