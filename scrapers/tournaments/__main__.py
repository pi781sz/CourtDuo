"""Standalone runner: scrapes the four junior tournament categories and
prints the result as JSON on stdout. No database involved.

Usage:
    python -m scrapers.tournaments
    python -m scrapers.tournaments --category 12 --category 14
    python -m scrapers.tournaments --doubles-only
    python -m scrapers.tournaments --pretty
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .models import AgeCategory
from .scraper import scrape_all


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
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging on stderr.")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    categories = [AgeCategory(c) for c in args.category] if args.category else None
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
