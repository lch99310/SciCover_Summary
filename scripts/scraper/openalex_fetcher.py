"""
scraper.openalex_fetcher — Unified article fetcher using the OpenAlex API.

Replaces all six journal-specific web scrapers with a single API-based
approach.  OpenAlex provides structured metadata (title, authors, DOI,
abstract, volume/issue, publication date, open-access URLs, preprint
locations) for hundreds of millions of scholarly works.

Each journal is identified by its OpenAlex Source ID.  The fetcher queries
the ``/works`` endpoint, filtered by source + type + recency, and returns
a ``CoverArticleRaw`` compatible with the existing downstream pipeline.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from .base import CoverArticleRaw

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Journal registry — OpenAlex Source IDs
# ---------------------------------------------------------------------------

JOURNAL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "science": {
        "source_id": "S3880285",
        "display_name": "Science",
        "slug": "science",
        "require_oa": True,
    },
    "nature": {
        "source_id": "S137773608",
        "display_name": "Nature",
        "slug": "nature",
        "require_oa": True,
    },
    "cell": {
        "source_id": "S110447773",
        "display_name": "Cell",
        "slug": "cell",
        "require_oa": True,
    },
    "polgeog": {
        "source_id": "S202534398",
        "display_name": "Political Geography",
        "slug": "polgeog",
        "require_oa": True,
    },
    "intorg": {
        "source_id": "S160686149",
        "display_name": "International Organization",
        "slug": "intorg",
        # IO is a quarterly journal with few OA articles.  Disabling the
        # OA filter gives access to regular-issue articles (abstract-only
        # summaries are still useful).
        "require_oa": False,
    },
    "asr": {
        "source_id": "S157620343",
        "display_name": "American Sociological Review",
        "slug": "asr",
        # ASR publishes infrequently with few OA articles.
        "require_oa": False,
    },
}

# Aliases for user-facing --journal names.
JOURNAL_ALIASES: Dict[str, str] = {
    "political geography": "polgeog",
    "international organization": "intorg",
    "american sociological review": "asr",
}

API_BASE = "https://api.openalex.org"
CONTENT_BASE = "https://content.openalex.org"


def _doi_pdf_patterns(doi: str) -> List[str]:
    """Construct direct publisher PDF URLs from a DOI.

    Many publishers serve PDFs at predictable URLs derived from the DOI.
    These are more reliable than the OpenAlex content API which often
    returns 404.
    """
    urls: List[str] = []
    doi_lower = doi.lower()
    suffix = doi.split("/", 1)[1] if "/" in doi else doi

    # Nature / Springer (10.1038/...)
    if doi_lower.startswith("10.1038/"):
        urls.append(f"https://www.nature.com/articles/{suffix}.pdf")

    # Science / AAAS (10.1126/...)
    elif doi_lower.startswith("10.1126/"):
        urls.append(f"https://www.science.org/doi/pdf/{doi}")

    # Elsevier (10.1016/...) — covers Cell Press, ScienceDirect,
    # Political Geography, and all other Elsevier journals.
    # ScienceDirect PDF endpoint works for all Elsevier DOIs.
    elif doi_lower.startswith("10.1016/"):
        # ScienceDirect PDF (works for all Elsevier journals)
        urls.append(f"https://www.sciencedirect.com/science/article/pii/{suffix}/pdfft")
        # Cell Press has its own PDF endpoint for cell.* sub-journals
        if "j.cell." in doi_lower or ".cell." in doi_lower:
            urls.append(f"https://www.cell.com/action/showPdf?pii={suffix}")

    # Cambridge University Press (10.1017/...)
    elif doi_lower.startswith("10.1017/"):
        urls.append(
            f"https://www.cambridge.org/core/services/aop-cambridge-core"
            f"/content/view/{doi}"
        )

    # SAGE Publications (10.1177/...)
    elif doi_lower.startswith("10.1177/"):
        urls.append(f"https://journals.sagepub.com/doi/pdf/{doi}")

    # Taylor & Francis (10.1080/...)
    elif doi_lower.startswith("10.1080/"):
        urls.append(f"https://www.tandfonline.com/doi/pdf/{doi}")

    # Wiley (10.1002/...)
    elif doi_lower.startswith("10.1002/"):
        urls.append(f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}")

    return urls

# Only consider articles published within this many days as "recent".
# This prevents the tier system from selecting old articles with better
# metadata over newer articles with less metadata.
_RECENT_DAYS = 180


# ---------------------------------------------------------------------------
# Abstract reconstruction
# ---------------------------------------------------------------------------

def _reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Convert OpenAlex's inverted-index abstract back to plain text.

    OpenAlex stores abstracts as ``{"word": [pos0, pos1, ...], ...}``
    due to legal constraints.  We rebuild the sentence by sorting
    positions and joining tokens.
    """
    if not inverted_index:
        return ""
    # Build (position, word) pairs.
    pairs: List[tuple] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            pairs.append((pos, word))
    pairs.sort(key=lambda p: p[0])
    return " ".join(word for _, word in pairs)


