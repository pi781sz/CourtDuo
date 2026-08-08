"""Parses PZT tournament listing pages (Tournament.aspx?CategoryID=...).

Selectors are anchored on the CSS classes PZT actually renders (verified
against a live fetch of Tournament.aspx?CategoryID=18, see
tests/test_tournament_parser.py for the fixture), not guessed from field
descriptions. Detail rows (div.tournAppContentRow2_B) are matched by their
label TEXT rather than by position, since PZT reorders/omits rows per
tournament (e.g. "Miejsce rozgrywek" is absent when the venue has no
separate court-location table).

If PZT changes these classes or label wording, `parse_category_page` logs
and skips the tournament instead of writing partial/garbage data (see
CLAUDE.md, "Scraping etiquette").

PZT also renders a "_light" variant of the header classes for tournaments
in certain statuses (e.g. tournAppStatusINPROGRESS): tournAppTopMain1_B,
tournAppTopMain2_B, tournAppTopLeft_B_1, tournAppTopCent_B,
tournAppClubName_B, tournAppPlaceOfGame_B, tournAppHideDetails and
tournAppShowDetails each have a "tournAppXxx_light" counterpart. Header
elements are matched by class PREFIX (`_find_by_class_prefix`), never by
exact token, so both variants are caught.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from selectolax.parser import HTMLParser, Node

from .models import AgeCategory, Event, Gender, PlayType, Tournament

logger = logging.getLogger(__name__)

TYPE_PREFIXES = ("OTK SS", "OTK", "WTK", "MW")
_TYPE_PREFIX_RE = re.compile(r"^\s*(" + "|".join(re.escape(p) for p in TYPE_PREFIXES) + r")\b")

_GUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

_DATE_RANGE_RE = re.compile(r"Od:\s*(\d{4}\.\d{2}\.\d{2})\s*Do:\s*(\d{4}\.\d{2}\.\d{2})")

# Fallback source for date_from: div.tournAppTopRightConDate renders
# "Turniej gł.: 2026-08-07" (ISO, start date only) and is present even on
# the handful of tournaments where tournAppTopCent_B's Od:/Do: block
# doesn't parse (see _parse_tournament_block).
_FALLBACK_DATE_FROM_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

_DATETIME_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2}).*?(?P<hour>\d{2}):(?P<minute>\d{2})"
)

_EVENT_LINE_RE = re.compile(
    r"Kategoria:\s*(?P<category>.+?)\s*Typ:\s*(?P<play_type>Gra pojedyncza|Gra podw[óo]jna)\s*;"
    r"\s*(?P<gender>Ch[łl]opcy|Dziewcz[eę]ta)\s*;\s*(?P<draw>.*)",
    re.IGNORECASE,
)

_PAREN_RE = re.compile(r"\(([^)]+)\)")

# draw_format sometimes runs into trailing remarks PZT renders in the same
# cell ("Uwagi: ...", a following "Turniej główny" phase, or a "Losowanie"
# note) with no separator the regex above can key on. Cut at the earliest
# of these markers (or a literal newline) instead.
_DRAW_FORMAT_CUT_MARKERS = ("Uwagi:", "Turniej główny", "Losowanie", "\n")

WOJEWODZTWA = {
    "dolnośląskie",
    "kujawsko-pomorskie",
    "lubelskie",
    "lubuskie",
    "łódzkie",
    "małopolskie",
    "mazowieckie",
    "opolskie",
    "podkarpackie",
    "podlaskie",
    "pomorskie",
    "śląskie",
    "świętokrzyskie",
    "warmińsko-mazurskie",
    "wielkopolskie",
    "zachodniopomorskie",
}

LABEL_TERMIN_ZGLOSZEN = "Termin zgłoszeń"
LABEL_TERMIN_ODWOLAN = "Termin odwołań"
LABEL_MIEJSCE_ROZGRYWEK = "Miejsce rozgrywek"
LABEL_MIEJSCE_TURNIEJU = "Miejsce turnieju"
LABEL_ROZGRYWKI = "Rozgrywki"

# Leading Polish postcode ("99-210 Uniejów...") stripped before extracting
# the town from a "Miejsce turnieju" row.
_POSTCODE_RE = re.compile(r"^\d{2}-\d{3}\s*")

# Labels PZT sometimes renders inside the same "Miejsce turnieju" value cell,
# after the address (a trailing "Uwagi:" note, contact details, or a
# neighbouring field's label bleeding in). These never form part of a town
# name, so extract_city truncates at the earliest one it finds — defense in
# depth alongside bounding the value to its own row (step 5.2, "venue_city
# bleed"). Matched case-insensitively, with or without a trailing colon.
_CITY_TRUNCATE_LABELS = (
    "Uwagi",
    "email",
    r"tel\.",
    "Miejsce rozgrywek",
    r"Termin zgłoszeń",
    "Organizator",
    "Dyrektor turnieju",
    r"Turniej gł\.",
)
_CITY_TRUNCATE_RE = re.compile(
    "(?:" + "|".join(_CITY_TRUNCATE_LABELS) + r")\s*:?",
    re.IGNORECASE,
)

_TOURNAMENT_SELECTOR = "div.tournAppContainer_B"


def _parse_pzt_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%Y.%m.%d").date()
    except ValueError:
        logger.warning("Could not parse PZT date %r", raw)
        return None


def _find_tournament_nodes(root: Node) -> list[Node]:
    return root.css(_TOURNAMENT_SELECTOR)


def _find_by_class_prefix(node: Node, tag: str, prefix: str) -> Node | None:
    """Finds the first descendant <tag> with a class token starting with `prefix`.

    PZT renders a "_light" variant of the header classes for tournaments in
    certain statuses (e.g. tournAppStatusINPROGRESS) — tournAppTopCent_B
    becomes tournAppTopCent_B_light, tournAppTopMain1_B becomes
    tournAppTopMain1_B_light, and so on. An exact class selector
    (`div.tournAppTopCent_B`) misses the _light block entirely, so header
    elements must be matched by prefix instead of exact token.
    """
    for candidate in node.css(tag):
        classes = (candidate.attributes.get("class") or "").split()
        if any(cls.startswith(prefix) for cls in classes):
            return candidate
    return None


def _extract_guid(node: Node) -> str | None:
    for anchor in node.css("a"):
        href = anchor.attributes.get("href") or ""
        match = _GUID_RE.search(href)
        if match:
            return match.group(0)
    match = _GUID_RE.search(node.html or "")
    return match.group(0) if match else None


def _row_label(row: Node) -> str | None:
    label_node = row.css_first(".tournAppContentColL_B") or row.css_first(".tournAppContentColLBn_B")
    if label_node is None:
        return None
    return label_node.text(strip=True)


def _row_value_node(row: Node) -> Node | None:
    return row.css_first(".tournAppContentColR_B") or row.css_first(".tournAppContentColR_B_p0")


def _find_row(rows: list[Node], label: str) -> Node | None:
    for row in rows:
        if _row_label(row) == label:
            return row
    return None


def _parse_datetime_row(row: Node | None) -> datetime | None:
    """Parses a Termin zgłoszeń / Termin odwołań row into a datetime.

    Handles both markup shapes PZT uses for these rows: plain text in
    .tournAppContentColR_B ("2026-07-31 23:59"), or a
    .tournAppContentColR_B_p0 table whose first
    td.tournAppContentTdEntryFee holds
    "2026-08-03 (poniedziałek)<br>godz. 23:59".
    """
    if row is None:
        return None
    value_node = _row_value_node(row)
    if value_node is None:
        return None
    table = value_node.css_first("table")
    if table is not None:
        cell = table.css_first("td.tournAppContentTdEntryFee")
        text = cell.text(separator=" ", strip=True) if cell else value_node.text(separator=" ", strip=True)
    else:
        text = value_node.text(separator=" ", strip=True)
    match = _DATETIME_RE.search(text)
    if not match:
        logger.warning("Could not parse date/time from row text: %r", text)
        return None
    return datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour")),
        int(match.group("minute")),
    )


def _parse_wojewodztwo(row: Node | None) -> str | None:
    """Extracts the województwo from the "Miejsce rozgrywek" row.

    That row lists one or more court locations, each ending in
    "(<województwo>)"; absent entirely on some tournaments. Validated
    against the 16 real województwa so unrelated parenthesised text never
    slips through.
    """
    if row is None:
        return None
    value_node = _row_value_node(row)
    if value_node is None:
        return None
    text = value_node.text(separator=" ", strip=True)
    for match in _PAREN_RE.finditer(text):
        candidate = match.group(1).strip().lower()
        if candidate in WOJEWODZTWA:
            return candidate
    return None


def _parse_venue_address(row: Node | None) -> str | None:
    """Extracts the raw "Miejsce turnieju" text — the actual address PZT
    prints (town, street), unlike the unreliable "Miejsce rozgrywek" row
    (see _parse_wojewodztwo). Absent entirely on some tournaments.

    "Miejsce turnieju" renders twice per tournament (summary block and
    Informacje tab); `rows` is in document order, and `_find_row` already
    returns the first match, which is what we want here.

    deep=False bounds this to the value cell's own text, excluding any
    nested element PZT renders inside the same cell (e.g. an "Uwagi:"
    note) — without it, .text() recurses into such descendants and the
    address bleeds into whatever follows (step 5.2, "venue_city bleed").
    """
    if row is None:
        return None
    value_node = _row_value_node(row)
    if value_node is None:
        return None
    text = value_node.text(deep=False, separator=" ", strip=True)
    return text or None


def _title_case_word(word: str) -> str:
    return "-".join(part.capitalize() for part in word.split("-"))


def extract_city(raw: str) -> str | None:
    """Extracts a town name from a "Miejsce turnieju" row's raw text.

    Order of operations (CLAUDE.md, "Tournament selection"):
    truncate at the earliest trailing PZT label (defense in depth against
    venue_city bleed — see _CITY_TRUNCATE_RE — even though bounding the
    value to its own row in _parse_venue_address is the real fix), strip a
    leading postcode, take everything before the first comma (or the whole
    string if there's none), strip emoji/symbols, collapse whitespace, then
    Title Case each word. Deliberately does not validate against a list of
    Polish towns — there is no reliable list, and a wrong one would
    silently drop real tournaments.
    """
    text = raw.strip()
    truncate_match = _CITY_TRUNCATE_RE.search(text)
    if truncate_match:
        text = text[: truncate_match.start()]
    text = _POSTCODE_RE.sub("", text.strip())
    text = text.split(",", 1)[0]
    text = "".join(ch for ch in text if ch.isalpha() or ch.isspace() or ch == "-")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return " ".join(_title_case_word(word) for word in text.split(" "))


def _truncate_draw_format(raw: str) -> str:
    cut_at = len(raw)
    for marker in _DRAW_FORMAT_CUT_MARKERS:
        idx = raw.find(marker)
        if idx != -1:
            cut_at = min(cut_at, idx)
    return raw[:cut_at].strip()


def _parse_events(row: Node | None) -> list[Event]:
    if row is None:
        return []
    value_node = _row_value_node(row)
    if value_node is None:
        return []
    events: list[Event] = []
    for tr in value_node.css("tr"):
        text = re.sub(r"\s+", " ", tr.text(separator=" ", strip=True)).strip()
        match = _EVENT_LINE_RE.search(text)
        if not match:
            logger.warning("Could not parse event row: %r", text)
            continue
        play_type = PlayType.DOUBLES if "podw" in match.group("play_type").lower() else PlayType.SINGLES
        gender = Gender.BOYS if "opcy" in match.group("gender").lower() else Gender.GIRLS
        events.append(
            Event(
                category_label=match.group("category").strip(),
                play_type=play_type,
                gender=gender,
                draw_format=_truncate_draw_format(match.group("draw").strip()),
                raw_text=text,
            )
        )
    return events


def _parse_tournament_block(node: Node, age_category: AgeCategory, source_url: str) -> Tournament | None:
    name_node = node.css_first("div.tournAppName_B")
    name = name_node.text(strip=True) if name_node else ""

    prefix_match = _TYPE_PREFIX_RE.search(name)
    if not prefix_match:
        logger.warning("Tournament block has no recognizable type prefix, skipping: %.80s", name)
        return None
    type_prefix = prefix_match.group(1)

    ranga = None
    ranga_count_node = node.css_first("div.tournAppRangCount")
    if ranga_count_node is not None:
        ranga_text = ranga_count_node.text(strip=True)
        try:
            ranga = int(ranga_text)
        except ValueError:
            logger.warning("Could not parse ranga %r for tournament %r", ranga_text, name)

    date_from = date_to = None
    date_node = _find_by_class_prefix(node, "div", "tournAppTopCent_B")
    if date_node is not None:
        date_match = _DATE_RANGE_RE.search(date_node.text(separator=" ", strip=True))
        if date_match:
            date_from = _parse_pzt_date(date_match.group(1))
            date_to = _parse_pzt_date(date_match.group(2))

    if date_from is None:
        fallback_node = node.css_first("div.tournAppTopRightConDate")
        fallback_match = (
            _FALLBACK_DATE_FROM_RE.search(fallback_node.text(separator=" ", strip=True))
            if fallback_node is not None
            else None
        )
        if fallback_match:
            logger.warning(
                "tournAppTopCent_B Od:/Do: block missing or unparsable for tournament %r; "
                "falling back to tournAppTopRightConDate for date_from",
                name,
            )
            date_from = date(
                int(fallback_match.group(1)), int(fallback_match.group(2)), int(fallback_match.group(3))
            )

    if date_from is None:
        logger.warning("Tournament %r parsed with no date_from (primary and fallback both failed)", name)

    rows = node.css("div.tournAppContentRow2_B")
    entry_deadline = _parse_datetime_row(_find_row(rows, LABEL_TERMIN_ZGLOSZEN))
    withdrawal_deadline = _parse_datetime_row(_find_row(rows, LABEL_TERMIN_ODWOLAN))
    wojewodztwo = _parse_wojewodztwo(_find_row(rows, LABEL_MIEJSCE_ROZGRYWEK))
    venue_address = _parse_venue_address(_find_row(rows, LABEL_MIEJSCE_TURNIEJU))
    venue_city = extract_city(venue_address) if venue_address else None
    events = _parse_events(_find_row(rows, LABEL_ROZGRYWKI))

    if not events:
        logger.warning("Tournament %r has a Rozgrywki row PZT rendered but no events matched", name)

    guid = _extract_guid(node)
    if guid is None:
        logger.warning("Tournament %r has no extractable GUID from its results link", name)

    return Tournament(
        guid=guid,
        name=name,
        type_prefix=type_prefix,
        age_category=age_category,
        ranga=ranga,
        date_from=date_from,
        date_to=date_to,
        wojewodztwo=wojewodztwo,
        entry_deadline=entry_deadline,
        withdrawal_deadline=withdrawal_deadline,
        events=events,
        source_url=source_url,
        venue_address=venue_address,
        venue_city=venue_city,
    )


def find_tournament_html_at(html: str, index: int = 0) -> str | None:
    """Returns the raw HTML of the tournament block at `index` on a category page.

    Used by `--dump-html --index N` to inspect the exact markup PZT is
    currently rendering for a specific tournament (0-based, in page
    order), e.g. when selectors stop matching and the parser needs to be
    updated.
    """
    tree = HTMLParser(html)
    if not tree.root:
        return None
    nodes = _find_tournament_nodes(tree.root)
    if not 0 <= index < len(nodes):
        return None
    return nodes[index].html


def parse_category_page(html: str, age_category: AgeCategory, source_url: str) -> list[Tournament]:
    """Parses one Tournament.aspx?CategoryID=... page into Tournament objects."""
    tree = HTMLParser(html)
    nodes = _find_tournament_nodes(tree.root) if tree.root else []
    if not nodes:
        logger.error(
            "No tournament blocks found for %s (%s) — page shape may have changed",
            age_category.label,
            source_url,
        )
        return []

    tournaments: list[Tournament] = []
    for node in nodes:
        tournament = _parse_tournament_block(node, age_category, source_url)
        if tournament is not None:
            tournaments.append(tournament)
    return tournaments
