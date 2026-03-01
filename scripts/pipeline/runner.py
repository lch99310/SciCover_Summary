"""
pipeline.runner — End-to-end orchestrator for the SciCover pipeline.

Responsibilities
----------------
1. Iterate over the requested journal scrapers.
2. For each journal:
   a. Scrape the current issue (or a specific back-issue).
   b. Check whether we have already processed this issue (deduplicate).
   c. Download the cover image to the local ``data/images/`` directory.
   d. Attempt to fetch the full article text from preprints or open-access.
   e. Call the AI summariser (full-text or abstract-only mode).
   f. Write the resulting entry to ``data/<article_id>.json``.
3. Rebuild the global ``data/index.json`` and ``data/latest.json`` manifests.

Error handling: a failure in one journal MUST NOT prevent the others from
being processed.  Errors are logged and collected; the pipeline returns
a summary report at the end.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from ..scraper import (
    ALL_SCRAPERS,
    ScienceScraper, NatureScraper, CellScraper,
    PolGeogScraper, IntOrgScraper, ASRScraper,
)
from ..scraper.base import BaseScraper, CoverArticleRaw
from ..ai.summarizer import BilingualSummarizer
from ..ai.fulltext import fetch_fulltext
from ..utils.helpers import generate_article_id, download_image, ensure_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Root data directory — lives next to the ``scripts/`` package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # …/scicover
DATA_DIR = _PROJECT_ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
INDEX_FILE = DATA_DIR / "index.json"
LATEST_FILE = DATA_DIR / "latest.json"

# Map of journal name -> scraper class for --journal filtering.
SCRAPER_MAP: Dict[str, Type[BaseScraper]] = {
    "science": ScienceScraper,
    "nature": NatureScraper,
    "cell": CellScraper,
    "political geography": PolGeogScraper,
    "polgeog": PolGeogScraper,
    "international organization": IntOrgScraper,
    "intorg": IntOrgScraper,
    "american sociological review": ASRScraper,
    "asr": ASRScraper,
}


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """Orchestrates the full scrape -> summarise -> persist pipeline."""

    def __init__(
        self,
        journals: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> None:
        """
        Parameters
        ----------
        journals:
            List of journal names to process (case-insensitive).
            ``None`` or ``["all"]`` means all available scrapers.
        dry_run:
            If ``True``, scrape and download images but skip AI
            summarisation.  Useful for testing scrapers in isolation.
        """
        self.dry_run = dry_run
        self.scrapers = self._resolve_scrapers(journals)
        self.summarizer = None if dry_run else BilingualSummarizer()

        # Ensure base directories exist.
        ensure_dir(DATA_DIR)
        ensure_dir(IMAGES_DIR)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the pipeline and return a summary report.

        Returns
        -------
        dict
            ``{"processed": [...], "skipped": [...], "errors": [...]}``.
        """
        report: Dict[str, list] = {
            "processed": [],
            "skipped": [],
            "errors": [],
        }

        for scraper_cls in self.scrapers:
            scraper = scraper_cls()
            journal = scraper.JOURNAL_NAME

            try:
                self._process_journal(scraper, report)
            except Exception as exc:
                logger.exception("Unhandled error processing %s", journal)
                report["errors"].append(
                    {"journal": journal, "error": str(exc)}
                )

        # Rebuild global manifests.
        self._rebuild_index()
        self._rebuild_latest()

        # Log final summary.
        logger.info(
            "Pipeline complete: %d processed, %d skipped, %d errors",
            len(report["processed"]),
            len(report["skipped"]),
            len(report["errors"]),
        )
        return report

    # ------------------------------------------------------------------
    # Internal: per-journal processing
    # ------------------------------------------------------------------

    def _process_journal(
        self,
        scraper: BaseScraper,
        report: Dict[str, list],
    ) -> None:
        """Scrape, summarise, and persist one journal."""
        journal = scraper.JOURNAL_NAME

        # Step 1 — Scrape.
        raw = scraper.scrape_current_issue()
        if raw is None:
            logger.warning("Scraping returned nothing for %s", journal)
            report["errors"].append(
                {"journal": journal, "error": "scraper returned None"}
            )
            return

        # Step 2 — Deduplicate.
        article_id = generate_article_id(raw.journal, raw.date)
        entry_file = DATA_DIR / f"{article_id}.json"

        if entry_file.exists():
            logger.info("Already have %s — skipping", article_id)
            report["skipped"].append(article_id)
            return

        # Step 3 — Download cover image.
        image_path: Optional[Path] = None
        if raw.cover_image_url:
            ext = self._guess_image_ext(raw.cover_image_url)
            image_path = IMAGES_DIR / f"{article_id}{ext}"
            result = download_image(raw.cover_image_url, image_path)
            if result is None:
                logger.warning("Image download failed for %s", article_id)
                image_path = None

        # Step 4 — Attempt full-text retrieval (preprint or open-access).
        fulltext: Optional[str] = None
        if not self.dry_run:
            try:
                fulltext = fetch_fulltext(
                    preprint_url=raw.preprint_url,
                    article_url=raw.article_url,
                    doi=raw.article_doi,
                )
                if fulltext:
                    logger.info(
                        "Full text available for %s (%d chars) — using structured summary",
                        article_id,
                        len(fulltext),
                    )
                else:
                    logger.info(
                        "No full text available for %s — using abstract-only summary",
                        article_id,
                    )
            except Exception as exc:
                logger.warning("Full-text fetch failed for %s: %s", article_id, exc)

        # Step 5 — AI summarisation (skipped in dry-run mode).
        ai_output: Optional[Dict[str, Any]] = None
        if not self.dry_run and self.summarizer is not None:
            ai_output = self.summarizer.summarize(raw, fulltext=fulltext)
            if ai_output is None:
                logger.warning("AI summarisation failed for %s", article_id)

        # Step 6 — Assemble and write the entry JSON.
        entry = self._build_entry(
            raw, article_id, image_path, ai_output,
            summary_mode="full-text" if fulltext else "abstract-only",
        )
        self._write_json(entry_file, entry)

        report["processed"].append(article_id)
        logger.info("Wrote %s", entry_file)

    # ------------------------------------------------------------------
    # Entry assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_entry(
        raw: CoverArticleRaw,
        article_id: str,
        image_path: Optional[Path],
        ai_output: Optional[Dict[str, Any]],
        summary_mode: str = "abstract-only",
    ) -> Dict[str, Any]:
        """Build the final JSON entry from scraped + AI data."""
        entry: Dict[str, Any] = {
            "id": article_id,
            "journal": raw.journal,
            "volume": raw.volume,
            "issue": raw.issue,
            "date": raw.date,
            "cover_image": {
                "url": raw.cover_image_url,
                "local_path": str(image_path.relative_to(image_path.parents[1]))
                if image_path
                else "",
                "credit": raw.cover_image_credit,
            },
            "cover_description": raw.cover_description,
            "article": {
                "title": raw.article_title,
                "authors": raw.article_authors,
                "abstract": raw.article_abstract,
                "doi": raw.article_doi,
                "url": raw.article_url,
                "pages": raw.article_pages,
            },
            "preprint_url": raw.preprint_url,
            "ai_summary": ai_output,  # None if dry-run or failed
            "summary_mode": summary_mode,  # "full-text" or "abstract-only"
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return entry

    # ------------------------------------------------------------------
    # Index / latest manifests
    # ------------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """Rebuild ``data/index.json`` from all individual entry files.

        The index is a sorted list of lightweight references (id, journal,
        date, title) so the front-end can render a catalogue without
        loading every full entry.
        """
        entries = []
        for f in sorted(DATA_DIR.glob("*.json")):
            if f.name in ("index.json", "latest.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entries.append(
                    {
                        "id": data.get("id", f.stem),
                        "journal": data.get("journal", ""),
                        "date": data.get("date", ""),
                        "title": (
                            data.get("ai_summary", {}) or {}
                        ).get("title", {}).get("en", data.get("article", {}).get("title", "")),
                        "cover_image_local": data.get("cover_image", {}).get("local_path", ""),
                    }
                )
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed entry %s: %s", f, exc)

        # Sort newest first.
        entries.sort(key=lambda e: e.get("date", ""), reverse=True)

        self._write_json(INDEX_FILE, {"entries": entries, "count": len(entries)})
        logger.info("Rebuilt %s with %d entries", INDEX_FILE, len(entries))

    def _rebuild_latest(self) -> None:
        """Rebuild ``data/latest.json`` containing the most recent entry
        per journal.  This powers the front-end "hero" display.
        """
        latest: Dict[str, Any] = {}
        for f in sorted(DATA_DIR.glob("*.json"), reverse=True):
            if f.name in ("index.json", "latest.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                journal = data.get("journal", "")
                if journal and journal not in latest:
                    latest[journal] = data
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed entry %s: %s", f, exc)

        self._write_json(LATEST_FILE, latest)
        logger.info("Rebuilt %s with journals: %s", LATEST_FILE, list(latest.keys()))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_scrapers(
        journals: Optional[List[str]],
    ) -> List[Type[BaseScraper]]:
        """Map user-supplied journal names to scraper classes."""
        if not journals or journals == ["all"]:
            return list(ALL_SCRAPERS)

        result = []
        for name in journals:
            cls = SCRAPER_MAP.get(name.lower())
            if cls is None:
                logger.warning(
                    "Unknown journal '%s'. Available: %s",
                    name,
                    ", ".join(SCRAPER_MAP.keys()),
                )
            else:
                result.append(cls)
        return result

    @staticmethod
    def _guess_image_ext(url: str) -> str:
        """Guess a file extension from an image URL."""
        lower = url.lower().split("?")[0]
        if lower.endswith(".png"):
            return ".png"
        if lower.endswith(".gif"):
            return ".gif"
        if lower.endswith(".webp"):
            return ".webp"
        return ".jpg"  # default for JPEG and unknown

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        """Atomically write *data* as pretty-printed JSON to *path*."""
        ensure_dir(path.parent)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            # Clean up on failure.
            tmp.unlink(missing_ok=True)
            raise
