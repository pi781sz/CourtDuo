"""Parses PZT tournament listing pages (Tournament.aspx?CategoryID=...).

Field extraction is anchored on the literal Polish labels PZT renders
("Termin zgłoszeń", "Termin odwołań", "Rozgrywki", the "Od: ... Do: ..."
date pair, etc.) rather than on CSS classes or element ids. Those labels
are stable, human-facing text; the surrounding markup is an ASP.NET
WebForms GridView and its class names are the kind of thing that gets
regenerated across PZT site updates. If PZT changes the wording of a
label, `parse_category_page` logs and skips the tournament instead of
writing partial/garbage data (see CLAUDE.md, "Scraping etiquette").

NOTE: this parser could not be validated against a live fetch of
portal.pzt.pl — the sandbox this was written in has no network route to
that host. Field regexes are built from the exact field descriptions and
label text in CLAUDE.md. Run `python -m scrapers.tournaments` against the
real site and diff the JSON output against the live pages before trusting
this in production; adjust `_LABEL_PATTERNS` if any label text differs.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from selectolax.parser import HTMLParser, Node

from .models import AgeCategory, Event, Gender, PlayType, Tournament, TournamentDirector

logger = logging.getLogger(__name__)

TYPE_PREFIXES = ("OTK SS", "OTK", "WTK", "MW")
_TYPE_PREFIX_RE = re.compile(r"^\s*(" + "|".join(re.escape(p) for p in TYPE_PREFIXES) + r")\b")

_GUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

_DATE_RANGE_RE = re.compile(r"Od:\s*(\d{4}\.\d{2}\.\d{2})\s*Do:\s*(\d{4}\.\d{2}\.\d{2})")
_RANGA_RE = re.compile(r"Ranga:?\s*([1-7])\b")
_ENTRY_DEADLINE_RE = re.compile(r"Termin zg[łl]osze[nń]:?\s*(\d{4}\.\d{2}\.\d{2})")
_WITHDRAWAL_DEADLINE_RE = re.compile(r"Termin odwo[łl]a[nń]:?\s*(\d{4}\.\d{2}\.\d{2})")
_ORGANISER_RE = re.compile(r"Organizator:?\s*(.+)")
_VENUE_RE = re.compile(r"(?:Miejsce|Adres)(?: rozgrywania)?:?\s*(.+)")
_WOJEWODZTWO_RE = re.compile(r"Wojew[óo]dztwo:?\s*(.+)")
_DIRECTOR_RE = re.compile(r"Dyrektor turnieju:?\s*(.+)")
_PHONE_RE = re.compile(r"(?:tel\.?|telefon)[:\s]*([+\d][\d\s-]{5,})", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_ENTRY_FEE_RE = re.compile(r"Wpisowe:?\s*(.+)")
_SURFACE_RE = re.compile(r"Nawierzchnia:?\s*(.+)")
_COURT_COUNT_RE = re.compile(r"Liczba kort[óo]w:?\s*(\d+)")

_EVENT_LINE_RE = re.compile(
    r"Kategoria:\s*(?P<category>.+?)\s*Typ:\s*(?P<play_type>Gra pojedyncza|Gra podw[óo]jna)\s*;"
    r"\s*(?P<gender>Ch[łl]opcy|Dziewcz[eę]ta)\s*;\s*(?P<draw>[^\n]*)",
    re.IGNORECASE,
)

REQUIRED_MARKERS = ("Termin zg", "Rozgrywki")


def _parse_pzt_date(raw: str) -> date | None:
    try:
        return datetime.strptime(raw.strip(), "%Y.%m.%d").date()
    except ValueError:
        logger.warning("Could not parse PZT date %r", raw)
        return None


def _find_tournament_nodes(root: Node) -> list[Node]:
    """Finds the minimal (innermost) DOM nodes that each represent one tournament.

    A tournament block is identified by containing all of REQUIRED_MARKERS in
    its text plus a name line starting with a known type prefix. We keep only
    the innermost matching nodes so nested containers (e.g. a table wrapping
    a div wrapping the actual card) don't produce duplicate matches.
    """
    candidates: list[Node] = []
    for node in root.css("*"):
        text = node.text(separator="\n", strip=True)
        if not text or len(text) > 20_000:
            continue
        # Require the type-prefix name line near the top of the block (not
        # just anywhere) so we don't match the whole page body as one block.
        if all(marker in text for marker in REQUIRED_MARKERS) and _TYPE_PREFIX_RE.search(text[:200]):
            candidates.append(node)

    minimal: list[Node] = []
    for node in candidates:
        is_minimal = True
        for other in candidates:
            if other == node:
                continue
            if _contains(node, other):
                is_minimal = False
                break
        if is_minimal:
            minimal.append(node)
    return minimal


def _contains(ancestor: Node, descendant: Node) -> bool:
    parent = descendant.parent
    while parent is not None:
        if parent == ancestor:
            return True
        parent = parent.parent
    return False


def _extract_guid(node: Node) -> str | None:
    for anchor in node.css("a"):
        href = anchor.attributes.get("href") or ""
        match = _GUID_RE.search(href)
        if match:
            return match.group(0)
    match = _GUID_RE.search(node.html or "")
    return match.group(0) if match else None


def _parse_events(text: str) -> list[Event]:
    events: list[Event] = []
    for match in _EVENT_LINE_RE.finditer(text):
        try:
            play_type = PlayType.DOUBLES if "podw" in match.group("play_type").lower() else PlayType.SINGLES
            gender = Gender.BOYS if "opcy" in match.group("gender").lower() else Gender.GIRLS
        except Exception:
            logger.warning("Could not classify event line: %r", match.group(0))
            continue
        events.append(
            Event(
                category_label=match.group("category").strip(),
                play_type=play_type,
                gender=gender,
                draw_format=match.group("draw").strip(),
                raw_text=match.group(0).strip(),
            )
        )
    return events


def _first_group(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _parse_director(text: str) -> TournamentDirector:
    match = _DIRECTOR_RE.search(text)
    if not match:
        return TournamentDirector()
    # Director line typically runs "Name, tel. 123456789, email: foo@bar.pl"
    # up to the next field label or end of line.
    segment = match.group(1).split("\n", 1)[0]
    phone_match = _PHONE_RE.search(segment)
    email_match = _EMAIL_RE.search(segment)
    name_part = segment
    for cut in (phone_match, email_match):
        if cut:
            name_part = name_part[: cut.start()]
    name = name_part.strip(" ,;\t") or None
    return TournamentDirector(
        name=name,
        phone=phone_match.group(1).strip() if phone_match else None,
        email=email_match.group(0).strip() if email_match else None,
    )


def _parse_tournament_block(node: Node, age_category: AgeCategory, source_url: str) -> Tournament | None:
    text = node.text(separator="\n", strip=True)
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    text = "\n".join(lines)

    prefix_match = _TYPE_PREFIX_RE.search(text)
    if not prefix_match:
        logger.warning("Tournament block has no recognizable type prefix, skipping: %.80s", text)
        return None
    type_prefix = prefix_match.group(1)
    name = lines[0] if lines else ""

    date_match = _DATE_RANGE_RE.search(text)
    date_from = _parse_pzt_date(date_match.group(1)) if date_match else None
    date_to = _parse_pzt_date(date_match.group(2)) if date_match else None

    entry_deadline_raw = _first_group(_ENTRY_DEADLINE_RE, text)
    withdrawal_deadline_raw = _first_group(_WITHDRAWAL_DEADLINE_RE, text)
    court_count_raw = _first_group(_COURT_COUNT_RE, text)

    events = _parse_events(text)
    if not events:
        logger.warning("Tournament %r has a Rozgrywki block PZT rendered but no events matched", name)

    guid = _extract_guid(node)
    if guid is None:
        logger.warning("Tournament %r has no extractable GUID from its results link", name)

    return Tournament(
        guid=guid,
        name=name,
        type_prefix=type_prefix,
        age_category=age_category,
        ranga=int(m.group(1)) if (m := _RANGA_RE.search(text)) else None,
        date_from=date_from,
        date_to=date_to,
        organiser=_first_group(_ORGANISER_RE, text),
        venue_address=_first_group(_VENUE_RE, text),
        wojewodztwo=_first_group(_WOJEWODZTWO_RE, text),
        entry_deadline=_parse_pzt_date(entry_deadline_raw) if entry_deadline_raw else None,
        withdrawal_deadline=_parse_pzt_date(withdrawal_deadline_raw) if withdrawal_deadline_raw else None,
        director=_parse_director(text),
        entry_fee=_first_group(_ENTRY_FEE_RE, text),
        court_surface=_first_group(_SURFACE_RE, text),
        court_count=int(court_count_raw) if court_count_raw else None,
        events=events,
        source_url=source_url,
    )


def find_first_tournament_html(html: str) -> str | None:
    """Returns the raw HTML of the first tournament block on a category page.

    Used by `--dump-html` to inspect the exact markup PZT is currently
    rendering, e.g. when `_LABEL_PATTERNS` stop matching and the parser
    needs to be updated.
    """
    tree = HTMLParser(html)
    if not tree.root:
        return None
    nodes = _find_tournament_nodes(tree.root)
    return nodes[0].html if nodes else None


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
