"""
scraper.biorxiv_api — bioRxiv / medRxiv API client for preprint discovery.

Uses the bioRxiv "pubs" endpoint to find preprints that correspond to
published journal articles (identified by DOI).

API reference: https://api.biorxiv.org

Key endpoints:
    GET https://api.biorxiv.org/pubs/biorxiv/{DOI}
    GET https://api.biorxiv.org/pubs/medrxiv/{DOI}

Returns a JSON response with a ``collection`` array containing preprint
metadata (preprint DOI, date, title, etc.) for all preprints that were
later published as the given DOI.

Works for ANY published DOI — not just Elsevier.  Many Science, Nature,
Cell, and other journal articles have bioRxiv or medRxiv preprints.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.biorxiv.org"


def find_preprint(published_doi: str) -> Optional[str]:
    """Look up a bioRxiv or medRxiv preprint URL for a published DOI.

    Queries both bioRxiv and medRxiv pubs APIs.  Returns the first match.

    Parameters
    ----------
    published_doi : str
        The DOI of the published article (e.g. ``10.1126/science.adx1234``).

    Returns
    -------
    str or None
        The preprint landing page URL, or ``None`` if no preprint was found.
    """
    if not published_doi:
        return None

    # Try bioRxiv first (larger corpus), then medRxiv.
    for server in ("biorxiv", "medrxiv"):
        result = _query_pubs_api(server, published_doi)
        if result:
            return result

    return None


def _query_pubs_api(server: str, published_doi: str) -> Optional[str]:
    """Query a single pubs endpoint (biorxiv or medrxiv)."""
    url = f"{_API_BASE}/pubs/{server}/{published_doi}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        collection = data.get("collection", [])
        if not collection:
            return None

        entry = collection[0]
        preprint_doi = entry.get("preprint_doi", "")
        if not preprint_doi:
            return None

        base = "www.biorxiv.org" if server == "biorxiv" else "www.medrxiv.org"
        preprint_url = f"https://{base}/content/{preprint_doi}"

        logger.info(
            "%s pubs API: found preprint for DOI %s → %s",
            server, published_doi, preprint_url,
        )
        return preprint_url

    except requests.RequestException as exc:
        logger.debug("%s pubs API failed for DOI %s: %s", server, published_doi, exc)
        return None
    except (ValueError, KeyError) as exc:
        logger.debug("%s pubs API parse error for DOI %s: %s", server, published_doi, exc)
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
