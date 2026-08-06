"""Standalone runner: scrapes the four junior tournament categories and
prints the result as JSON on stdout. No database involved.

Usage:
    python -m scrapers.tournaments
    python -m scrapers.tournaments --category 12 --category 14
    python -m scrapers.tournaments --doubles-only
    python -m scrapers.tournaments --pretty
    python -m scrapers.tournaments --dump-html
    python -m scrapers.tournaments --category 18 --dump-html --index 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from core.http import build_client

from .models import AgeCategory
from .parser import find_tournament_html_at
from .scraper import fetch_category_html, scrape_all


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--category",
        type=int,
        action="append",
        choices=[c.value for c in AgeCategory],
        help="CategoryID to scrape (repeatable). Defaults to all four.",
    )
    parser.add_argument(
        "--doubles-only",
        action="store_true",
        help="Only include tournaments that have at least one Gra podwójna event.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
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

    tournaments = await scrape_all(categories)

    if args.doubles_only:
        tournaments = [t for t in tournaments if t.has_doubles]

    payload = [t.to_dict() for t in tournaments]
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")

    logging.info(
        "Scraped %d tournaments (%d with doubles events)",
        len(payload),
        sum(1 for t in tournaments if t.has_doubles),
    )
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
