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
from ..scraper.elsevier_api import (
    fetch_fulltext as elsevier_fetch_fulltext,
    fetch_first_figure as elsevier_fetch_first_figure,
    get_api_key as elsevier_get_api_key,
)
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
        """Fetch, summarise, and persist one journal.

        Iterates through ranked candidates from OpenAlex.  If the top
        candidate has already been processed, moves on to the next one
        instead of skipping the journal entirely.
        """

        # Step 1 — Fetch ranked candidates from OpenAlex.
        logger.info("Fetching candidates for %s via OpenAlex...", journal_name)
        candidates = self.fetcher.fetch_candidates(journal_key)
        if not candidates:
            logger.warning("OpenAlex returned nothing for %s", journal_name)
            report["errors"].append(
                {"journal": journal_name, "error": "OpenAlex returned no results"}
            )
            return

        # Step 2 — Find the first candidate we haven't processed yet.
        raw = None
        article_id = ""
        entry_file = None

        for candidate in candidates:
            # Validate date.
            if not candidate.date or not candidate.date.strip():
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                candidate.date = today

            cand_id = generate_article_id(candidate.journal, candidate.date)
            try:
                dt = datetime.strptime(candidate.date, "%Y-%m-%d")
                cand_dir = (
                    DATA_DIR / "articles" / f"{dt.year:04d}" / f"{dt.month:02d}"
                )
            except (ValueError, TypeError):
                cand_dir = DATA_DIR / "articles"

            cand_file = cand_dir / f"{cand_id}.json"

            if cand_file.exists():
                # Check if the existing file is a DIFFERENT article (same
                # journal + date but different DOI).  This happens when a
                # journal publishes multiple articles on the same date
                # (e.g. International Organization special issues).
                if self._is_same_article(cand_file, candidate):
                    logger.info(
                        "Already have %s ('%s') — trying next candidate",
                        cand_id, candidate.article_title[:50],
                    )
                    report["skipped"].append(cand_id)
                    continue
                # Different article with same date — find a unique ID.
                cand_id, cand_file = self._find_unique_id(
                    cand_id, cand_dir, candidate,
                )
                if cand_id is None:
                    # All suffixed IDs also exist for this article.
                    report["skipped"].append(
                        generate_article_id(candidate.journal, candidate.date)
                    )
                    continue

            # Found a new article to process.
            raw = candidate
            article_id = cand_id
            entry_file = cand_file
            break

        if raw is None:
            logger.info(
                "All %d candidates for %s already processed",
                len(candidates), journal_name,
            )
            return

        logger.info(
            "%s: processing '%s' (vol.%s #%s, %s)",
            journal_name,
            raw.article_title[:60],
            raw.volume,
            raw.issue,
            raw.date,
        )

        # Step 3 — Extract thumbnail.
        # Strategy: Elsevier API figures → PDF pages → article HTML → preprint HTML.
        image_path: Optional[Path] = None
        oa_pdf_url = getattr(raw, "_oa_pdf_url", "")
        all_pdf_urls: list = getattr(raw, "_all_pdf_urls", [])

        # Also try Unpaywall to discover additional PDF URLs for thumbnails.
        if raw.article_doi and not self.dry_run:
            unpaywall_pdf = self._fetch_unpaywall_pdf(raw.article_doi)
            if unpaywall_pdf and unpaywall_pdf not in all_pdf_urls:
                all_pdf_urls.append(unpaywall_pdf)

        # For bioRxiv/medRxiv preprints: add the preprint PDF to the URL list.
        if raw.preprint_url and ("biorxiv.org" in raw.preprint_url or "medrxiv.org" in raw.preprint_url):
            from ..scraper.biorxiv_api import get_preprint_pdf_url
            preprint_pdf = get_preprint_pdf_url(raw.preprint_url)
            if preprint_pdf not in all_pdf_urls:
                all_pdf_urls.insert(0, preprint_pdf)  # prioritise preprint PDF

        # Determine the best URL for HTML image extraction: prefer preprint_url
        # for bioRxiv/medRxiv (reliable og:image), then article_url.
        if raw.preprint_url and ("biorxiv.org" in raw.preprint_url or "medrxiv.org" in raw.preprint_url):
            html_url_for_image = raw.preprint_url
        else:
            html_url_for_image = raw.article_url or raw.preprint_url or ""

        if not self.dry_run:
            img_slug = JOURNAL_IMAGE_SLUG.get(journal_name, journal_name.lower())
            img_dir = IMAGES_DIR / img_slug
            ensure_dir(img_dir)
            thumb_file = img_dir / f"{article_id}-cover.jpg"

            # Strategy 1: Elsevier API figures (Cell, Political Geography).
            doi = raw.article_doi or ""
            if doi.lower().startswith("10.1016/") and elsevier_get_api_key():
                image_path = elsevier_fetch_first_figure(doi, thumb_file)
                if image_path:
                    logger.info(
                        "Thumbnail from Elsevier API for %s", article_id,
                    )

            # Strategy 2: PDF pages → article HTML → preprint HTML.
            # Always attempt if we have any URL source (PDF, HTML, or DOI).
            if not image_path and (oa_pdf_url or all_pdf_urls or html_url_for_image or doi):
                pdf_urls_to_try = list(all_pdf_urls)
                if oa_pdf_url and oa_pdf_url not in pdf_urls_to_try:
                    pdf_urls_to_try.append(oa_pdf_url)
                image_path = extract_thumbnail_from_urls(
                    pdf_urls_to_try, thumb_file,
                    article_url=html_url_for_image,
                    doi=doi,
                )

            if image_path:
                logger.info("Thumbnail extracted for %s", article_id)
            else:
                logger.info("No thumbnail for %s (all strategies failed)", article_id)

        # Step 4 — Full-text retrieval.
        # For Elsevier journals (Cell, Political Geography), the Elsevier
        # Text Mining API is the most reliable source — try it first.
        fulltext: Optional[str] = None
        if not self.dry_run:
            # Priority 1: Elsevier API (Cell, Political Geography).
            if doi.lower().startswith("10.1016/"):
                try:
                    fulltext = elsevier_fetch_fulltext(doi)
                    if fulltext:
                        logger.info(
                            "Full text from Elsevier API for %s (%d chars)",
                            article_id, len(fulltext),
                        )
                except Exception as exc:
                    logger.debug(
                        "Elsevier API fulltext failed for %s: %s",
                        article_id, exc,
                    )

            # Priority 2: OpenAlex content API.
            if not fulltext:
                openalex_id = getattr(raw, "_openalex_id", "")
                if openalex_id:
                    try:
                        fulltext = self.fetcher.fetch_fulltext(openalex_id)
                        if fulltext:
                            logger.info(
                                "Full text from OpenAlex for %s (%d chars)",
                                article_id, len(fulltext),
                            )
                    except Exception as exc:
                        logger.warning(
                            "OpenAlex full-text fetch failed for %s: %s",
                            article_id, exc,
                        )

            # Priority 3: Crossref full-text links (public API).
            # Crossref metadata often includes XML/HTML full-text URLs
            # that are accessible without subscription for OA articles.
            if not fulltext and doi:
                try:
                    from ..ai.fulltext import fetch_crossref_fulltext
                    fulltext = fetch_crossref_fulltext(doi)
                    if fulltext:
                        logger.info(
                            "Full text from Crossref links for %s (%d chars)",
                            article_id, len(fulltext),
                        )
                except Exception as exc:
                    logger.debug(
                        "Crossref full-text fetch failed for %s: %s",
                        article_id, exc,
                    )

            # Priority 4: preprint URL, article HTML, Europe PMC, PDFs.
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

    @staticmethod
    def _is_same_article(existing_file: Path, candidate: CoverArticleRaw) -> bool:
        """Check if an existing JSON file contains the same article as *candidate*.

        Compares by DOI (primary) or article title (fallback).  Returns
        ``True`` if the existing file is the same article (true duplicate).
        """
        try:
            data = json.loads(existing_file.read_text(encoding="utf-8"))
            existing_doi = (
                data.get("coverStory", {})
                .get("keyArticle", {})
                .get("doi", "")
            )
            cand_doi = candidate.article_doi or ""

            # If both have DOIs, compare those.
            if existing_doi and cand_doi:
                return existing_doi.lower() == cand_doi.lower()

            # Fallback: compare article titles.
            existing_title = (
                data.get("coverStory", {})
                .get("keyArticle", {})
                .get("title", "")
            ).lower().strip()
            cand_title = (candidate.article_title or "").lower().strip()

            if existing_title and cand_title:
                return existing_title == cand_title

            # Can't determine — assume same to be safe.
            return True
        except (json.JSONDecodeError, OSError):
            return True

    def _find_unique_id(
        self,
        base_id: str,
        parent_dir: Path,
        candidate: CoverArticleRaw,
    ) -> tuple:
        """Find a unique article ID by appending a numeric suffix.

        Tries ``{base_id}-02``, ``{base_id}-03``, etc.  For each suffixed
        file that already exists, checks whether it's the same article.

        Returns ``(unique_id, file_path)`` or ``(None, None)`` if the
        article already exists under a suffixed ID.
        """
        for seq in range(2, 50):
            suffixed_id = f"{base_id}-{seq:02d}"
            suffixed_file = parent_dir / f"{suffixed_id}.json"
            if not suffixed_file.exists():
                return suffixed_id, suffixed_file
            # File exists — check if it's the same article.
            if self._is_same_article(suffixed_file, candidate):
                logger.info(
                    "Already have %s ('%s') — trying next candidate",
                    suffixed_id, candidate.article_title[:50],
                )
                return None, None
        return None, None

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

    @staticmethod
    def _fetch_unpaywall_pdf(doi: str) -> Optional[str]:
        """Query the Unpaywall API for a direct OA PDF URL."""
        import requests as _req
        api_url = f"https://api.unpaywall.org/v2/{doi}?email=scicover@example.com"
        try:
            resp = _req.get(api_url, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            best_oa = data.get("best_oa_location") or {}
            pdf_url = best_oa.get("url_for_pdf") or ""
            if pdf_url:
                logger.info("Unpaywall found PDF for thumbnail (DOI %s)", doi)
                return pdf_url
            for loc in data.get("oa_locations", []):
                pdf_url = loc.get("url_for_pdf") or ""
                if pdf_url:
                    return pdf_url
        except Exception:
            pass
        return None

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
