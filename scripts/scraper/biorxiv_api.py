"""
scraper.biorxiv_api — bioRxiv API client for preprint discovery.

Uses the bioRxiv "pubs" endpoint to find bioRxiv preprints that correspond
to published journal articles (identified by DOI).

API reference: https://api.biorxiv.org

Key endpoint:
    GET https://api.biorxiv.org/pubs/biorxiv/{DOI}

Returns a JSON response with a ``collection`` array containing preprint
metadata (bioRxiv DOI, preprint date, preprint title, etc.) for all
bioRxiv preprints that were later published as the given DOI.

This is particularly useful for Cell Press articles, which almost always
have a bioRxiv preprint version that provides:
  - Free full-text HTML at ``https://www.biorxiv.org/content/{biorxiv_doi}.full``
  - og:image cover figures for thumbnail extraction
  - PDF at ``https://www.biorxiv.org/content/{biorxiv_doi}.full.pdf``
"""

from __future__ import annotations

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.biorxiv.org"


def find_preprint(published_doi: str) -> Optional[str]:
    """Look up a bioRxiv preprint URL for a published journal article DOI.

    Parameters
    ----------
    published_doi : str
        The DOI of the published article (e.g. ``10.1016/j.cell.2025.12.029``).

    Returns
    -------
    str or None
        The bioRxiv landing page URL (e.g.
        ``https://www.biorxiv.org/content/10.1101/2025.01.15.633256v1``),
        or ``None`` if no preprint was found.
    """
    if not published_doi:
        return None

    url = f"{_API_BASE}/pubs/biorxiv/{published_doi}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            logger.debug(
                "bioRxiv pubs API: HTTP %d for DOI %s",
                resp.status_code, published_doi,
            )
            return None

        data = resp.json()
        collection = data.get("collection", [])
        if not collection:
            logger.debug("bioRxiv pubs API: no preprint found for DOI %s", published_doi)
            return None

        # Use the first (usually most recent version) entry.
        entry = collection[0]
        biorxiv_doi = entry.get("preprint_doi", "")
        if not biorxiv_doi:
            return None

        preprint_url = f"https://www.biorxiv.org/content/{biorxiv_doi}"

        logger.info(
            "bioRxiv pubs API: found preprint for DOI %s → %s",
            published_doi, preprint_url,
        )
        return preprint_url

    except requests.RequestException as exc:
        logger.debug("bioRxiv pubs API request failed for DOI %s: %s", published_doi, exc)
        return None
    except (ValueError, KeyError) as exc:
        logger.debug("bioRxiv pubs API parse error for DOI %s: %s", published_doi, exc)
        return None


def get_preprint_pdf_url(preprint_url: str) -> str:
    """Construct the PDF URL for a bioRxiv preprint.

    Parameters
    ----------
    preprint_url : str
        bioRxiv landing page (e.g. ``https://www.biorxiv.org/content/10.1101/2025.01.15.633256v1``).

    Returns
    -------
    str
        Direct PDF URL (e.g. ``...633256v1.full.pdf``).
    """
    return preprint_url.rstrip("/") + ".full.pdf"


def get_preprint_fulltext_url(preprint_url: str) -> str:
    """Construct the full-text HTML URL for a bioRxiv preprint.

    Parameters
    ----------
    preprint_url : str
        bioRxiv landing page URL.

    Returns
    -------
    str
        Full-text HTML URL (e.g. ``...633256v1.full``).
    """
    return preprint_url.rstrip("/") + ".full"
