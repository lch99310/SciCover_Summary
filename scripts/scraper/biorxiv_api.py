"""
scraper.biorxiv_api — Preprint discovery for published journal articles.

Discovers preprints using multiple APIs (tried in order):
  1. bioRxiv / medRxiv "pubs" API — most reliable for life sciences.
  2. Crossref API — ``relation.is-preprint-of`` links; covers all fields.
  3. Semantic Scholar API — ``externalIds`` field; broad coverage.

Works for ANY published DOI across all journals (Science, Nature, Cell,
Political Geography, International Organization, ASR, etc.).

API references:
    https://api.biorxiv.org
    https://api.crossref.org/swagger-ui/index.html
    https://api.semanticscholar.org/api-docs/graph
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.biorxiv.org"

# Known preprint server domains that our fulltext fetcher can handle.
_KNOWN_PREPRINT_DOMAINS = (
    "arxiv.org", "biorxiv.org", "medrxiv.org", "chemrxiv.org",
    "ssrn.com", "socarxiv", "osf.io", "repec", "econpapers",
    "nber.org/papers",
)


def find_preprint(published_doi: str) -> Optional[str]:
    """Look up a preprint URL for a published DOI.

    Tries multiple discovery strategies in order:
      1. bioRxiv / medRxiv pubs API (fastest, most reliable for bio/med).
      2. Crossref relation links (broad coverage across all fields).
      3. Semantic Scholar externalIds (good for CS/physics/social sciences).

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

    # Strategy 1: bioRxiv / medRxiv pubs API.
    for server in ("biorxiv", "medrxiv"):
        result = _query_pubs_api(server, published_doi)
        if result:
            return result

    # Strategy 2: Crossref relation links.
    result = _query_crossref(published_doi)
    if result:
        return result

    # Strategy 3: Semantic Scholar.
    result = _query_semantic_scholar(published_doi)
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


def _query_crossref(published_doi: str) -> Optional[str]:
    """Query Crossref for preprint relations linked to *published_doi*.

    Crossref metadata often contains ``relation.is-preprint-of`` or
    ``relation.has-preprint`` entries that point to preprint DOIs on
    arXiv, bioRxiv, SSRN, etc.  This covers all academic fields.
    """
    url = f"https://api.crossref.org/works/{published_doi}"
    headers = {
        "User-Agent": "SciCover/1.0 (https://github.com/lch99310/SciCover_Summary; mailto:scicover@example.com)",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        message = data.get("message", {})
        relation = message.get("relation", {})

        # Check multiple relation types that link to preprints.
        for rel_key in ("has-preprint", "is-preprint-of", "is-identical-to",
                        "is-version-of", "has-version", "references"):
            entries = relation.get(rel_key, [])
            for entry in entries:
                preprint_id = entry.get("id", "")
                id_type = entry.get("id-type", "")

                preprint_url = _resolve_preprint_id(preprint_id, id_type)
                if preprint_url:
                    logger.info(
                        "Crossref %s: found preprint for DOI %s → %s",
                        rel_key, published_doi, preprint_url,
                    )
                    return preprint_url

    except requests.RequestException as exc:
        logger.debug("Crossref API failed for DOI %s: %s", published_doi, exc)
    except (ValueError, KeyError) as exc:
        logger.debug("Crossref API parse error for DOI %s: %s", published_doi, exc)

    return None


def _query_semantic_scholar(published_doi: str) -> Optional[str]:
    """Query Semantic Scholar for preprint versions of *published_doi*.

    Semantic Scholar tracks paper versions across arXiv, bioRxiv, medRxiv,
    and other preprint servers.  It has particularly good coverage for
    computer science, physics, and social sciences.
    """
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{published_doi}"
    params = {"fields": "externalIds,url"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return None

        data = resp.json()
        ext_ids = data.get("externalIds") or {}

        # Check for arXiv ID.
        arxiv_id = ext_ids.get("ArXiv")
        if arxiv_id:
            preprint_url = f"https://arxiv.org/abs/{arxiv_id}"
            logger.info(
                "Semantic Scholar: found arXiv preprint for DOI %s → %s",
                published_doi, preprint_url,
            )
            return preprint_url

    except requests.RequestException as exc:
        logger.debug("Semantic Scholar API failed for DOI %s: %s", published_doi, exc)
    except (ValueError, KeyError) as exc:
        logger.debug("Semantic Scholar parse error for DOI %s: %s", published_doi, exc)

    return None


def _resolve_preprint_id(preprint_id: str, id_type: str = "") -> Optional[str]:
    """Convert a preprint identifier (DOI or URL) to a usable landing page URL.

    Only returns URLs on known preprint servers that our fulltext fetcher
    can actually handle.
    """
    if not preprint_id:
        return None

    # If it's already a URL on a known preprint server, return directly.
    if preprint_id.startswith("http"):
        id_lower = preprint_id.lower()
        for domain in _KNOWN_PREPRINT_DOMAINS:
            if domain in id_lower:
                return preprint_id
        return None

    # If it's a DOI, resolve to a URL.
    if id_type == "doi" or preprint_id.startswith("10."):
        doi = preprint_id.replace("https://doi.org/", "").replace("http://doi.org/", "")
        doi_lower = doi.lower()

        # arXiv DOIs: 10.48550/arXiv.XXXX.XXXXX
        m = re.search(r"arxiv\.(\d{4}\.\d{4,5})", doi_lower)
        if m:
            return f"https://arxiv.org/abs/{m.group(1)}"

        # bioRxiv/medRxiv DOIs: 10.1101/YYYY.MM.DD.XXXXXX
        if doi_lower.startswith("10.1101/"):
            # Determine server from the DOI metadata if possible;
            # default to bioRxiv (larger corpus).
            return f"https://www.biorxiv.org/content/{doi}"

        # chemRxiv: 10.26434/chemrxiv-...
        if "chemrxiv" in doi_lower:
            return f"https://doi.org/{doi}"

        # SSRN: 10.2139/ssrn.XXXXXXX
        if doi_lower.startswith("10.2139/ssrn"):
            ssrn_id = doi.split(".")[-1]
            return f"https://papers.ssrn.com/sol3/papers.cfm?abstract_id={ssrn_id}"

        # OSF / SocArXiv: 10.31235/osf.io/XXXXX
        if "osf.io" in doi_lower:
            return f"https://doi.org/{doi}"

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
