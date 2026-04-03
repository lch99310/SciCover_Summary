"""
ai.fulltext — Full-text retrieval for preprint and open-access articles.

Attempts to fetch the full text of an article from:
  1. Preprint servers (arXiv, bioRxiv, medRxiv, SSRN, SocArXiv, etc.)
  2. Europe PMC (free full-text API).
  3. Open-access publisher pages (with generic HTML fallback).
  4. PDF text extraction (cookie-based session to bypass anti-scraping).

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
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Maximum characters to keep from the full text.  Qwen3 VL has a 131k
# context window; we stay well under that to leave room for the prompt.
MAX_FULLTEXT_CHARS = 60_000

# Shared HTTP session headers — mimic a real browser to avoid anti-scraping.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://scholar.google.com/",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_crossref_fulltext(doi: str) -> Optional[str]:
    """Fetch full text via Crossref ``link`` entries (public API).

    Crossref metadata often includes direct links to publisher XML/HTML
    full-text endpoints.  These links are part of the public Crossref
    metadata and are generally accessible for OA articles without
    subscription.

    This is particularly useful for AAAS (Science), Springer (Nature),
    and other publishers whose main article pages block scrapers but
    whose API endpoints may serve the content directly.
    """
    if not doi:
        return None

    url = f"https://api.crossref.org/works/{doi}"
    headers = {
        "User-Agent": "SciCover/1.0 (https://github.com/lch99310/SciCover_Summary; mailto:scicover@example.com)",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        message = data.get("message", {})
        links = message.get("link", [])

        # Sort links: prefer XML (structured) over HTML, prefer text over PDF.
        xml_links = []
        html_links = []
        for link in links:
            ct = (link.get("content-type") or "").lower()
            link_url = link.get("URL", "")
            if not link_url:
                continue
            if "xml" in ct:
                xml_links.append(link_url)
            elif "html" in ct or "text" in ct:
                html_links.append(link_url)

        # Try XML links first (more structured, easier to extract text).
        for link_url in xml_links:
            text = _fetch_xml_fulltext(link_url)
            if text:
                logger.info(
                    "Got full text from Crossref XML link (%d chars): %s",
                    len(text), link_url,
                )
                return _truncate(text)

        # Try HTML links.
        for link_url in html_links:
            text = _fetch_generic_html(link_url)
            if text:
                logger.info(
                    "Got full text from Crossref HTML link (%d chars): %s",
                    len(text), link_url,
                )
                return _truncate(text)

    except requests.RequestException as exc:
        logger.debug("Crossref fulltext API failed for DOI %s: %s", doi, exc)
    except (ValueError, KeyError) as exc:
        logger.debug("Crossref fulltext parse error for DOI %s: %s", doi, exc)

    return None


def _fetch_xml_fulltext(url: str) -> Optional[str]:
    """Fetch and extract text from an XML full-text endpoint.

    Handles JATS XML (used by most STM publishers) and generic XML.
    """
    try:
        resp = requests.get(
            url, headers=_HEADERS, timeout=30, allow_redirects=True,
        )
        if resp.status_code != 200:
            return None

        ct = resp.headers.get("Content-Type", "")
        if "xml" not in ct.lower() and "text" not in ct.lower():
            return None

        soup = BeautifulSoup(resp.text, "lxml-xml")

        # JATS XML: body element contains the article text.
        body = soup.find("body")
        if body:
            # Remove references/back matter.
            for ref in body.select("ref-list, back, fn-group"):
                ref.decompose()
            text = body.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            if len(text) > 500:
                return text

        # Generic XML fallback.
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if len(text) > 1000:
            return text

    except Exception as exc:
        logger.debug("XML fulltext fetch failed for %s: %s", url, exc)

    return None


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
    # Use a cookie-based session: visit the article landing page first to
    # acquire cookies, then download the PDF with those cookies.  This
    # bypasses publisher anti-scraping that blocks direct PDF requests.
    pdf_urls_to_try = list(all_pdf_urls or [])
    if oa_pdf_url and oa_pdf_url not in pdf_urls_to_try:
        pdf_urls_to_try.append(oa_pdf_url)

    # Also try Unpaywall to discover additional PDF URLs (free API, covers
    # all DOIs including Elsevier/ScienceDirect which are hard to scrape).
    if doi:
        unpaywall_pdf = _fetch_unpaywall_pdf_url(doi)
        if unpaywall_pdf and unpaywall_pdf not in pdf_urls_to_try:
            pdf_urls_to_try.append(unpaywall_pdf)

    for pdf_url in pdf_urls_to_try:
        text = _extract_text_from_pdf(pdf_url, article_url=article_url)
        if text:
            return _truncate(text)

    # --- Strategy 5: Generic HTML scraper (any OA publisher page) ---
    if article_url:
        text = _fetch_generic_html(article_url)
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
    if "osf.io" in url:
        return _fetch_osf(url)
    if "socarxiv" in url.lower():
        return _fetch_osf(url)  # SocArXiv is hosted on OSF
    if "repec" in url.lower() or "econpapers" in url.lower():
        return _fetch_repec(url)
    if "nber.org" in url:
        return _fetch_nber(url)
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


def _fetch_osf(url: str) -> Optional[str]:
    """Fetch from OSF Preprints / SocArXiv.

    OSF preprints often have a landing page with a download link.
    We try to extract text from the linked PDF as a fallback.
    """
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    # OSF sometimes renders the abstract in a specific container.
    body = soup.select_one(
        ".preprint-content, .article-body, .preprint-abstract, "
        "[class*='abstract'], .manuscript-body"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 500:
            logger.info("Got OSF/SocArXiv text (%d chars)", len(text))
            return text

    # Try to find a PDF download link and extract text from it.
    pdf_link = soup.select_one(
        "a[href$='.pdf'], a[href*='/download'], "
        "a[data-analytics-name='Download']"
    )
    if pdf_link:
        pdf_href = pdf_link.get("href", "")
        if pdf_href and not pdf_href.startswith("http"):
            pdf_href = urljoin(url, pdf_href)
        if pdf_href:
            text = _extract_text_from_pdf(pdf_href)
            if text:
                logger.info("Got OSF/SocArXiv PDF text (%d chars)", len(text))
                return text

    return None


def _fetch_repec(url: str) -> Optional[str]:
    """Fetch from RePEc / EconPapers / IDEAS.

    RePEc aggregates economics working papers.  Landing pages usually
    link to a downloadable PDF hosted by the institution.
    """
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    # Look for abstract text on the page.
    abstract = soup.select_one(
        "#abstract-body, .abstract, [class*='abstract'], "
        "#abstract, .paper-abstract"
    )
    if abstract:
        text = _extract_text(abstract)
        if len(text) > 200:
            logger.info("Got RePEc abstract (%d chars)", len(text))
            return text

    # Try to find a PDF download link.
    pdf_link = soup.select_one("a[href$='.pdf']")
    if pdf_link:
        pdf_href = pdf_link.get("href", "")
        if pdf_href and not pdf_href.startswith("http"):
            pdf_href = urljoin(url, pdf_href)
        if pdf_href:
            text = _extract_text_from_pdf(pdf_href)
            if text:
                logger.info("Got RePEc PDF text (%d chars)", len(text))
                return text

    return None


def _fetch_nber(url: str) -> Optional[str]:
    """Fetch from NBER working papers."""
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(
        ".page-header + .container, .paper-content, "
        "#paper-body, .abstract"
    )
    if body:
        text = _extract_text(body)
        if len(text) > 300:
            logger.info("Got NBER text (%d chars)", len(text))
            return text

    return None


# ---------------------------------------------------------------------------
# Open-access publisher fetchers
# ---------------------------------------------------------------------------

def _try_open_access(url: str) -> Optional[str]:
    """Try to fetch full text from open-access publisher pages.

    First tries publisher-specific selectors, then falls back to a generic
    HTML scraper that works with any OA publisher page.
    """
    _fetchers = [
        ("sciencedirect.com", _fetch_sciencedirect),
        ("cambridge.org", _fetch_cambridge),
        ("nature.com", _fetch_nature),
        ("science.org", _fetch_science),
        ("sciencemag.org", _fetch_science),
        ("cell.com", _fetch_cell),
    ]
    for domain, fetcher in _fetchers:
        if domain in url:
            result = fetcher(url)
            if result:
                return result
            # Publisher-specific failed — try generic below.
            break

    # Generic fallback for any OA publisher page.
    return _fetch_generic_html(url)


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


def _fetch_unpaywall_pdf_url(doi: str) -> Optional[str]:
    """Query the Unpaywall API for a direct OA PDF URL.

    Unpaywall (https://unpaywall.org/) is a free API that provides OA PDF
    locations for any DOI.  Particularly useful for Elsevier/ScienceDirect
    articles where the HTML is JavaScript-rendered and impossible to scrape.

    Returns the PDF URL or ``None``.
    """
    if not doi:
        return None

    # Unpaywall requires an email in the query.
    api_url = f"https://api.unpaywall.org/v2/{doi}?email=scicover@example.com"
    try:
        resp = requests.get(api_url, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        best_oa = data.get("best_oa_location") or {}
        pdf_url = best_oa.get("url_for_pdf") or ""
        if pdf_url:
            logger.info("Unpaywall found PDF URL for DOI %s: %s", doi, pdf_url)
            return pdf_url

        # Try other OA locations.
        for loc in data.get("oa_locations", []):
            pdf_url = loc.get("url_for_pdf") or ""
            if pdf_url:
                logger.info("Unpaywall found PDF URL for DOI %s: %s", doi, pdf_url)
                return pdf_url

    except Exception as exc:
        logger.debug("Unpaywall API failed for DOI %s: %s", doi, exc)

    return None


# ---------------------------------------------------------------------------
# PDF text extraction (via PyMuPDF)
# ---------------------------------------------------------------------------

def _extract_text_from_pdf(
    pdf_url: str,
    *,
    article_url: str = "",
    timeout: int = 60,
) -> Optional[str]:
    """Download a PDF and extract the entire article text using PyMuPDF (fitz).

    Uses a cookie-based requests.Session: visits the article landing page
    first to acquire cookies / session tokens, then downloads the PDF with
    those cookies.  This mimics browser behaviour and bypasses many
    publisher anti-scraping mechanisms that block direct PDF requests.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.debug("PyMuPDF not installed — cannot extract text from PDF")
        return None

    # Build a session and warm it up by visiting the landing page first.
    session = _build_session(article_url)

    # Download the PDF.
    try:
        resp = session.get(
            pdf_url,
            timeout=timeout,
            stream=True,
            headers={
                "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
            },
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
# Generic HTML full-text scraper
# ---------------------------------------------------------------------------

def _fetch_generic_html(url: str) -> Optional[str]:
    """Generic fallback: fetch any OA article page and extract body text.

    Uses a cascade of CSS selectors ordered from most to least specific.
    Works with most publisher sites that serve OA articles as full HTML.
    """
    html = _http_get(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")

    # Remove noise elements first.
    for tag in soup.select(
        "script, style, nav, header, footer, aside, "
        ".references, .ref-list, .bibliography, .supplementary, "
        ".article-metrics, .related-articles, .social-sharing, "
        "#cookie-banner, .cookie-notice, .modal, .popup, "
        ".sidebar, .nav, .menu, .breadcrumb, .pagination"
    ):
        tag.decompose()

    # Selectors ordered from most specific to most generic.
    _SELECTORS = [
        # Publisher article bodies
        "div.c-article-body",             # Nature / Springer
        ".article__body",                 # Science.org
        ".article-body",                  # Cell Press
        "#body",                          # ScienceDirect
        ".Body",                          # ScienceDirect alt
        "#bodymatter",                    # Science.org alt
        ".hlFld-Fulltext",                # Taylor & Francis, Wiley
        ".NLM_sec_level_1",              # various OA journals
        ".article-content",              # SAGE, misc
        ".article-full-text",            # generic
        ".fulltext",                     # generic
        ".paper-content",               # generic
        # Semantic elements
        "article",
        "[role='main']",
        "main",
        "#main-content",
        "#maincontent",
        "#content",
        ".content",
    ]

    for selector in _SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = _extract_text(el)
            if len(text) > 1000:
                logger.info(
                    "Got generic HTML full text (%d chars, selector=%s) from %s",
                    len(text), selector, url,
                )
                return text

    # Last resort: try the whole <body>.
    body = soup.find("body")
    if body:
        text = _extract_text(body)
        if len(text) > 2000:
            logger.info(
                "Got generic HTML full text from <body> (%d chars) from %s",
                len(text), url,
            )
            return text

    logger.debug("Generic HTML scraper found no usable text from %s", url)
    return None


# ---------------------------------------------------------------------------
# Cookie-based session builder
# ---------------------------------------------------------------------------

def _build_session(article_url: str = "") -> requests.Session:
    """Create a requests.Session pre-warmed with cookies from the article page.

    Visiting the landing page first mimics browser behaviour: the publisher
    sets session cookies, which then allow the PDF download to succeed.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)

    if article_url:
        try:
            logger.debug("Warming session by visiting %s", article_url)
            resp = session.get(
                article_url,
                timeout=30,
                allow_redirects=True,
            )
            logger.debug(
                "Session warm-up: status=%d, cookies=%d",
                resp.status_code,
                len(session.cookies),
            )
        except requests.RequestException as exc:
            logger.debug("Session warm-up failed (continuing anyway): %s", exc)

    return session


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
