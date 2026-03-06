"""
scraper.elsevier_api — Elsevier ScienceDirect Text Mining API client.

Uses the Elsevier Content API to retrieve full text and figure images
for Open Access articles from Elsevier journals (Cell, Political Geography).

API reference: https://dev.elsevier.com/documentation/FullTextRetrievalAPI.wadl

Only used for OA articles — the API returns full text for entitled or OA
content, and an error otherwise.

Requires an API key registered at https://dev.elsevier.com/apikey/manage
(passed via the ELSEVIER_API_KEY environment variable).
"""

from __future__ import annotations

import io
import logging
import os
import re
from typing import List, Optional
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_API_BASE = "https://api.elsevier.com/content/article"


def get_api_key() -> str:
    """Return the Elsevier API key from the environment."""
    return os.environ.get("ELSEVIER_API_KEY", "")


# ---------------------------------------------------------------------------
# Full-text retrieval
# ---------------------------------------------------------------------------

def fetch_fulltext(doi: str, api_key: str = "") -> Optional[str]:
    """Retrieve the full plain-text body of an article via the Elsevier API.

    Parameters
    ----------
    doi : str
        The article DOI (e.g. ``10.1016/j.cell.2025.12.029``).
    api_key : str
        Elsevier API key. Falls back to ``ELSEVIER_API_KEY`` env var.

    Returns
    -------
    str or None
        Plain text of the article, or ``None`` if retrieval failed
        (e.g. article is not entitled / not OA).
    """
    key = api_key or get_api_key()
    if not key:
        logger.debug("No Elsevier API key — skipping Elsevier fulltext")
        return None

    url = f"{_API_BASE}/doi/{doi}"
    try:
        resp = requests.get(
            url,
            headers={
                "X-ELS-APIKey": key,
                "Accept": "text/plain",
            },
            timeout=30,
        )
        if resp.status_code == 200:
            text = resp.text.strip()
            if len(text) > 500:
                logger.info(
                    "Elsevier API: got full text for DOI %s (%d chars)",
                    doi, len(text),
                )
                return text
            logger.debug("Elsevier API: text too short for DOI %s (%d chars)", doi, len(text))
            return None

        if resp.status_code in (401, 403):
            logger.info(
                "Elsevier API: not entitled to DOI %s (HTTP %d)",
                doi, resp.status_code,
            )
        elif resp.status_code == 404:
            logger.debug("Elsevier API: DOI not found: %s", doi)
        else:
            logger.warning(
                "Elsevier API: unexpected HTTP %d for DOI %s",
                resp.status_code, doi,
            )
        return None

    except requests.RequestException as exc:
        logger.warning("Elsevier API request failed for DOI %s: %s", doi, exc)
        return None


# ---------------------------------------------------------------------------
# Figure image extraction from XML
# ---------------------------------------------------------------------------

