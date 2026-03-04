"""
pipeline.runner — End-to-end orchestrator for the SciCover pipeline.

Responsibilities
----------------
1. Iterate over the requested journals.
2. For each journal:
   a. Fetch the latest research article via the OpenAlex API.
   b. Check whether we have already processed this article (deduplicate).
   c. Download the cover image (if available) to ``data/images/``.
   d. Attempt to fetch the full article text via OpenAlex content API.
   e. Call the AI summariser (full-text or abstract-only mode).
   f. Write the resulting entry to ``data/articles/<year>/<month>/<id>.json``.
3. Rebuild the global ``data/index.json`` and ``data/latest.json`` manifests.

Error handling: a failure in one journal MUST NOT prevent the others from
being processed.  Errors are logged and collected; the pipeline returns
a summary report at the end.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..scraper.openalex_fetcher import (
    OpenAlexFetcher,
    JOURNAL_REGISTRY,
    JOURNAL_ALIASES,
)
from ..scraper.base import CoverArticleRaw
from ..ai.summarizer import BilingualSummarizer
from ..utils.helpers import generate_article_id, download_image, ensure_dir
from ..utils.pdf_thumbnail import extract_thumbnail_from_urls

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = _PROJECT_ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
INDEX_FILE = DATA_DIR / "index.json"
LATEST_FILE = DATA_DIR / "latest.json"

# Map journal display name -> image directory slug.
# Uses lowercase-hyphenated names for consistency with generate_article_id().
JOURNAL_IMAGE_SLUG: Dict[str, str] = {
    "Science": "science",
    "Nature": "nature",
    "Cell": "cell",
    "Political Geography": "political-geography",
    "International Organization": "international-organization",
    "American Sociological Review": "american-sociological-review",
}

# All journal keys from the registry.
ALL_JOURNAL_KEYS = list(JOURNAL_REGISTRY.keys())


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

class PipelineRunner:
    """Orchestrates the full fetch -> summarise -> persist pipeline."""

    def __init__(
        self,
        journals: Optional[List[str]] = None,
        dry_run: bool = False,
    ) -> None:
        self.dry_run = dry_run
        self.journal_keys = self._resolve_journals(journals)
        self.fetcher = OpenAlexFetcher()
        self.summarizer = None if dry_run else BilingualSummarizer()

        ensure_dir(DATA_DIR)
        ensure_dir(IMAGES_DIR)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the pipeline and return a summary report."""
        report: Dict[str, list] = {
            "processed": [],
            "skipped": [],
            "errors": [],
        }

        for key in self.journal_keys:
            info = JOURNAL_REGISTRY[key]
            journal_name = info["display_name"]

            try:
                self._process_journal(key, journal_name, report)
            except Exception as exc:
                logger.exception("Unhandled error processing %s", journal_name)
                report["errors"].append(
                    {"journal": journal_name, "error": str(exc)}
                )

        # Rebuild global manifests.
        self._rebuild_index()
        self._rebuild_latest()

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
        journal_key: str,
        journal_name: str,
        report: Dict[str, list],
    ) -> None:
        """Fetch, summarise, and persist one journal."""

        # Step 1 — Fetch latest article from OpenAlex.
        logger.info("Fetching latest article for %s via OpenAlex...", journal_name)
        raw = self.fetcher.fetch_latest(journal_key)
        if raw is None:
            logger.warning("OpenAlex returned nothing for %s", journal_name)
            report["errors"].append(
                {"journal": journal_name, "error": "OpenAlex returned no results"}
            )
            return

        logger.info(
            "%s: found '%s' (vol.%s #%s, %s)",
            journal_name,
            raw.article_title[:60],
            raw.volume,
            raw.issue,
            raw.date,
        )

        # Validate date.
        if not raw.date or not raw.date.strip():
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            logger.warning(
                "Article for %s has no date — falling back to today (%s)",
                journal_name, today,
            )
            raw.date = today

        # Step 2 — Deduplicate.
        article_id = generate_article_id(raw.journal, raw.date)
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

        # Step 3 — Extract thumbnail.
        # Strategy: PDF pages → article HTML (og:image, figures) → preprint HTML.
        image_path: Optional[Path] = None
        oa_pdf_url = getattr(raw, "_oa_pdf_url", "")
        all_pdf_urls: list = getattr(raw, "_all_pdf_urls", [])
        # Determine the best URL for HTML image extraction: prefer article_url,
        # fall back to preprint_url (bioRxiv/arXiv pages have og:image tags).
        html_url_for_image = raw.article_url or raw.preprint_url or ""
        if not self.dry_run and (oa_pdf_url or all_pdf_urls or html_url_for_image):
            img_slug = JOURNAL_IMAGE_SLUG.get(journal_name, journal_name.lower())
            img_dir = IMAGES_DIR / img_slug
            ensure_dir(img_dir)
            thumb_file = img_dir / f"{article_id}-cover.jpg"
            # Build ordered list: repository copies first, then publisher.
            pdf_urls_to_try = list(all_pdf_urls)
            if oa_pdf_url and oa_pdf_url not in pdf_urls_to_try:
                pdf_urls_to_try.append(oa_pdf_url)
            image_path = extract_thumbnail_from_urls(
                pdf_urls_to_try, thumb_file,
                article_url=html_url_for_image,
            )
            if image_path:
                logger.info("Thumbnail extracted for %s", article_id)
            else:
                logger.info("No thumbnail for %s (PDF and HTML both failed)", article_id)

        # Step 4 — Attempt full-text retrieval via OpenAlex content API.
        fulltext: Optional[str] = None
        if not self.dry_run:
            openalex_id = getattr(raw, "_openalex_id", "")
            if openalex_id:
                try:
                    fulltext = self.fetcher.fetch_fulltext(openalex_id)
                    if fulltext:
                        logger.info(
                            "Full text available for %s (%d chars)",
                            article_id, len(fulltext),
                        )
                    else:
                        logger.info(
                            "No full text from OpenAlex for %s — "
                            "using abstract-only summary",
                            article_id,
                        )
                except Exception as exc:
                    logger.warning(
                        "Full-text fetch failed for %s: %s", article_id, exc
                    )

            # Fallback: try preprint URL, article URL, or OA PDF.
            if not fulltext:
                try:
                    from ..ai.fulltext import fetch_fulltext as fetch_ft_legacy
                    fulltext = fetch_ft_legacy(
                        preprint_url=raw.preprint_url,
                        article_url=raw.article_url,
                        doi=raw.article_doi,
                        oa_pdf_url=oa_pdf_url,
                        all_pdf_urls=all_pdf_urls,
                    )
                    if fulltext:
                        logger.info(
                            "Full text from fallback sources for %s (%d chars)",
                            article_id, len(fulltext),
                        )
                except Exception as exc:
                    logger.warning(
                        "Fallback full-text fetch failed for %s: %s",
                        article_id, exc,
                    )

        # Step 5 — AI summarisation.
        ai_output: Optional[Dict[str, Any]] = None
        if not self.dry_run and self.summarizer is not None:
            ai_output = self.summarizer.summarize(raw, fulltext=fulltext)
            if ai_output is None:
                logger.warning(
                    "AI summarisation failed for %s — skipping (will not "
                    "write an entry with empty summaries)",
                    article_id,
                )
                report["errors"].append(
                    {"journal": journal_name, "error": "AI summarisation failed"}
                )
                return

        # Step 6 — Assemble and write JSON entry.
        # Use the actual mode from the summariser — it may have fallen back
        # from full-text to abstract-only if the model rejected the input.
        if self.summarizer:
            actual_mode = getattr(self.summarizer, "_last_mode", "abstract-only")
        else:
            actual_mode = "full-text" if fulltext else "abstract-only"
        entry = self._build_entry(
            raw, article_id, image_path, ai_output,
            summary_mode=actual_mode,
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
        """Build the final JSON entry in the frontend-compatible format."""
        if image_path:
            try:
                local_img = "data/" + str(image_path.relative_to(DATA_DIR))
            except ValueError:
                local_img = str(image_path)
        else:
            local_img = ""

        ai = ai_output or {}
        title_zh = ai.get("title", {}).get("zh", raw.article_title or "")
        title_en = ai.get("title", {}).get("en", raw.article_title or "")
        summary_zh = ai.get("summary", {}).get("zh", "")
        summary_en = ai.get("summary", {}).get("en", "")

        images: List[Dict[str, Any]] = []
        if local_img:
            images.append({
                "url": local_img,
                "caption": {
                    "zh": raw.cover_description or "",
                    "en": raw.cover_description or "",
                },
            })

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
                "source": "openalex",
            },
        }
        return entry

    # ------------------------------------------------------------------
    # Index / latest manifests
    # ------------------------------------------------------------------

    def _rebuild_index(self) -> None:
        """Rebuild ``data/index.json`` from all individual entry files."""
        articles = []
        for f in sorted(DATA_DIR.glob("articles/**/*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                article_id = data.get("id", f.stem)
                date_str = data.get("date", "")
                rel_path = str(f.relative_to(DATA_DIR))
                title = data.get("coverStory", {}).get("title", {})
                title_zh = title.get("zh", "")
                title_en = title.get("en", "")
                cover_url = data.get("coverImage", {}).get("url", "")

                # Validate: skip entries with missing critical fields.
                if not date_str or not date_str.strip():
                    logger.warning("Skipping %s: empty date", f)
                    continue
                if not title_zh and not title_en:
                    logger.warning("Skipping %s: no title", f)
                    continue

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

        # NOTE: We intentionally do NOT scan flat data/*.json files.
        # Legacy root-level JSON files use an old schema (cover_image,
        # article, ai_summary) that is incompatible with the frontend
        # and can cause crashes (e.g. empty date fields).

        articles.sort(key=lambda e: e.get("date", ""), reverse=True)

        index = {
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "articles": articles,
        }
        self._write_json(INDEX_FILE, index)
        logger.info("Rebuilt %s with %d entries", INDEX_FILE, len(articles))

    def _rebuild_latest(self) -> None:
        """Rebuild ``data/latest.json``."""
        latest: Dict[str, str] = {}
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
    def _resolve_journals(journals: Optional[List[str]]) -> List[str]:
        """Map user-supplied journal names to registry keys."""
        if not journals or journals == ["all"]:
            return list(JOURNAL_REGISTRY.keys())

        result = []
        for name in journals:
            lower = name.lower().strip()
            # Direct key match.
            if lower in JOURNAL_REGISTRY:
                result.append(lower)
                continue
            # Alias match.
            alias = JOURNAL_ALIASES.get(lower)
            if alias:
                result.append(alias)
                continue
            logger.warning(
                "Unknown journal '%s'. Available: %s",
                name,
                ", ".join(
                    list(JOURNAL_REGISTRY.keys())
                    + list(JOURNAL_ALIASES.keys())
                ),
            )
        return result

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
            tmp.unlink(missing_ok=True)
            raise
