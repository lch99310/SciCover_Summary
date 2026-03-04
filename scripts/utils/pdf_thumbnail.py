"""
utils.pdf_thumbnail — Extract a thumbnail image from a PDF page with a figure.

Uses PyMuPDF (``fitz``) to find the first page that contains a meaningful
image (embedded figure, photo, etc.) and renders it as a JPEG.  If no page
has an image, falls back to the first page.

If the PDF cannot be downloaded or parsed, the function returns ``None``
gracefully so the pipeline can continue without a thumbnail.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Target width for the rendered thumbnail (pixels).
TARGET_WIDTH = 800
JPEG_QUALITY = 85

# Minimum image area (pixels) to count as a "meaningful" figure.
# Tiny images (icons, logos, decorations) are ignored.
_MIN_IMAGE_AREA = 40_000  # ~200×200

# How many pages to scan for a figure before giving up.
_MAX_PAGES_TO_SCAN = 8

# Shared headers that mimic a real browser.
_PDF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://scholar.google.com/",
}


def extract_thumbnail_from_urls(
    pdf_urls: list[str],
    output_path: str | Path,
    *,
    timeout: int = 60,
) -> Optional[Path]:
    """Try multiple PDF URLs in order, returning the first successful thumbnail.

    Repository copies (PubMed Central, Europe PMC, etc.) are typically more
    accessible than publisher PDFs, so callers should order *pdf_urls* with
    the most reliable sources first.
    """
    for url in pdf_urls:
        result = extract_thumbnail_from_pdf(url, output_path, timeout=timeout)
        if result is not None:
            return result
    return None


def extract_thumbnail_from_pdf(
    pdf_url: str,
    output_path: str | Path,
    *,
    timeout: int = 60,
) -> Optional[Path]:
    """Download a PDF from *pdf_url* and save a page with a figure as JPEG.

    Scans the first few pages looking for one that contains a meaningful
    embedded image (figure, chart, photo).  If none is found, falls back
    to the first page.

    Parameters
    ----------
    pdf_url:
        Direct URL to the PDF file.
    output_path:
        Where to save the resulting JPEG image.
    timeout:
        HTTP download timeout in seconds.

    Returns
    -------
    pathlib.Path | None
        The output path on success, or ``None`` if the PDF could not be
        downloaded, parsed, or rendered.
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

    # Step 1 — Download the PDF to a temporary file.
    try:
        logger.info("Downloading PDF for thumbnail: %s", pdf_url)
        resp = requests.get(
            pdf_url,
            timeout=timeout,
            stream=True,
            headers=_PDF_HEADERS,
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