def fetch_figures(doi: str, api_key: str = "") -> List[str]:
    """Retrieve figure image URLs from the article's full XML.

    The Elsevier XML uses ``<ce:figure>`` elements with ``<ce:link>``
    references.  The actual images are served from the Elsevier CDN at
    ``https://ars.els-cdn.com/content/image/``.

    Returns a list of image URLs (may be empty).
    """
    key = api_key or get_api_key()
    if not key:
        return []

    url = f"{_API_BASE}/doi/{doi}"
    try:
        resp = requests.get(
            url,
            headers={
                "X-ELS-APIKey": key,
                "Accept": "text/xml",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.debug(
                "Elsevier API XML: HTTP %d for DOI %s",
                resp.status_code, doi,
            )
            return []

        return _extract_figure_urls_from_xml(resp.text, doi)

    except requests.RequestException as exc:
        logger.debug("Elsevier API XML request failed: %s", exc)
        return []


def fetch_first_figure(
    doi: str,
    output_path: str | Path,
    api_key: str = "",
) -> Optional[Path]:
    """Download the first large figure from the article and save as JPEG.

    Returns the output path on success, or ``None`` if no figure was found.
    """
    figure_urls = fetch_figures(doi, api_key=api_key)
    if not figure_urls:
        return None

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    for fig_url in figure_urls:
        try:
            resp = requests.get(fig_url, timeout=30, stream=True)
            if resp.status_code != 200:
                continue

            ct = resp.headers.get("Content-Type", "")
            if "image" not in ct.lower():
                continue

            data = resp.content
            if len(data) < 5000:
                continue

            # Convert to JPEG via PIL for consistent output.
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(data))
                if img.width < 200 or img.height < 200:
                    continue
                img = img.convert("RGB")
                img.save(str(out), "JPEG", quality=85)
                logger.info(
                    "Elsevier API: saved figure (%dx%d) from %s",
                    img.width, img.height, fig_url,
                )
                return out
            except ImportError:
                # No PIL — save raw if JPEG.
                if "jpeg" in ct.lower() or "jpg" in ct.lower():
                    out.write_bytes(data)
                    return out
            except Exception as exc:
                logger.debug("Figure conversion failed: %s", exc)
                continue

        except requests.RequestException as exc:
            logger.debug("Figure download failed: %s", exc)
            continue

    return None


def _extract_figure_urls_from_xml(xml_text: str, doi: str) -> List[str]:
    """Parse Elsevier XML and extract figure image URLs.

    Elsevier XML figures look like:
        <ce:figure id="fig1">
            <ce:link locator="gr1" id="lnk1"/>
            <ce:caption>...</ce:caption>
        </ce:figure>

    The actual images are at:
        https://ars.els-cdn.com/content/image/1-s2.0-{PII}-{locator}.jpg

    Or via the Object Retrieval API:
        https://api.elsevier.com/content/object/eid/1-s2.0-{PII}
    """
    urls: List[str] = []

    try:
        soup = BeautifulSoup(xml_text, "lxml-xml")
    except Exception:
        soup = BeautifulSoup(xml_text, "lxml")

    # Extract the PII from the XML metadata.
    pii = ""
    pii_el = soup.find("pii")
    if pii_el:
        pii = pii_el.get_text(strip=True).replace("-", "").replace("(", "").replace(")", "")

    if not pii:
        # Try to extract PII from xocs:pii-unformatted
        pii_el = soup.find("pii-unformatted") or soup.find(re.compile(r"pii", re.I))
        if pii_el:
            pii = pii_el.get_text(strip=True).replace("-", "").replace("(", "").replace(")", "")

    if not pii:
        logger.debug("Could not extract PII from Elsevier XML for DOI %s", doi)
        return []

    # Find all <ce:figure> or <figure> elements with link locators.
    figures = soup.find_all(re.compile(r"figure", re.I))
    for fig in figures:
        # Look for <ce:link locator="gr1"/> or <link locator="..."/>
        links = fig.find_all(re.compile(r"link", re.I))
        for link in links:
            locator = link.get("locator") or ""
            if locator:
                # Construct CDN URL.
                cdn_url = (
                    f"https://ars.els-cdn.com/content/image/"
                    f"1-s2.0-{pii}-{locator}.jpg"
                )
                urls.append(cdn_url)

    # Also look for <ce:e-component> with <ce:link> that reference graphics.
    for ecomp in soup.find_all(re.compile(r"e-component", re.I)):
        comp_id = ecomp.get("id", "")
        if comp_id and any(
            prefix in comp_id.lower()
            for prefix in ("gr", "fig", "ga", "fx")
        ):
            cdn_url = (
                f"https://ars.els-cdn.com/content/image/"
                f"1-s2.0-{pii}-{comp_id}.jpg"
            )
            if cdn_url not in urls:
                urls.append(cdn_url)

    if urls:
        logger.info(
            "Elsevier API: found %d figure URLs for DOI %s",
            len(urls), doi,
        )

    return urls