# ---------------------------------------------------------------------------
# OpenAlex Fetcher
# ---------------------------------------------------------------------------

class OpenAlexFetcher:
    """Fetch the latest research article from a journal via the OpenAlex API.

    Usage::

        fetcher = OpenAlexFetcher(api_key="...")
        raw = fetcher.fetch_latest("science")
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or os.environ.get("OPENALEX_API_KEY", "")
        self._session = requests.Session()
        if not self._api_key:
            logger.warning(
                "No OpenAlex API key provided (OPENALEX_API_KEY). "
                "Requests may be rate-limited."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_latest(self, journal_key: str) -> Optional[CoverArticleRaw]:
        """Fetch the most recent research article for *journal_key*.

        Convenience wrapper around :meth:`fetch_candidates` that returns
        only the top-ranked candidate.
        """
        candidates = self.fetch_candidates(journal_key)
        return candidates[0] if candidates else None

    def fetch_candidates(self, journal_key: str) -> List[CoverArticleRaw]:
        """Return a ranked list of recent OA article candidates.

        The list is ordered by content-quality tier (best first), then by
        publication date (newest first within each tier).  Only articles
        from the last ``_RECENT_DAYS`` days are included, unless none exist
        (in which case the single newest article is returned as a fallback).

        The caller should iterate through the list, skipping articles that
        have already been processed, until a new article is found.
        """
        key = JOURNAL_ALIASES.get(journal_key.lower(), journal_key.lower())
        info = JOURNAL_REGISTRY.get(key)
        if info is None:
            logger.error("Unknown journal key: %s", journal_key)
            return []

        source_id = info["source_id"]
        journal_name = info["display_name"]
        require_oa = info.get("require_oa", True)

        filter_parts = [
            f"primary_location.source.id:{source_id}",
            "type:article",
            "is_paratext:false",
            "is_retracted:false",
            "biblio.volume:!null",
        ]
        if require_oa:
            filter_parts.append("open_access.is_oa:true")

        params: Dict[str, str] = {
            "filter": ",".join(filter_parts),
            "sort": "publication_date:desc",
            "per_page": "50",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        url = f"{API_BASE}/works"
        data = self._api_get(url, params=params)
        if data is None:
            return []

        results = data.get("results", [])
        if not results:
            logger.warning("No articles found for %s", journal_name)
            return []

        ranked = self._rank_candidates(results, journal_name)
        return [self._work_to_raw(w, journal_name) for w in ranked]

    def fetch_fulltext(self, openalex_id: str) -> Optional[str]:
        """Download the full text of a work via OpenAlex's content API.

        Tries TEI XML (Grobid parsed text) first, then the content API PDF,
        then falls back to returning ``None``.

        Returns plain text or ``None``.
        """
        # Extract the short ID (e.g. "W2741809807" from the full URL).
        short_id = openalex_id
        if "/" in short_id:
            short_id = short_id.rsplit("/", 1)[-1]

        if not self._api_key:
            return None

        # Strategy 1: TEI XML from OpenAlex content API (parsed full text).
        xml_url = f"{CONTENT_BASE}/works/{short_id}.tei.xml"
        xml_text = self._download_content(xml_url)
        if xml_text:
            plain = self._tei_to_text(xml_text)
            if plain and len(plain) > 500:
                logger.info(
                    "Got full text from OpenAlex TEI XML (%d chars)",
                    len(plain),
                )
                return self._truncate(plain)

        # Strategy 2: Download PDF from content API and extract text.
        pdf_url = f"{CONTENT_BASE}/works/{short_id}.pdf"
        text = self._extract_text_from_content_pdf(pdf_url)
        if text:
            logger.info(
                "Got full text from OpenAlex content PDF (%d chars)",
                len(text),
            )
            return self._truncate(text)

        return None

    def get_preprint_url(self, work: Dict[str, Any]) -> str:
        """Extract a preprint URL from a *known* preprint server.

        Only returns URLs on servers that our fulltext fetcher can actually
        handle.  Institutional repositories (DSpace, university repos, etc.)
        are excluded because they rarely provide scrapable full text.
        """
        _PREPRINT_SERVERS = (
            "arxiv", "biorxiv", "medrxiv", "ssrn", "socarxiv",
            "osf.io/preprints", "osf.io", "repec", "ideas.repec",
            "econpapers", "nber.org/papers",
        )

        for loc in work.get("locations", []):
            landing = loc.get("landing_page_url") or ""
            if not landing:
                continue

            # Only match known preprint server domains.
            landing_lower = landing.lower()
            for server in _PREPRINT_SERVERS:
                if server in landing_lower:
                    return landing

        return ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rank_candidates(
        self, results: List[Dict[str, Any]], journal_name: str,
    ) -> List[Dict[str, Any]]:
        """Rank articles by content-quality tier, returning all recent ones.

        Results arrive sorted by ``publication_date:desc`` (newest first).

        Tier order (best first):
          1. has_fulltext + PDF + abstract
          2. preprint + abstract
          3. PDF + abstract
          4. abstract only

        Only articles from the last ``_RECENT_DAYS`` days are included.
        If none exist, the single newest article with an abstract is returned.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=_RECENT_DAYS)
        ).strftime("%Y-%m-%d")

        tier1: List[Dict[str, Any]] = []
        tier2: List[Dict[str, Any]] = []
        tier3: List[Dict[str, Any]] = []
        tier4: List[Dict[str, Any]] = []

        for work in results:
            doi = work.get("doi") or ""
            if "d41586" in doi or "d41591" in doi:
                continue

            has_abstract = bool(work.get("abstract_inverted_index"))
            if not has_abstract:
                continue

            pub_date = work.get("publication_date", "") or ""
            if pub_date < cutoff:
                continue

            best_oa = work.get("best_oa_location", {}) or {}
            primary_loc = work.get("primary_location", {}) or {}
            has_pdf = bool(
                best_oa.get("pdf_url") or primary_loc.get("pdf_url")
            )
            has_fulltext = bool(work.get("has_fulltext"))
            has_preprint = bool(self.get_preprint_url(work))

            if has_fulltext and has_pdf:
                tier1.append(work)
            elif has_preprint:
                tier2.append(work)
            elif has_pdf:
                tier3.append(work)
            else:
                tier4.append(work)

        ranked = tier1 + tier2 + tier3 + tier4

        if not ranked:
            # No recent candidates — fall back to newest with abstract.
            for work in results:
                if bool(work.get("abstract_inverted_index")):
                    logger.warning(
                        "%s: no recent article found (cutoff=%s), "
                        "falling back to newest: '%s' (%s)",
                        journal_name, cutoff,
                        work.get("display_name", "")[:60],
                        work.get("publication_date", ""),
                    )
                    return [work]
            # Absolute last resort.
            return [results[0]]

        # Log the top pick.
        top = ranked[0]
        tag = (
            "has_fulltext + PDF + abstract" if top in tier1
            else "has preprint + abstract" if top in tier2
            else "has PDF + abstract" if top in tier3
            else "abstract only"
        )
        logger.info(
            "%s: top candidate '%s' (%s, %s) — %d total candidates",
            journal_name, top.get("display_name", "")[:60],
            tag, top.get("publication_date", ""), len(ranked),
        )
        return ranked

    def _work_to_raw(
        self, work: Dict[str, Any], journal_name: str,
    ) -> CoverArticleRaw:
        """Convert an OpenAlex work object to a ``CoverArticleRaw``."""
        biblio = work.get("biblio", {}) or {}
        primary_loc = work.get("primary_location", {}) or {}
        best_oa = work.get("best_oa_location", {}) or {}

        # Authors.
        authors: List[str] = []
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {}) or {}
            name = author.get("display_name", "")
            if name:
                authors.append(name)

        # DOI — strip the "https://doi.org/" prefix.
        raw_doi = work.get("doi") or ""
        doi = raw_doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        # Article URL — prefer the landing page from the primary location.
        article_url = primary_loc.get("landing_page_url") or raw_doi or ""

        # Pages.
        first_page = biblio.get("first_page", "")
        last_page = biblio.get("last_page", "")
        pages = ""
        if first_page and last_page and first_page != last_page:
            pages = f"{first_page}-{last_page}"
        elif first_page:
            pages = first_page

        # Abstract.
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

        # Preprint URL.
        preprint_url = self.get_preprint_url(work)

        # Open access PDF URL (can be used as cover image fallback or
        # for full-text retrieval).
        oa_pdf = best_oa.get("pdf_url") or primary_loc.get("pdf_url") or ""

        # Store the OpenAlex ID for content download.
        openalex_id = work.get("id", "")

        raw = CoverArticleRaw(
            journal=journal_name,
            volume=biblio.get("volume", "") or "",
            issue=biblio.get("issue", "") or "",
            date=work.get("publication_date", "") or "",
            cover_image_url="",  # OpenAlex doesn't provide cover images
            cover_image_credit="",
            cover_description="",
            article_title=work.get("display_name", "") or "",
            article_authors=authors,
            article_abstract=abstract,
            article_doi=doi,
            article_url=article_url,
            article_pages=pages,
            article_date=work.get("publication_date", "") or "",
            preprint_url=preprint_url,
        )

        # Attach extra metadata for the pipeline (not part of the dataclass,
        # but accessible via a private attribute).
        raw._openalex_id = openalex_id  # type: ignore[attr-defined]
        raw._oa_pdf_url = oa_pdf  # type: ignore[attr-defined]

        # Collect ALL PDF URLs from all locations.  Order:
        #   1. OpenAlex content API (most reliable, bypasses publisher blocks)
        #   2. Repository copies (PMC, Europe PMC, etc.)
        #   3. Primary OA PDF from publisher
        #   4. Other publisher PDFs
        #   5. DOI-based direct publisher PDF URLs (constructed from DOI)
        all_pdfs: List[str] = []

        # OpenAlex content API PDF — requires API key, $0.01/file, $1/day free.
        # This bypasses ALL publisher anti-scraping since OpenAlex has already
        # crawled and cached the PDFs.
        if self._api_key and openalex_id:
            short_id = openalex_id.rsplit("/", 1)[-1] if "/" in openalex_id else openalex_id
            content_pdf = f"{CONTENT_BASE}/works/{short_id}.pdf?api_key={self._api_key}"
            all_pdfs.append(content_pdf)

        repo_pdfs: List[str] = []
        publisher_pdfs: List[str] = []
        for loc in work.get("locations", []):
            loc_pdf = loc.get("pdf_url")
            if not loc_pdf:
                continue
            source = loc.get("source") or {}
            source_type = (source.get("type") or "").lower()
            if source_type == "repository":
                repo_pdfs.append(loc_pdf)
            elif loc_pdf != oa_pdf:
                publisher_pdfs.append(loc_pdf)
        all_pdfs.extend(repo_pdfs)
        if oa_pdf:
            all_pdfs.append(oa_pdf)
        all_pdfs.extend(publisher_pdfs)

        # Construct direct publisher PDF URLs from DOI.  These bypass
        # the OpenAlex content API (which often returns 404) and go
        # straight to the publisher's PDF endpoint.
        if doi:
            for pattern in _doi_pdf_patterns(doi):
                all_pdfs.append(pattern)

        # deduplicate while preserving order
        seen: set = set()
        deduped: List[str] = []
        for u in all_pdfs:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        raw._all_pdf_urls = deduped  # type: ignore[attr-defined]

        return raw

    def _api_get(
        self, url: str, *, params: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Make a GET request to the OpenAlex API and return the JSON body."""
        try:
            logger.debug("OpenAlex API: GET %s params=%s", url, params)
            resp = self._session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("OpenAlex API request failed: %s", exc)
            return None
        except ValueError as exc:
            logger.error("OpenAlex API returned invalid JSON: %s", exc)
            return None

    def _download_content(self, url: str) -> Optional[str]:
        """Download text content from the OpenAlex content API."""
        params = {}
        if self._api_key:
            params["api_key"] = self._api_key
        try:
            resp = self._session.get(url, params=params, timeout=60)
            if resp.status_code == 404:
                logger.debug("Content not available: %s", url)
                return None
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.debug("Content download failed: %s", exc)
            return None

    def _extract_text_from_content_pdf(self, pdf_url: str) -> Optional[str]:
        """Download a PDF from the content API and extract text via PyMuPDF."""
        import tempfile
        from pathlib import Path

        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.debug("PyMuPDF not installed — cannot extract content PDF")
            return None

        params = {}
        if self._api_key:
            params["api_key"] = self._api_key

        try:
            resp = self._session.get(
                pdf_url, params=params, timeout=60, stream=True,
            )
            if resp.status_code == 404:
                logger.debug("Content PDF not available: %s", pdf_url)
                return None
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.debug("Content PDF download failed: %s", exc)
            return None

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
                for chunk in resp.iter_content(chunk_size=8192):
                    tmp.write(chunk)

            doc = fitz.open(tmp_path)
            text_parts = []
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()

            text = "\n\n".join(text_parts)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()

            if len(text) > 500:
                return text
            return None

        except Exception as exc:
            logger.debug("Content PDF text extraction failed: %s", exc)
            return None
        finally:
            if tmp_path:
                try:
                    Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    pass

    @staticmethod
    def _tei_to_text(xml_text: str) -> str:
        """Extract plain text from TEI XML (Grobid output).

        This is a lightweight extraction — we pull text from <body>
        paragraphs and sections without needing a full XML parser.
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(xml_text, "lxml-xml")

            # Remove references section.
            for ref in soup.select("listBibl, biblStruct"):
                ref.decompose()

            body = soup.find("body")
            if body:
                text = body.get_text(separator="\n", strip=True)
                # Collapse multiple blank lines.
                text = re.sub(r"\n{3,}", "\n\n", text)
                return text.strip()
        except Exception as exc:
            logger.debug("TEI XML parsing failed: %s", exc)

        # Fallback: regex-based extraction.
        text = re.sub(r"<[^>]+>", " ", xml_text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _truncate(text: str, max_chars: int = 60_000) -> str:
        """Truncate text to *max_chars*, breaking at a paragraph boundary."""
        if len(text) <= max_chars:
            return text
        cut = text[:max_chars].rfind("\n\n")
        if cut > max_chars * 0.8:
            return text[:cut].rstrip()
        return text[:max_chars].rstrip()
