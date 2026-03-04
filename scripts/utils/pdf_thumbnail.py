"""
utils.pdf_thumbnail — Extract a thumbnail image from a PDF or article HTML.

Strategy (tried in order):
  1. Download the PDF (using a cookie-based session) and render the first
     page that contains a meaningful figure as a JPEG thumbnail.
  2. If all PDF URLs fail, fetch the article HTML page and download the
     first large ``<img>`` (typically a cover figure / graphical abstract).

If neither approach works, the function returns ``None`` gracefully so the
pipeline can continue without a thumbnail.
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Target width for the rendered thumbnail (pixels).
TARGET_WIDTH = 800
JPEG_QUALITY = 85

# Minimum image area (pixels) to count as a "meaningful" figure.
# Tiny images (icons, logos, decorations) are ignored.
_MIN_IMAGE_AREA = 40_000  # ~200×200

# How many pages to scan for a figure before giving up.
_MAX_PAGES_TO_SCAN = 8

# Minimum pixel dimensions for an HTML image to be considered a figure.
_MIN_HTML_IMG_WIDTH = 300
_MIN_HTML_IMG_HEIGHT = 200

# Shared headers that mimic a real browser.
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

_PDF_HEADERS = {
    "User-Agent": _HEADERS["User-Agent"],
    "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://scholar.google.com/",
}


def extract_thumbnail_from_urls(
    pdf_urls: list[str],
    output_path: str | Path,
    *,
    article_url: str = "",
    timeout: int = 60,
) -> Optional[Path]:
    """Try multiple PDF URLs, then HTML, returning the first successful thumbnail.

    Strategy:
      1. Try each PDF URL in order (cookie-based session for anti-scraping).
      2. If all PDFs fail and *article_url* is provided, extract an image
         from the article HTML page (graphical abstract, cover figure, etc.).
    """
    for url in pdf_urls:
        result = extract_thumbnail_from_pdf(
            url, output_path, article_url=article_url, timeout=timeout,
        )
        if result is not None:
            return result

    # Fallback: extract an image from the article HTML page.
    if article_url:
        result = extract_image_from_html(article_url, output_path, timeout=timeout)
        if result is not None:
            return result

    return None


def extract_thumbnail_from_pdf(
    pdf_url: str,
    output_path: str | Path,
    *,
    article_url: str = "",
    timeout: int = 60,
) -> Optional[Path]:
    """Download a PDF from *pdf_url* and save a page with a figure as JPEG.

    Uses a cookie-based session: visits the article landing page first to
    acquire cookies, then downloads the PDF.  This bypasses publisher
    anti-scraping that blocks direct PDF requests.

    Scans the first few pages looking for one that contains a meaningful
    embedded image (figure, chart, photo).  If none is found, falls back
    to the first page.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning(
            "PyMuPDF (fitz) is not installed — cannot extract PDF thumbnails. "
            "Install with: pip install PyMuPDF"
        )
        return None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Build a session, pre-warmed with cookies from the article page.
    session = _build_session(article_url)

    # Step 1 — Download the PDF to a temporary file.
    try:
        logger.info("Downloading PDF for thumbnail: %s", pdf_url)
        resp = session.get(
            pdf_url,
            timeout=timeout,
            stream=True,
            headers={
                "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
            },
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Check content type — some URLs redirect to login pages.
        ct = resp.headers.get("Content-Type", "")
        if "pdf" not in ct.lower() and "octet-stream" not in ct.lower():
            logger.warning(
                "URL did not return a PDF (Content-Type: %s), skipping", ct,
            )
            return None

    except requests.RequestException as exc:
        logger.warning("PDF download failed: %s", exc)
        return None

    # Write to a temp file, then render with PyMuPDF.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)

        # Step 2 — Open the PDF and find the best page.
        doc = fitz.open(tmp_path)
        if doc.page_count == 0:
            logger.warning("PDF has zero pages: %s", pdf_url)
            doc.close()
            return None

        best_page = _find_page_with_image(doc)

        # Step 3 — Render and save as JPEG.
        page = doc[best_page]
        rect = page.rect
        zoom = TARGET_WIDTH / rect.width
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        pix.save(str(out), output="jpeg", jpg_quality=JPEG_QUALITY)
        doc.close()

        size_kb = out.stat().st_size / 1024
        logger.info(
            "PDF thumbnail saved (%0.1f KB, %dx%d, page %d) to %s",
            size_kb, pix.width, pix.height, best_page + 1, out,
        )
        return out

    except Exception as exc:
        logger.warning("PDF thumbnail extraction failed: %s", exc)
        return None
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _find_page_with_image(doc) -> int:
    """Return the index of the first page that contains a meaningful image.

    Scans up to ``_MAX_PAGES_TO_SCAN`` pages.  A "meaningful" image is one
    whose area exceeds ``_MIN_IMAGE_AREA`` pixels — this filters out tiny
    logos, decorations, and line-art borders.

    Falls back to page 0 if no page has a qualifying image.
    """
    pages_to_check = min(doc.page_count, _MAX_PAGES_TO_SCAN)

    for i in range(pages_to_check):
        try:
            page = doc[i]
            images = page.get_images(full=True)
            for img in images:
                # img tuple: (xref, smask, width, height, bpc, colorspace, ...)
                w, h = img[2], img[3]
                if w * h >= _MIN_IMAGE_AREA:
                    logger.debug(
                        "Found figure on page %d (%dx%d px)", i + 1, w, h,
                    )
                    return i
        except Exception:
            continue

    # No page with a large image found — default to first page.
    return 0


# ---------------------------------------------------------------------------
# HTML image extraction (fallback when PDF fails)
# ---------------------------------------------------------------------------

def extract_image_from_html(
    article_url: str,
    output_path: str | Path,
    *,
    timeout: int = 30,
) -> Optional[Path]:
    """Extract a figure image from the article HTML page.

    Looks for graphical abstracts, cover figures, or large inline images
    on the OA article page.  Downloads the first qualifying image and
    saves it as JPEG.

    Returns the output path on success, or ``None`` if no suitable image
    was found.
    """
    if not article_url:
        return None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        session = _build_session()  # fresh session (no pre-warm needed)
        resp = session.get(article_url, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if "html" not in ct.lower():
            logger.debug("Article URL did not return HTML (Content-Type: %s)", ct)
            return None
    except requests.RequestException as exc:
        logger.debug("Failed to fetch article HTML for image: %s", exc)
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # Strategy 1: Look for graphical abstract / TOC image.
    img_url = _find_graphical_abstract(soup, article_url)

    # Strategy 2: Look for first large image in a <figure> tag.
    if not img_url:
        img_url = _find_figure_image(soup, article_url)

    # Strategy 3: Look for any large <img> in the article body.
    if not img_url:
        img_url = _find_large_img(soup, article_url)

    if not img_url:
        logger.debug("No suitable image found in HTML of %s", article_url)
        return None

    # Download the image.
    return _download_image(img_url, out, session, timeout=timeout)


def _find_graphical_abstract(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Find a graphical abstract / TOC image on the page."""
    selectors = [
        "img.graphical-abstract",
        ".graphical-abstract img",
        "img.toc-image",
        ".toc-image img",
        ".cover-image img",
        "[class*='graphical'] img",
        "[class*='toc-art'] img",
        "[id*='graphical'] img",
        "figure.graphical-abstract img",
    ]
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            src = el.get("src") or el.get("data-src") or ""
            if src:
                return urljoin(base_url, src)
    return None


def _find_figure_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Find the first large image inside a <figure> tag."""
    for figure in soup.select("figure"):
        img = figure.select_one("img")
        if not img:
            continue
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        # Check explicit dimensions if available.
        w = _parse_dim(img.get("width", ""))
        h = _parse_dim(img.get("height", ""))
        if w and h:
            if w < _MIN_HTML_IMG_WIDTH or h < _MIN_HTML_IMG_HEIGHT:
                continue
        # Skip tiny icons / decorations by filename.
        src_lower = src.lower()
        if any(skip in src_lower for skip in (
            "icon", "logo", "avatar", "badge", "pixel", "tracking",
            "1x1", "spacer", "blank",
        )):
            continue
        return urljoin(base_url, src)
    return None


def _find_large_img(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Find any large <img> in the article body area."""
    # Look inside article body first, then whole page.
    body = soup.select_one(
        "article, main, [role='main'], .article-body, "
        ".c-article-body, .article__body, #body, #content"
    )
    container = body or soup

    for img in container.select("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        src_lower = src.lower()
        # Skip non-content images.
        if any(skip in src_lower for skip in (
            "icon", "logo", "avatar", "badge", "pixel", "tracking",
            "1x1", "spacer", "blank", "spinner", ".svg",
        )):
            continue
        # Check explicit dimensions.
        w = _parse_dim(img.get("width", ""))
        h = _parse_dim(img.get("height", ""))
        if w and h and (w < _MIN_HTML_IMG_WIDTH or h < _MIN_HTML_IMG_HEIGHT):
            continue
        # If no dimensions, accept it (likely a real figure).
        return urljoin(base_url, src)
    return None


def _parse_dim(val: str) -> int:
    """Parse a dimension attribute (width/height) to int, or 0."""
    if not val:
        return 0
    m = re.match(r"(\d+)", str(val))
    return int(m.group(1)) if m else 0


def _download_image(
    img_url: str,
    output_path: Path,
    session: requests.Session,
    *,
    timeout: int = 30,
) -> Optional[Path]:
    """Download an image URL and save as JPEG."""
    try:
        resp = session.get(img_url, timeout=timeout, stream=True)
        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if "image" not in ct.lower():
            logger.debug("Image URL did not return an image (Content-Type: %s)", ct)
            return None

        # Read image data.
        data = resp.content
        if len(data) < 5000:
            logger.debug("Image too small (%d bytes), skipping", len(data))
            return None

        # If it's already JPEG, save directly; otherwise convert via PIL.
        if "jpeg" in ct.lower() or "jpg" in ct.lower():
            output_path.write_bytes(data)
        else:
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(data))
                img = img.convert("RGB")
                img.save(str(output_path), "JPEG", quality=JPEG_QUALITY)
            except ImportError:
                # No PIL — save raw (might not be JPEG).
                output_path.write_bytes(data)
            except Exception as exc:
                logger.debug("Image conversion failed: %s", exc)
                return None

        size_kb = output_path.stat().st_size / 1024
        logger.info(
            "HTML image saved (%0.1f KB) from %s to %s",
            size_kb, img_url, output_path,
        )
        return output_path

    except requests.RequestException as exc:
        logger.debug("Image download failed: %s", exc)
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
