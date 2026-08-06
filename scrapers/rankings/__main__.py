"""Standalone runner: scrapes the eight junior ranking lists (Sort=LP and
Sort=A each) and prints the result as JSON on stdout. No database
involved.

The published (year, month) is always discovered from the ranking index
first (CLAUDE.md: never hardcode or guess it) — there is no override flag
for that on purpose.

Usage:
    python -m scrapers.rankings
    python -m scrapers.rankings --list M12 --list W12
    python -m scrapers.rankings --sort LP
    python -m scrapers.rankings --pretty
    python -m scrapers.rankings --dump-index-html
    python -m scrapers.rankings --dump-html --list M18 --sort A --index 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from core.http import build_client

from .models import RankingList, Sort
from .parser import find_entry_html_at
from .scraper import discover_current_period, fetch_index_html, fetch_ranking_list_html, scrape_all_entries


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
        "--sort",
        dest="sorts",
        action="append",
        choices=[s.value for s in Sort],
        help="Sort order to scrape (repeatable): LP (ranked) and/or A (alphabetical). Defaults to both.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    parser.add_argument(
        "--dump-html",
        action="store_true",
        help=(
            "Print the raw HTML of a ranking row on a single list page (from the "
            "first requested/default --list and --sort) to stdout instead of JSON. "
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
    sorts = [Sort(s) for s in args.sorts] if args.sorts else None

    if args.dump_index_html:
        async with build_client() as client:
            html = await fetch_index_html(client)
        sys.stdout.write(html)
        sys.stdout.write("\n")
        return 0

    if args.dump_html:
        ranking_list = ranking_lists[0] if ranking_lists else next(iter(RankingList))
        sort = sorts[0] if sorts else Sort.RANKED
        async with build_client() as client:
            period = await discover_current_period(client)
            if period is None:
                logging.error("Could not discover the current ranking period — cannot dump a list page")
                return 1
            year, month = period
            html = await fetch_ranking_list_html(client, ranking_list, sort, year, month)
        row_html = find_entry_html_at(html, args.index)
        if row_html is None:
            logging.error(
                "No ranking row at index %d for %s Sort=%s %d/%d — page shape may have changed, "
                "or the list has fewer rows than that",
                args.index,
                ranking_list.code,
                sort.value,
                month,
                year,
            )
            return 1
        sys.stdout.write(row_html)
        sys.stdout.write("\n")
        return 0

    result = await scrape_all_entries(ranking_lists, sorts)
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

    logging.info("Scraped %d ranking entries for %d/%d", len(entries), month, year)
    return 0


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
