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

# Map journal name -> image directory slug.
# Must match the folder names under data/images/.
JOURNAL_IMAGE_SLUG: Dict[str, str] = {
    "Science": "science",
    "Nature": "nature",
    "Cell": "cell",
    "Political Geography": "Political_Geography",
    "International Organization": "International_Organization",
    "American Sociological Review": "ASR",
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

        # Validate: date is required for a meaningful article ID.
        if not raw.date or not raw.date.strip():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.warning(
                "Scraper for %s returned empty date — falling back to today (%s)",
                journal, today,
            )
            raw.date = today

        # Step 2 — Deduplicate.
        article_id = generate_article_id(raw.journal, raw.date)
        # Store articles under data/articles/<year>/<month>/<id>.json
        # matching the directory structure the frontend expects.
        try:
            dt = datetime.strptime(raw.date, "%Y-%m-%d")
            entry_file = (
                DATA_DIR / "articles" / f"{dt.year:04d}" / f"{dt.month:02d}"
                / f"{article_id}.json"
            )
        except (ValueError, TypeError):
            entry_file = DATA_DIR / "articles" / f"{article_id}.json"

        if entry_file.exists():
            logger.info("Already have %s — skipping", article_id)
            report["skipped"].append(article_id)
            return

        # Step 3 — Download cover image to data/images/<journal_slug>/.
        image_path: Optional[Path] = None
        if raw.cover_image_url:
            journal_slug = JOURNAL_IMAGE_SLUG.get(
                raw.journal, raw.journal.lower().replace(" ", "_")
            )
            journal_img_dir = IMAGES_DIR / journal_slug
            ensure_dir(journal_img_dir)
            ext = self._guess_image_ext(raw.cover_image_url)
            image_path = journal_img_dir / f"{article_id}-cover{ext}"
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
        """Build the final JSON entry in the frontend-compatible format.

        The output matches the ``ArticleDetail`` TypeScript interface used by
        the React front-end:
        ``{ id, journal, volume, issue, date, coverImage, coverStory }``.
        """
        # Resolve the local image path relative to the data directory.
        # The frontend loads images via getDataUrl("data/images/…").
        if image_path:
            try:
                local_img = "data/" + str(image_path.relative_to(DATA_DIR))
            except ValueError:
                local_img = str(image_path)
        else:
            local_img = ""

        # Extract bilingual title/summary from AI output.
        ai = ai_output or {}
        title_zh = ai.get("title", {}).get("zh", raw.article_title or "")
        title_en = ai.get("title", {}).get("en", raw.article_title or "")
        summary_zh = ai.get("summary", {}).get("zh", "")
        summary_en = ai.get("summary", {}).get("en", "")

        # Build the cover image entry in the gallery.
        images: List[Dict[str, Any]] = []
        if local_img:
            images.append({
                "url": local_img,
                "caption": {
                    "zh": raw.cover_description or "",
                    "en": raw.cover_description or "",
                },
            })

        # Construct DOI URL.
        doi = raw.article_doi or ""
        doi_url = f"https://doi.org/{doi}" if doi else ""

        entry: Dict[str, Any] = {
            "id": article_id,
            "journal": raw.journal,
            "volume": raw.volume or "",
            "issue": raw.issue or "",
            "date": raw.date,
            "coverImage": {
                "url": local_img,
                "credit": raw.cover_image_credit or "",
            },
            "coverStory": {
                "title": {"zh": title_zh, "en": title_en},
                "summary": {"zh": summary_zh, "en": summary_en},
                "keyArticle": {
                    "title": raw.article_title or "",
                    "authors": raw.article_authors or [],
                    "doi": doi,
                    "pages": raw.article_pages or "",
                },
                "images": images,
                "links": {
                    "official": raw.article_url or "",
                    "doi": doi_url,
                    **({"preprint": raw.preprint_url} if raw.preprint_url else {}),
                },
            },
            "_meta": {
                "summary_mode": summary_mode,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        return entry

    # ------------------------------------------------------------------
    # Index / latest manifests
    # ------------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """Rebuild ``data/index.json`` from all individual entry files.

        The index follows the ``ArticleIndex`` TypeScript interface:
        ``{ lastUpdated, articles: [{ id, journal, date, path, title_zh, title_en, cover_url }] }``
        """
        articles = []
        for f in sorted(DATA_DIR.glob("articles/**/*.json"), recursive=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                article_id = data.get("id", f.stem)
                date_str = data.get("date", "")
                # Compute the relative path from data/ to this file.
                rel_path = str(f.relative_to(DATA_DIR))
                # Extract bilingual titles.
                title = data.get("coverStory", {}).get("title", {})
                title_zh = title.get("zh", "")
                title_en = title.get("en", "")
                cover_url = data.get("coverImage", {}).get("url", "")

                articles.append({
                    "id": article_id,
                    "journal": data.get("journal", ""),
                    "date": date_str,
                    "path": rel_path,
                    "title_zh": title_zh,
                    "title_en": title_en,
                    "cover_url": cover_url,
                })
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed entry %s: %s", f, exc)

        # Also scan flat data/*.json files (legacy format).
        for f in sorted(DATA_DIR.glob("*.json")):
            if f.name in ("index.json", "latest.json"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                article_id = data.get("id", f.stem)
                # Skip if already found in articles/ directory.
                if any(a["id"] == article_id for a in articles):
                    continue
                date_str = data.get("date", "")
                title = data.get("coverStory", {}).get("title", {})
                title_zh = title.get("zh", "")
                title_en = title.get("en", "")
                cover_url = data.get("coverImage", {}).get("url", "")
                articles.append({
                    "id": article_id,
                    "journal": data.get("journal", ""),
                    "date": date_str,
                    "path": f.name,
                    "title_zh": title_zh,
                    "title_en": title_en,
                    "cover_url": cover_url,
                })
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Skipping malformed entry %s: %s", f, exc)

        # Sort newest first.
        articles.sort(key=lambda e: e.get("date", ""), reverse=True)

        index = {
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "articles": articles,
        }
        self._write_json(INDEX_FILE, index)
        logger.info("Rebuilt %s with %d entries", INDEX_FILE, len(articles))

    def _rebuild_latest(self) -> None:
        """Rebuild ``data/latest.json`` containing the path to the most
        recent entry per journal.  This powers the front-end "hero" display.
        """
        latest: Dict[str, str] = {}  # journal -> article path
        # Scan articles/ directory.
        all_files = sorted(DATA_DIR.glob("articles/**/*.json"), reverse=True)
        for f in all_files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                journal = data.get("journal", "")
                if journal and journal not in latest:
                    latest[journal] = str(f.relative_to(DATA_DIR))
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
