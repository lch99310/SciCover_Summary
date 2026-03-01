"""
ai.fulltext — Full-text retrieval for preprint and open-access articles.

Attempts to fetch the full text of an article from:
  1. Preprint servers (arXiv, bioRxiv, medRxiv, SSRN, SocArXiv, etc.)
  2. Open-access publisher pages (ScienceDirect, Cambridge Core, etc.)

Returns plain text suitable for feeding to the AI summariser.  If retrieval
fails, the caller should fall back to abstract-only summarisation.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Maximum characters to keep from the full text.  DeepSeek-V3 has a 128k
# context window, but we stay well under that to leave room for the prompt.
MAX_FULLTEXT_CHARS = 60_000

# Shared HTTP session headers.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_fulltext(
    preprint_url: str = "",
    article_url: str = "",
    doi: str = "",
) -> Optional[str]:
    """Try to retrieve the full text of an article.

    Strategy (tried in order):
      1. If *preprint_url* points to a known server, fetch from there.
      2. If *article_url* is on a known open-access publisher, try that.
      3. Return ``None`` — caller should fall back to abstract-only mode.

    Returns
    -------
    str or None
        Plain text of the article (truncated to MAX_FULLTEXT_CHARS),
        or ``None`` if retrieval failed.
    """
    # --- Strategy 1: Preprint URL ---
    if preprint_url:
        text = _try_preprint(preprint_url)
        if text:
            return _truncate(text)

    # --- Strategy 2: Open-access article URL ---
    if article_url:
        text = _try_open_access(article_url)
        if text:
            return _truncate(text)

    return None


# ---------------------------------------------------------------------------
# Preprint fetchers
# ---------------------------------------------------------------------------

def _try_preprint(url: str) -> Optional[str]:
    """Dispatch to the appropriate preprint fetcher."""
    if "arxiv.org" in url:
        return _fetch_arxiv(url)
    if "biorxiv.org" in url or "medrxiv.org" in url:
        return _fetch_biorxiv(url)
    if "ssrn.com" in url:
        return _fetch_ssrn(url)
    # Other preprint servers can be added here.
    return None


def _fetch_arxiv(url: str) -> Optional[str]:
    """Fetch full text from arXiv via the HTML rendering.

    arXiv now provides HTML versions at https://arxiv.org/html/<id>.
    Falls back to the abstract page if the HTML version is unavailable.
    """
    # Extract the arXiv ID (e.g., "2601.08791").
    m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", url)
    if not m:
        logger.debug("Could not extract arXiv ID from %s", url)
        return None

    arxiv_id = m.group(0)

    # Try the HTML rendering first.
    html_url = f"https://arxiv.org/html/{arxiv_id}"
    html = _http_get(html_url)
    if html:
        soup = BeautifulSoup(html, "lxml")
        # The main article text is inside <article> or <div class="ltx_page_content">.
        main = soup.select_one("article, .ltx_page_content, .ltx_document")
        if main:
            text = _extract_text(main)
            if len(text) > 500:
                logger.info("Got arXiv HTML full text (%d chars)", len(text))
                return text

    # Fall back to abstract page.
    abs_url = f"https://arxiv.org/abs/{arxiv_id}"
    html = _http_get(abs_url)
    if html:
        soup = BeautifulSoup(html, "lxml")
        abstract_block = soup.select_one(".abstract")
        if abstract_block:
            text = _extract_text(abstract_block)
            if text:
                logger.info("Got arXiv abstract only (%d chars)", len(text))
                return text

    return None


def _fetch_biorxiv(url: str) -> Optional[str]:
    """Fetch full text from bioRxiv / medRxiv.

    bioRxiv provides a .full suffix for the full-text HTML view.
    """
    # Normalise to the full-text URL.
    full_url = url.rstrip("/")
    if not full_url.endswith(".full"):
        full_url += ".full"

    html = _http_get(full_url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    # Main article content is inside <div class="article fulltext-view">.
    main = soup.select_one(
        ".article.fulltext-view, #content-block, .highwire-article-body"
    )
    if main:
        text = _extract_text(main)
        if len(text) > 500:
            logger.info("Got bioRxiv/medRxiv full text (%d chars)", len(text))
            return text

    return None


def _fetch_ssrn(url: str) -> Optional[str]:
    """Attempt to fetch from SSRN — usually behind a paywall, so this
    is best-effort.
    """
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    abstract_div = soup.select_one(".abstract-text, #abstract")
    if abstract_div:
        text = _extract_text(abstract_div)
        if text:
            logger.info("Got SSRN abstract (%d chars)", len(text))
            return text

    return None


# ---------------------------------------------------------------------------
# Open-access publisher fetchers
# ---------------------------------------------------------------------------

def _try_open_access(url: str) -> Optional[str]:
    """Try to fetch full text from open-access publisher pages."""
    if "sciencedirect.com" in url:
        return _fetch_sciencedirect(url)
    if "cambridge.org" in url:
        return _fetch_cambridge(url)
    # Nature / Science / Cell Press often require subscriptions for the full
    # text body — the abstract is already captured by the scraper, so we
    # skip them here.
    return None


def _fetch_sciencedirect(url: str) -> Optional[str]:
    """Fetch from ScienceDirect (Elsevier) — works for open-access articles."""
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    # ScienceDirect puts the article body in <div id="body">.
    body = soup.select_one(
        "#body, .Body, div[class*='body'], "
        ".article-body, #abstracts"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 500:
            logger.info("Got ScienceDirect full text (%d chars)", len(text))
            return text

    return None


def _fetch_cambridge(url: str) -> Optional[str]:
    """Fetch from Cambridge Core — works for open-access articles."""
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(
        ".article-body, .article, [class*='article-body'], "
        "#maincontent, .body"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 500:
            logger.info("Got Cambridge Core full text (%d chars)", len(text))
            return text

    return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _http_get(url: str, *, timeout: int = 30) -> Optional[str]:
    """Simple GET request with retries."""
    for attempt in range(1, 3):
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            logger.debug("HTTP GET failed for %s (attempt %d): %s", url, attempt, exc)
            if attempt < 2:
                time.sleep(2)
    return None


def _extract_text(element: BeautifulSoup) -> str:
    """Extract and clean text from a BS4 element, removing scripts/styles."""
    # Remove unwanted tags.
    for tag in element.select("script, style, nav, footer, .references, .ref-list"):
        tag.decompose()
    text = element.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _truncate(text: str) -> str:
    """Truncate to MAX_FULLTEXT_CHARS, breaking at a paragraph boundary."""
    if len(text) <= MAX_FULLTEXT_CHARS:
        return text
    # Try to break at a paragraph boundary.
    cut = text[:MAX_FULLTEXT_CHARS].rfind("\n\n")
    if cut > MAX_FULLTEXT_CHARS * 0.8:
        return text[:cut].rstrip()
    return text[:MAX_FULLTEXT_CHARS].rstrip()
