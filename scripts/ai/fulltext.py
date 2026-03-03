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
import tempfile
import time
from pathlib import Path
from typing import List, Optional

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
    oa_pdf_url: str = "",
    all_pdf_urls: Optional[List[str]] = None,
) -> Optional[str]:
    """Try to retrieve the full text of an article.

    Strategy (tried in order):
      1. If *preprint_url* points to a known server, fetch from there.
      2. If *doi* is available, try Europe PMC (free full-text API).
      3. If *article_url* is on a known open-access publisher, try that.
      4. If PDF URLs are available, download and extract text via PyMuPDF.
      5. Return ``None`` — caller should fall back to abstract-only mode.

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

    # --- Strategy 2: Europe PMC (very reliable for OA articles) ---
    if doi:
        text = _fetch_europepmc(doi)
        if text:
            return _truncate(text)

    # --- Strategy 3: Open-access article URL ---
    if article_url:
        text = _try_open_access(article_url)
        if text:
            return _truncate(text)

    # --- Strategy 4: Extract text from OA PDF(s) via PyMuPDF ---
    pdf_urls_to_try = list(all_pdf_urls or [])
    if oa_pdf_url and oa_pdf_url not in pdf_urls_to_try:
        pdf_urls_to_try.append(oa_pdf_url)
    for pdf_url in pdf_urls_to_try:
        text = _extract_text_from_pdf(pdf_url)
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
    if "nature.com" in url:
        return _fetch_nature(url)
    if "science.org" in url or "sciencemag.org" in url:
        return _fetch_science(url)
    if "cell.com" in url:
        return _fetch_cell(url)
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


def _fetch_nature(url: str) -> Optional[str]:
    """Fetch full text from Nature.com for open-access articles.

    Nature serves OA articles as full HTML at the landing-page URL.
    """
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(
        "div.c-article-body, article .article__body, "
        "#article-body, .main-content"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 500:
            logger.info("Got Nature full text (%d chars)", len(text))
            return text

    return None


def _fetch_science(url: str) -> Optional[str]:
    """Fetch full text from Science.org for open-access articles."""
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(
        ".article__body, .bodySection, #bodymatter, "
        "div[role='doc-chapter'], .hlFld-Fulltext"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 500:
            logger.info("Got Science.org full text (%d chars)", len(text))
            return text

    return None


def _fetch_cell(url: str) -> Optional[str]:
    """Fetch full text from Cell.com (Cell Press) for OA articles."""
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(
        ".article-body, #body, div[class*='body'], "
        ".article__sections, .fullText"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 500:
            logger.info("Got Cell Press full text (%d chars)", len(text))
            return text

    return None


def _fetch_europepmc(doi: str) -> Optional[str]:
    """Fetch full text from Europe PMC REST API.

    Europe PMC provides free XML full text for open-access articles.
    This is one of the most reliable sources for OA biomedical content.
    """
    if not doi:
        return None

    api_url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query=DOI:{doi}&resultType=core&format=json"
    )
    try:
        resp = requests.get(api_url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("resultList", {}).get("result", [])
        if not results:
            return None

        pmcid = results[0].get("pmcid")
        if not pmcid:
            logger.debug("No PMC ID found for DOI %s", doi)
            return None

        xml_url = (
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        )
        xml_resp = requests.get(xml_url, timeout=60)
        if xml_resp.status_code != 200:
            return None

        soup = BeautifulSoup(xml_resp.text, "lxml-xml")
        body = soup.find("body")
        if body:
            for ref in body.select("ref-list, back"):
                ref.decompose()
            text = body.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            if len(text) > 500:
                logger.info("Got Europe PMC full text (%d chars)", len(text))
                return text
    except Exception as exc:
        logger.debug("Europe PMC fetch failed for DOI %s: %s", doi, exc)

    return None


# ---------------------------------------------------------------------------
# PDF text extraction (via PyMuPDF)
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(pdf_url: str, *, timeout: int = 60) -> Optional[str]:
    """Download a PDF and extract text using PyMuPDF (fitz).

    This is a last-resort strategy for when HTML full-text is unavailable.
    Works well for open-access articles that provide a direct PDF link.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.debug("PyMuPDF not installed — cannot extract text from PDF")
        return None

    # Download the PDF.
    try:
        resp = requests.get(
            pdf_url, headers=_HEADERS, timeout=timeout, stream=True,
        )
        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if "pdf" not in ct.lower() and "octet-stream" not in ct.lower():
            logger.debug("URL did not return a PDF (Content-Type: %s)", ct)
            return None
    except requests.RequestException as exc:
        logger.debug("PDF download failed for text extraction: %s", exc)
        return None

    # Write to temp file and extract text.
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
        # Clean up: collapse excessive whitespace.
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) > 500:
            logger.info("Extracted full text from PDF (%d chars)", len(text))
            return text

        logger.debug("PDF text too short (%d chars), skipping", len(text))
        return None

    except Exception as exc:
        logger.debug("PDF text extraction failed: %s", exc)
        return None
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


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
