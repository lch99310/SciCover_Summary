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
# Playwright singleton  (lazy-initialised, shared across all scrapers)
# ---------------------------------------------------------------------------

_pw_browser = None
_pw_playwright = None


def _get_playwright_browser():
    """Return a shared Playwright Chromium browser instance (headless).

    Lazily created on first call so that Playwright is only imported
    when actually needed (i.e. after a 403 from ``requests``).
    """
    global _pw_browser, _pw_playwright
    if _pw_browser is not None:
        return _pw_browser
    try:
        from playwright.sync_api import sync_playwright
        _pw_playwright = sync_playwright().start()
        _pw_browser = _pw_playwright.chromium.launch(headless=True)
        logger.info("Playwright browser launched for fallback fetching")
        return _pw_browser
    except Exception as exc:
        logger.warning("Playwright unavailable — no fallback for 403: %s", exc)
        return None


def shutdown_playwright() -> None:
    """Clean up the shared Playwright browser (called at pipeline exit)."""
    global _pw_browser, _pw_playwright
    if _pw_browser:
        try:
            _pw_browser.close()
        except Exception:
            pass
        _pw_browser = None
    if _pw_playwright:
        try:
            _pw_playwright.stop()
        except Exception:
            pass
        _pw_playwright = None

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
    article_date: str = ""                # Article-level publication date (may differ from issue date)

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
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Cache-Control": "max-age=0",
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
        seconds between attempts.  If all ``requests`` attempts fail with
        a **403 Forbidden** (common on publisher sites that block
        non-browser traffic), a single Playwright headless-Chromium
        fallback attempt is made before giving up.

        All HTTP and network errors are caught and logged rather than
        propagated so one bad page does not crash the entire pipeline.
        """
        last_status: Optional[int] = None

        for attempt in range(1, retries + 1):
            try:
                logger.debug("Fetching %s (attempt %d/%d)", url, attempt, retries)
                resp = self._session.get(url, timeout=30, allow_redirects=True)
                last_status = resp.status_code
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

        # ----- Playwright fallback for 403 Forbidden -----
        if last_status == 403:
            html = self._fetch_with_playwright(url)
            if html is not None:
                return html

        return None

    # ------------------------------------------------------------------
    # Playwright fallback
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_with_playwright(url: str, timeout_ms: int = 30_000) -> Optional[str]:
        """Fetch *url* using headless Chromium via Playwright.

        Returns the fully-rendered page HTML, or ``None`` on failure.
        This is only called as a fallback after ``requests`` receives a
        403 Forbidden, so the overhead of a real browser is acceptable.
        """
        browser = _get_playwright_browser()
        if browser is None:
            return None

        page = None
        try:
            page = browser.new_page()
            logger.info("Playwright fallback: loading %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Give JS-rendered content a moment to settle.
            page.wait_for_timeout(3000)
            html = page.content()
            logger.info("Playwright fallback succeeded for %s (%d chars)", url, len(html))
            return html
        except Exception as exc:
            logger.warning("Playwright fallback failed for %s: %s", url, exc)
            return None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

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
