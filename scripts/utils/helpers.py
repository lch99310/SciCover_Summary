"""
utils.helpers — Small standalone utility functions for SciCover.

These are pure helpers with no business logic — file I/O, ID generation,
image downloading, etc.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def generate_article_id(journal: str, date: str) -> str:
    """Generate a stable, filesystem-safe identifier for an article.

    The ID is built as ``<journal_slug>-<date>`` where *journal_slug* is the
    lower-cased journal name with non-alphanumeric characters replaced by
    hyphens, and *date* is the ISO-8601 date string (``YYYY-MM-DD``).

    Examples
    --------
    >>> generate_article_id("Science", "2025-06-20")
    'science-2025-06-20'
    >>> generate_article_id("Nature", "2025-06-19")
    'nature-2025-06-19'
    """
    slug = re.sub(r"[^a-z0-9]+", "-", journal.lower()).strip("-")
    safe_date = re.sub(r"[^0-9-]", "", date)
    return f"{slug}-{safe_date}"


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def ensure_dir(path: str | Path) -> Path:
    """Create *path* (and parents) if it does not exist; return as ``Path``.

    This is a thin wrapper around ``Path.mkdir(parents=True, exist_ok=True)``
    for readability.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Image downloading
# ---------------------------------------------------------------------------

def download_image(url: str, output_path: str | Path, *, timeout: int = 30) -> Optional[Path]:
    """Download an image from *url* and save it to *output_path*.

    Parameters
    ----------
    url:
        Absolute URL to the image file.
    output_path:
        Local filesystem path where the image will be saved.  Parent
        directories are created automatically.
    timeout:
        HTTP request timeout in seconds.

    Returns
    -------
    pathlib.Path
        The resolved output path on success, or ``None`` on failure.
    """
    out = Path(output_path)
    ensure_dir(out.parent)

    try:
        logger.info("Downloading image: %s", url)
        resp = requests.get(
            url,
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

        with open(out, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)

        size_kb = out.stat().st_size / 1024
        logger.info("Saved image (%0.1f KB) to %s", size_kb, out)
        return out

    except requests.RequestException as exc:
        logger.error("Image download failed for %s: %s", url, exc)
        return None
    except OSError as exc:
        logger.error("Could not write image to %s: %s", out, exc)
        return None


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------

def truncate(text: str, max_len: int = 300) -> str:
    """Truncate *text* to *max_len* characters, adding an ellipsis if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"
