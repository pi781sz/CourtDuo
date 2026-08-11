"""Standalone runner: scrapes the four junior tournament categories and
writes tournaments + events to the database.

Usage:
    python -m scrapers.tournaments
    python -m scrapers.tournaments --category 12 --category 14
    python -m scrapers.tournaments --dump-html
    python -m scrapers.tournaments --category 18 --dump-html --index 5
    python -m scrapers.tournaments --dry-run --doubles-only --pretty
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from core.http import build_client
from db import crud
from db.crud import store_tournaments
from db.session import get_session_factory

from .models import AgeCategory
from .parser import find_tournament_html_at
from .scraper import fetch_category_html, scrape_all

SCRAPER_NAME = "tournaments"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--category",
        type=int,
        action="append",
        choices=[c.value for c in AgeCategory],
        help="CategoryID to scrape (repeatable). Defaults to all four.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scraped tournaments as JSON on stdout instead of writing to the database. No DATABASE_URL needed.",
    )
    parser.add_argument(
        "--doubles-only",
        action="store_true",
        help="With --dry-run, only include tournaments that have at least one Gra podwójna event.",
    )
    parser.add_argument("--pretty", action="store_true", help="With --dry-run, pretty-print the JSON output.")
    parser.add_argument(
        "--dump-html",
        action="store_true",
        help=(
            "Print the raw HTML of a tournament block on the page (from the "
            "first requested/default category) to stdout instead of JSON. "
            "For debugging when the page shape changes."
        ),
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="0-based position of the tournament block to dump with --dump-html (default: 0, the first).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging on stderr.")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    categories = [AgeCategory(c) for c in args.category] if args.category else None

    if args.dump_html:
        category = categories[0] if categories else next(iter(AgeCategory))
        async with build_client() as client:
            html = await fetch_category_html(client, category)
        block_html = find_tournament_html_at(html, args.index)
        if block_html is None:
            logging.error(
                "No tournament block at index %d for %s — page shape may have changed, "
                "or the category has fewer tournaments than that",
                args.index,
                category.label,
            )
            return 1
        sys.stdout.write(block_html)
        sys.stdout.write("\n")
        return 0

    if args.dry_run:
        # Debugging path (module docstring): writes nothing, not even a
        # scraper_runs row, and needs no DATABASE_URL.
        tournaments = await scrape_all(categories)
        payload_tournaments = tournaments
        if args.doubles_only:
            payload_tournaments = [t for t in payload_tournaments if t.has_doubles]
        payload = [t.to_dict() for t in payload_tournaments]
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        logging.info(
            "Scraped %d tournaments (%d with doubles events) [dry-run, not written to the database]",
            len(payload),
            sum(1 for t in payload_tournaments if t.has_doubles),
        )
        return 0

    # A real run: exactly one scraper_runs row is written below, success or
    # failure (CLAUDE.md "Operations" -- the staleness alarm's whole
    # premise is that a scraper that stops running must not be invisible).
    # scrape_all itself is inside the try too, since "the scrape raised" is
    # one of the documented ok=False cases.
    session_factory = get_session_factory()
    started_at = datetime.now(timezone.utc)
    items_seen: int | None = None
    items_written: int | None = None
    ok = False
    detail: str | None = None
    exit_code = 0
    try:
        tournaments = await scrape_all(categories)
        items_seen = len(tournaments)
        async with session_factory() as session:
            written, doubles_events = await store_tournaments(session, tournaments)
            await session.commit()
        items_written = written
        ok = items_seen > 0 and items_written > 0
        if ok:
            logging.info(
                "Scraped %d tournaments, wrote %d to the database (%d doubles events)",
                len(tournaments),
                written,
                doubles_events,
            )
        else:
            detail = "Zero tournaments scraped or written across all categories"
            logging.error(detail)
            exit_code = 1
    except Exception as exc:  # noqa: BLE001 -- must still record the run row below
        detail = f"{type(exc).__name__}: {exc}"[:500]
        logging.exception("Tournaments scraper failed")
        exit_code = 1
    finally:
        finished_at = datetime.now(timezone.utc)
        try:
            async with session_factory() as run_session:
                await crud.record_scraper_run(
                    run_session, SCRAPER_NAME, started_at, finished_at, ok, items_seen, items_written, detail
                )
                await run_session.commit()
        except Exception:
            # Per CLAUDE.md "Operations": if the database itself is
            # unreachable the row cannot be written -- that IS a staleness
            # condition, and bot.staleness catches it as "no successful
            # run" on its own. Nothing more to do here than log.
            logging.exception("Failed to record scraper_runs row for %s", SCRAPER_NAME)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
