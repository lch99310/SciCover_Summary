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
    doi: str = "",
    timeout: int = 60,
) -> Optional[Path]:
    """Try multiple PDF URLs, then HTML, returning the first successful thumbnail.

    Strategy:
      1. Try each PDF URL in order (cookie-based session for anti-scraping).
      2. If all PDFs fail, extract an image from the article HTML page
         (og:image, graphical abstract, figures).
      3. If article_url fails, try the DOI URL (``https://doi.org/...``)
         which may redirect to a different endpoint that allows access.
    """
    for url in pdf_urls:
        result = extract_thumbnail_from_pdf(
            url, output_path, article_url=article_url, timeout=timeout,
        )
        if result is not None:
            return result

    # Fallback: extract an image from the article HTML page.
    # Try article_url first, then DOI URL (DOI redirects may bypass blocks).
    html_urls_to_try = []
    if article_url:
        html_urls_to_try.append(article_url)
    if doi:
        doi_url = f"https://doi.org/{doi}" if not doi.startswith("http") else doi
        if doi_url not in html_urls_to_try:
            html_urls_to_try.append(doi_url)

    for html_url in html_urls_to_try:
        result = extract_image_from_html(html_url, output_path, timeout=timeout)
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

    # Write to a temp file, then extract figure with PyMuPDF.
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)

        # Step 2 — Open the PDF and try to extract the best embedded figure.
        doc = fitz.open(tmp_path)
        if doc.page_count == 0:
            logger.warning("PDF has zero pages: %s", pdf_url)
            doc.close()
            return None

        # Try to extract the largest embedded figure image directly.
        extracted = _extract_best_figure(doc, out)
        if extracted:
            doc.close()
            size_kb = out.stat().st_size / 1024
            logger.info(
                "PDF figure extracted (%0.1f KB) to %s", size_kb, out,
            )
            return out

        # Fallback: render the best page as a whole-page JPEG.
        best_page = _find_page_with_image(doc)
        page = doc[best_page]
        rect = page.rect
        zoom = TARGET_WIDTH / rect.width
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        pix.save(str(out), output="jpeg", jpg_quality=JPEG_QUALITY)
        doc.close()

        size_kb = out.stat().st_size / 1024
        logger.info(
            "PDF page rendered (%0.1f KB, %dx%d, page %d) to %s",
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


def _extract_best_figure(doc, output_path: Path) -> bool:
    """Extract the largest embedded figure image from the PDF.

    Instead of rendering a whole page (which includes text, headers, etc.),
    this extracts the actual image data of the biggest figure.  This gives
    a clean figure image suitable for use as a cover thumbnail.

    Scans the first ``_MAX_PAGES_TO_SCAN`` pages and picks the image with
    the largest pixel area (width × height).  Skips tiny images (logos, etc.)
    below ``_MIN_IMAGE_AREA``.

    Returns ``True`` if a figure was successfully extracted and saved.
    """
    best_xref = None
    best_area = 0
    pages_to_check = min(doc.page_count, _MAX_PAGES_TO_SCAN)

    for i in range(pages_to_check):
        try:
            page = doc[i]
            images = page.get_images(full=True)
            for img_info in images:
                # img_info: (xref, smask, width, height, bpc, colorspace, ...)
                xref = img_info[0]
                w, h = img_info[2], img_info[3]
                area = w * h
                if area >= _MIN_IMAGE_AREA and area > best_area:
                    best_area = area
                    best_xref = xref
        except Exception:
            continue

    if best_xref is None:
        logger.debug("No extractable figure found in PDF")
        return False

    try:
        img_data = doc.extract_image(best_xref)
        if not img_data or not img_data.get("image"):
            logger.debug("Failed to extract image data for xref %d", best_xref)
            return False

        raw_bytes = img_data["image"]
        ext = img_data.get("ext", "png")

        # Convert to JPEG via Pillow for consistent output format.
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(raw_bytes))
            # Resize if too large, maintaining aspect ratio.
            if img.width > TARGET_WIDTH:
                ratio = TARGET_WIDTH / img.width
                new_h = int(img.height * ratio)
                img = img.resize((TARGET_WIDTH, new_h), Image.LANCZOS)
            img = img.convert("RGB")
            img.save(str(output_path), "JPEG", quality=JPEG_QUALITY)
        except ImportError:
            # No PIL — if already JPEG, save directly; otherwise skip.
            if ext in ("jpeg", "jpg"):
                output_path.write_bytes(raw_bytes)
            else:
                logger.debug("No PIL for image conversion, ext=%s", ext)
                return False

        logger.debug(
            "Extracted figure: xref=%d, area=%d px, ext=%s",
            best_xref, best_area, ext,
        )
        return True

    except Exception as exc:
        logger.debug("Figure extraction failed: %s", exc)
        return False


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

    # Strategy 1: OpenGraph / Twitter meta tags (most reliable — works on
    # virtually every publisher page, even JS-rendered ones, because meta
    # tags are always in the initial HTML).
    img_url = _find_meta_image(soup, article_url)

    # Strategy 2: Look for graphical abstract / TOC image.
    if not img_url:
        img_url = _find_graphical_abstract(soup, article_url)

    # Strategy 3: Look for first large image in a <figure> tag.
    if not img_url:
        img_url = _find_figure_image(soup, article_url)

    # Strategy 4: Look for any large <img> in the article body.
    if not img_url:
        img_url = _find_large_img(soup, article_url)

    if not img_url:
        logger.debug("No suitable image found in HTML of %s", article_url)
        return None

    # Download the image.
    return _download_image(img_url, out, session, timeout=timeout)


def _find_meta_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Extract image URL from OpenGraph or Twitter Card meta tags.

    These are the most reliable source: every major publisher includes
    ``og:image`` in their HTML <head>, and it's always present in the
    initial HTML (no JavaScript rendering needed).
    """
    # Try og:image first, then twitter:image.
    for attr, key in [
        ("property", "og:image"),
        ("name", "twitter:image"),
        ("name", "twitter:image:src"),
    ]:
        tag = soup.find("meta", attrs={attr: key})
        if tag:
            content = tag.get("content", "")
            if content and not any(
                skip in content.lower()
                for skip in ("logo", "icon", "favicon", "placeholder", "default")
            ):
                logger.debug("Found meta image (%s): %s", key, content)
                return urljoin(base_url, content)
    return None


def _find_graphical_abstract(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Find a graphical abstract / TOC image on the page."""
    selectors = [
        # Cell Press: graphical abstracts live in section.graphic > div.figure-wrap
        "section.graphic .figure-wrap img",
        "section.graphic img",
        ".graphical-abstract img",
        "img.graphical-abstract",
        "img.toc-image",
        ".toc-image img",
        ".cover-image img",
        "[class*='graphical'] img",
        "[class*='toc-art'] img",
        "[id*='graphical'] img",
        "figure.graphical-abstract img",
        # Elsevier / ScienceDirect
        ".abstract-graphical img",
        ".ga_image img",
    ]
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            src = el.get("src") or el.get("data-src") or ""
            if src:
                logger.debug("Found graphical abstract (%s): %s", selector, src)
                return urljoin(base_url, src)
    return None


def _find_figure_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Find the first large image inside a <figure> or figure-wrap tag."""
    # Include Cell Press .figure-wrap containers alongside standard <figure>.
    for figure in soup.select("figure, .figure-wrap"):
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
