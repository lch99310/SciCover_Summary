"""
utils.pdf_thumbnail — Extract a thumbnail image from the first page of a PDF.

Uses PyMuPDF (``fitz``) to render the first page of an open-access PDF at a
resolution suitable for web thumbnails (~800px wide).  The output is saved as
a JPEG file.

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
    """Download a PDF from *pdf_url* and save the first page as a JPEG thumbnail.

    Parameters
    ----------
    pdf_url:
        Direct URL to the PDF file.
    output_path:
        Where to save the resulting JPEG image.  Parent directories are
        created automatically.
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
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            },
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
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            for chunk in resp.iter_content(chunk_size=8192):
                tmp.write(chunk)

        # Step 2 — Open the PDF and render the first page.
        doc = fitz.open(tmp_path)
        if doc.page_count == 0:
            logger.warning("PDF has zero pages: %s", pdf_url)
            doc.close()
            return None

        page = doc[0]
        # Calculate zoom factor to hit TARGET_WIDTH.
        rect = page.rect
        zoom = TARGET_WIDTH / rect.width
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Step 3 — Save as JPEG.
        pix.save(str(out), output="jpeg", jpg_quality=JPEG_QUALITY)
        doc.close()

        size_kb = out.stat().st_size / 1024
        logger.info(
            "PDF thumbnail saved (%0.1f KB, %dx%d) to %s",
            size_kb, pix.width, pix.height, out,
        )
        return out

    except Exception as exc:
        logger.warning("PDF thumbnail extraction failed: %s", exc)
        return None
    finally:
        # Clean up temp file.
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
