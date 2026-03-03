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
    },
    "nature": {
        "source_id": "S137773608",
        "display_name": "Nature",
        "slug": "nature",
    },
    "cell": {
        "source_id": "S110447773",
        "display_name": "Cell",
        "slug": "cell",
    },
    "polgeog": {
        "source_id": "S202534398",
        "display_name": "Political Geography",
        "slug": "polgeog",
    },
    "intorg": {
        "source_id": "S160686149",
        "display_name": "International Organization",
        "slug": "intorg",
    },
    "asr": {
        "source_id": "S157620343",
        "display_name": "American Sociological Review",
        "slug": "asr",
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

        Parameters
        ----------
        journal_key:
            A key from ``JOURNAL_REGISTRY`` (e.g. ``"science"``) or an
            alias from ``JOURNAL_ALIASES`` (e.g. ``"political geography"``).

        Returns ``None`` if the API call fails or no article is found.
        """
        key = JOURNAL_ALIASES.get(journal_key.lower(), journal_key.lower())
        info = JOURNAL_REGISTRY.get(key)
        if info is None:
            logger.error("Unknown journal key: %s", journal_key)
            return None

        source_id = info["source_id"]
        journal_name = info["display_name"]

        # Query: latest research articles from this source, sorted by date.
        params: Dict[str, str] = {
            "filter": (
                f"primary_location.source.id:{source_id},"
                "type:article,"
                "is_paratext:false,"
                "is_retracted:false"
            ),
            "sort": "publication_date:desc",
            "per_page": "5",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        url = f"{API_BASE}/works"
        data = self._api_get(url, params=params)
        if data is None:
            return None

        results = data.get("results", [])
        if not results:
            logger.warning("No articles found for %s", journal_name)
            return None

        # Pick the first result (most recent research article).
        work = results[0]
        return self._work_to_raw(work, journal_name)

    def fetch_fulltext(self, openalex_id: str) -> Optional[str]:
        """Download the full text of a work via OpenAlex's content API.

        Tries TEI XML (Grobid parsed text) first, then falls back to
        checking ``best_oa_location.pdf_url`` for a direct PDF link.

        Returns plain text or ``None``.
        """
        # Extract the short ID (e.g. "W2741809807" from the full URL).
        short_id = openalex_id
        if "/" in short_id:
            short_id = short_id.rsplit("/", 1)[-1]

        # Strategy 1: TEI XML from OpenAlex content API (parsed full text).
        if self._api_key:
            xml_url = f"{CONTENT_BASE}/works/{short_id}.grobid-xml"
            xml_text = self._download_content(xml_url)
            if xml_text:
                plain = self._tei_to_text(xml_text)
                if plain and len(plain) > 500:
                    logger.info(
                        "Got full text from OpenAlex TEI XML (%d chars)",
                        len(plain),
                    )
                    return self._truncate(plain)

        return None

    def get_preprint_url(self, work: Dict[str, Any]) -> str:
        """Extract a preprint URL from the work's locations, if available."""
        for loc in work.get("locations", []):
            version = (loc.get("version") or "").lower()
            source = loc.get("source") or {}
            source_type = (source.get("type") or "").lower()
            landing = loc.get("landing_page_url") or ""

            # Check for preprint repositories.
            if version in ("submittedVersion", "submitted"):
                return landing
            if source_type == "repository":
                # Check for known preprint servers.
                for server in ("arxiv", "biorxiv", "medrxiv", "ssrn", "socarxiv"):
                    if server in landing.lower():
                        return landing
        return ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
