"""
scraper.base — Abstract base scraper and shared data model.

Every journal scraper inherits from ``BaseScraper`` and returns one or more
``CoverArticleRaw`` instances that the downstream pipeline can consume.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional, List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class CoverArticleRaw:
    """Raw scraped data for a single journal-cover article.

    Fields intentionally mirror the final JSON schema so the pipeline can
    serialise this object directly after AI enrichment.
    """

    journal: str = ""
    volume: str = ""
    issue: str = ""
    date: str = ""                        # ISO-8601 date string, e.g. "2025-06-20"

    cover_image_url: str = ""             # Absolute URL to the hi-res cover image
    cover_image_credit: str = ""          # Photographer / illustrator credit
    cover_description: str = ""           # "On the cover" text from the TOC page

    article_title: str = ""
    article_authors: List[str] = field(default_factory=list)
    article_abstract: str = ""
    article_doi: str = ""                 # e.g. "10.1126/science.abc1234"
    article_url: str = ""                 # Absolute URL to the full article page
    article_pages: str = ""               # e.g. "123-127"

    preprint_url: str = ""                # Optional link to a preprint version

    def to_dict(self) -> dict:
        """Return a plain ``dict`` suitable for JSON serialisation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Abstract base scraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """Abstract base class that every journal scraper must implement.

    Provides shared helpers for HTTP fetching and HTML parsing so that
    concrete scrapers only need to worry about CSS selectors and page layout.
    """

    # Subclasses should set a human-readable journal name.
    JOURNAL_NAME: str = "Unknown"
    BASE_URL: str = ""

    # Shared HTTP session (created lazily per instance).
    _session: Optional[requests.Session] = None

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    # ------------------------------------------------------------------
    # Public API — must be implemented by every concrete scraper
    # ------------------------------------------------------------------

    @abstractmethod
    def scrape_current_issue(self) -> Optional[CoverArticleRaw]:
        """Scrape the current (latest) issue and return a ``CoverArticleRaw``.

        Returns ``None`` when scraping fails entirely so that the pipeline
        can skip this journal without raising.
        """
        ...

    @abstractmethod
    def scrape_issue(self, volume: str, issue: str) -> Optional[CoverArticleRaw]:
        """Scrape a specific back-issue identified by *volume* and *issue*."""
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _fetch(self, url: str, *, retries: int = 2, delay: float = 3.0) -> Optional[str]:
        """GET *url* and return the response text, or ``None`` on failure.

        Retries up to *retries* times with a linear back-off of *delay*
        seconds between attempts.  All HTTP and network errors are caught
        and logged rather than propagated so one bad page does not crash
        the entire pipeline.
        """
        for attempt in range(1, retries + 1):
            try:
                logger.debug("Fetching %s (attempt %d/%d)", url, attempt, retries)
                resp = self._session.get(url, timeout=30, allow_redirects=True)
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                logger.warning(
                    "Fetch failed for %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    retries,
                    exc,
                )
                if attempt < retries:
                    time.sleep(delay * attempt)
        return None

    def _parse_html(self, html: str) -> BeautifulSoup:
        """Parse raw HTML into a ``BeautifulSoup`` tree using the fast *lxml* parser."""
        return BeautifulSoup(html, "lxml")

    def _fetch_and_parse(self, url: str) -> Optional[BeautifulSoup]:
        """Convenience wrapper: fetch a URL then parse it.

        Returns ``None`` if the HTTP request fails.
        """
        html = self._fetch(url)
        if html is None:
            return None
        return self._parse_html(html)

    @staticmethod
    def _abs_url(base: str, relative: str) -> str:
        """Resolve *relative* against *base*, stripping leading ``//``."""
        if relative.startswith("http"):
            return relative
        if relative.startswith("//"):
            return "https:" + relative
        if relative.startswith("/"):
            # Extract scheme + host from base.
            from urllib.parse import urljoin
            return urljoin(base, relative)
        from urllib.parse import urljoin
        return urljoin(base, relative)

    @staticmethod
    def _clean_text(text: Optional[str]) -> str:
        """Collapse whitespace and strip a string, returning '' for None."""
        if not text:
            return ""
        return " ".join(text.split()).strip()
