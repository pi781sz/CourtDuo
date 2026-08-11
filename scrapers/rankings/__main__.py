"""Standalone runner: scrapes the eight junior ranking lists (Sort=A) and
writes players + ranking rows to the database.

The published (year, month) is always discovered from the ranking index
first (CLAUDE.md: never hardcode or guess it) — there is no override flag
for that on purpose.

Usage:
    python -m scrapers.rankings
    python -m scrapers.rankings --list M12 --list W12
    python -m scrapers.rankings --dump-index-html
    python -m scrapers.rankings --dump-html --list M18 --index 5
    python -m scrapers.rankings --dry-run --pretty
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
from db.crud import store_ranking_entries
from db.session import get_session_factory

from .models import RankingList
from .parser import find_entry_html_at
from .scraper import discover_current_period, fetch_index_html, fetch_ranking_list_html, scrape_all_entries

SCRAPER_NAME = "rankings"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--list",
        dest="lists",
        action="append",
        choices=[rl.code for rl in RankingList],
        help="Ranking list code to scrape (repeatable). Defaults to all eight.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scraped ranking entries as JSON on stdout instead of writing to the database. No DATABASE_URL needed.",
    )
    parser.add_argument("--pretty", action="store_true", help="With --dry-run, pretty-print the JSON output.")
    parser.add_argument(
        "--dump-html",
        action="store_true",
        help=(
            "Print the raw HTML of a ranking row on a single list page (from the "
            "first requested/default --list) to stdout instead of JSON. "
            "For debugging when the page shape changes."
        ),
    )
    parser.add_argument(
        "--index",
        type=int,
        default=0,
        help="0-based position of the ranking row to dump with --dump-html (default: 0, the first).",
    )
    parser.add_argument(
        "--dump-index-html",
        action="store_true",
        help="Print the raw HTML of the ranking index page (RCatID=M) to stdout instead of JSON.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging on stderr.")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    ranking_lists = [RankingList(c) for c in args.lists] if args.lists else None

    if args.dump_index_html:
        async with build_client() as client:
            html = await fetch_index_html(client)
        sys.stdout.write(html)
        sys.stdout.write("\n")
        return 0

    if args.dump_html:
        ranking_list = ranking_lists[0] if ranking_lists else next(iter(RankingList))
        async with build_client() as client:
            period = await discover_current_period(client)
            if period is None:
                logging.error("Could not discover the current ranking period — cannot dump a list page")
                return 1
            year, month = period
            html = await fetch_ranking_list_html(client, ranking_list, year, month)
        row_html = find_entry_html_at(html, args.index)
        if row_html is None:
            logging.error(
                "No ranking row at index %d for %s %d/%d — page shape may have changed, "
                "or the list has fewer rows than that",
                args.index,
                ranking_list.code,
                month,
                year,
            )
            return 1
        sys.stdout.write(row_html)
        sys.stdout.write("\n")
        return 0

    if args.dry_run:
        # Debugging path (module docstring): writes nothing, not even a
        # scraper_runs row, and needs no DATABASE_URL.
        result = await scrape_all_entries(ranking_lists)
        if result is None:
            logging.error("Could not discover the current ranking period — nothing scraped")
            return 1
        year, month, entries = result
        payload = {
            "year": year,
            "month": month,
            "entries": [e.to_dict() for e in entries],
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        logging.info(
            "Scraped %d ranking entries total for %d/%d [dry-run, not written to the database]",
            len(entries),
            month,
            year,
        )
        return 0

    # A real run: exactly one scraper_runs row is written below, success or
    # failure (CLAUDE.md "Operations" -- the staleness alarm's whole
    # premise is that a scraper that stops running must not be invisible).
    # This includes the "could not discover the period" case, which used to
    # just log and return 1 with no record left behind.
    session_factory = get_session_factory()
    started_at = datetime.now(timezone.utc)
    items_seen: int | None = None
    items_written: int | None = None
    ok = False
    detail: str | None = None
    exit_code = 0
    try:
        result = await scrape_all_entries(ranking_lists)
        if result is None:
            detail = "Could not discover the current ranking period"
            logging.error(detail)
            exit_code = 1
        else:
            year, month, entries = result
            items_seen = len(entries)
            async with session_factory() as session:
                written = await store_ranking_entries(session, entries)
                await session.commit()
            items_written = written
            ok = items_seen > 0 and items_written > 0
            if ok:
                logging.info(
                    "Scraped %d ranking entries for %d/%d, wrote %d to the database",
                    len(entries),
                    month,
                    year,
                    written,
                )
            else:
                detail = "Zero ranking entries scraped or written across all lists"
                logging.error(detail)
                exit_code = 1
    except Exception as exc:  # noqa: BLE001 -- must still record the run row below
        detail = f"{type(exc).__name__}: {exc}"[:500]
        logging.exception("Rankings scraper failed")
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
