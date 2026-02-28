#!/usr/bin/env python3
"""
main.py — CLI entry point for the SciCover pipeline.

Usage (run from the repository root)
-----
    # Scrape and summarise all journals (default)
    python -m scripts.main

    # Scrape only Nature, skip AI summarisation
    python -m scripts.main --journal Nature --dry-run

    # Scrape Science and Cell
    python -m scripts.main --journal Science --journal Cell

    # Show help
    python -m scripts.main --help
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List

from .pipeline.runner import PipelineRunner


def _configure_logging(verbose: bool = False) -> None:
    """Set up structured logging to stderr."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )
    # Silence overly chatty third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        prog="scicover",
        description=(
            "SciCover — scrape top journal covers and generate bilingual "
            "summaries for a general audience."
        ),
    )

    parser.add_argument(
        "--journal",
        action="append",
        dest="journals",
        metavar="NAME",
        help=(
            "Journal to process.  Accepted values: Science, Nature, Cell, "
            "'Political Geography' (or polgeog), 'International Organization' "
            "(or intorg), 'American Sociological Review' (or asr), "
            "or 'all' (default).  May be specified multiple times, e.g. "
            "--journal Science --journal Nature."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Scrape and download images but skip AI summarisation.  "
            "Useful for testing scrapers without consuming API credits."
        ),
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging for more detailed output.",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    """Parse arguments, run the pipeline, and return an exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(verbose=args.verbose)
    logger = logging.getLogger("scicover")

    # Normalise the --journal list.
    journals = args.journals  # None means "all"
    if journals and any(j.lower() == "all" for j in journals):
        journals = None  # explicit "all" -> same as omitting the flag

    logger.info("Starting SciCover pipeline")
    if args.dry_run:
        logger.info("DRY RUN mode — AI summarisation is disabled")

    runner = PipelineRunner(journals=journals, dry_run=args.dry_run)
    report = runner.run()

    # Pretty-print the report to stderr.
    logger.info("--- Pipeline Report ---")
    if report["processed"]:
        logger.info("Processed: %s", ", ".join(report["processed"]))
    if report["skipped"]:
        logger.info("Skipped (already exist): %s", ", ".join(report["skipped"]))
    if report["errors"]:
        logger.warning("Errors:")
        for err in report["errors"]:
            logger.warning("  %s: %s", err["journal"], err["error"])

    # Exit code: 0 if at least something was processed or skipped, 1 otherwise.
    if report["processed"] or report["skipped"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
