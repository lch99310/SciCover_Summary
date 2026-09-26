"""
scraper.crossref_dates — Recover precise publication dates from Crossref.

Some publishers deposit *year-only* publication dates.  OpenAlex normalises
those to ``YYYY-01-01``, which makes every article in a volume look as if it
appeared on 1 January.  Cambridge University Press does this for
*International Organization*: volume 80 issues 1, 2 and 3 all carry
``2026-01-01`` in OpenAlex.

That breaks two things downstream:

* recency filtering — a day-level cutoff discards the whole journal;
* sorting — ``data/index.json`` is ordered by ``date``, so the affected
  articles sink to the bottom of the archive regardless of when they
  actually came out.

Crossref is the upstream source of that metadata and often holds a more
precise date than the one OpenAlex ends up exposing, because a work can
carry several dates at different precisions (``published-print``,
``published-online``, ``issued``).  This module reads them all and returns
the most useful one.

Everything here degrades safely: if Crossref is unreachable, returns
nothing usable, or only confirms the year we already had, the caller keeps
the original OpenAlex date.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests

logger = logging.getLogger(__name__)

API_URL = "https://api.crossref.org/works"

_USER_AGENT = (
    "SciCover/1.0 (https://github.com/lch99310/SciCover_Summary; "
    "mailto:scicover@example.com)"
)

# Which Crossref date fields to consult, in order of preference.
#
# ``published-print`` and ``issued`` describe the ISSUE the article belongs
# to, which is what a reader comparing the site against a journal's issue
# page expects to see.  ``published-online`` is consulted last: for a
# journal with an online-first workflow it can precede the issue by many
# months, so it is a fallback rather than the primary answer.
_DATE_FIELDS: Sequence[str] = (
    "published-print",
    "issued",
    "published",
    "published-online",
)

# Crossref caps `rows`; keep batches well inside it.
_BATCH_SIZE = 40


def _date_from_parts(parts: Any) -> Optional[str]:
    """Convert a Crossref ``date-parts`` value to ``YYYY-MM-DD``.

    Crossref encodes dates as ``{"date-parts": [[2026, 8, 14]]}`` with
    trailing components omitted when unknown.  Precision therefore varies:

    * ``[[2026, 8, 14]]`` -> ``"2026-08-14"`` (day precision)
    * ``[[2026, 8]]``     -> ``"2026-08-01"`` (month precision; the 1st is
      used as a representative day, which still sorts into the right month)
    * ``[[2026]]``        -> ``None`` (year only — no better than the
      ``YYYY-01-01`` we are trying to replace)

    Returns ``None`` for anything unusable rather than raising, since this
    runs against third-party data.
    """
    if not isinstance(parts, (list, tuple)) or not parts:
        return None
    first = parts[0]
    if not isinstance(first, (list, tuple)) or not first:
        return None

    nums: List[int] = []
    for component in first[:3]:
        if isinstance(component, bool) or not isinstance(component, int):
            return None
        nums.append(component)

    if not nums or not (1000 <= nums[0] <= 9999):
        return None
    if len(nums) < 2:
        # Year only — carries no more information than the OpenAlex date.
        return None

    year, month = nums[0], nums[1]
    if not 1 <= month <= 12:
        return None
    day = nums[2] if len(nums) > 2 else 1
    if not 1 <= day <= 31:
        return None

    return f"{year:04d}-{month:02d}-{day:02d}"


def best_date(message: Dict[str, Any]) -> Optional[str]:
    """Pick the most useful publication date from a Crossref work record.

    Walks :data:`_DATE_FIELDS` in order and returns the first date with at
    least month precision.  Returns ``None`` when every field is year-only
    or absent — meaning Crossref has nothing to add.
    """
    if not isinstance(message, dict):
        return None
    for field in _DATE_FIELDS:
        value = message.get(field)
        if not isinstance(value, dict):
            continue
        resolved = _date_from_parts(value.get("date-parts"))
        if resolved:
            return resolved
    return None


def _normalise_doi(doi: str) -> str:
    """Strip any URL prefix and lowercase a DOI for comparison."""
    doi = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.lower()


def resolve_dates(
    dois: Iterable[str],
    *,
    session: Optional[requests.Session] = None,
    timeout: int = 20,
) -> Dict[str, str]:
    """Look up precise publication dates for *dois* via Crossref.

    DOIs are queried in batches using Crossref's ``filter=doi:`` syntax, so
    a whole journal's candidate list costs one or two HTTP requests rather
    than one per article.

    Returns a mapping of lowercased DOI -> ``YYYY-MM-DD`` containing only
    the DOIs for which Crossref offered a date of at least month precision.
    DOIs that are missing, year-only, or that failed to fetch are simply
    absent from the result, so the caller falls back to its existing date.
    """
    wanted = [d for d in {_normalise_doi(x) for x in dois} if d]
    if not wanted:
        return {}

    http = session or requests.Session()
    resolved: Dict[str, str] = {}

    for start in range(0, len(wanted), _BATCH_SIZE):
        batch = wanted[start:start + _BATCH_SIZE]
        params = {
            "filter": ",".join(f"doi:{d}" for d in batch),
            "select": "DOI,published-print,published-online,issued,published",
            "rows": str(len(batch)),
        }
        try:
            resp = http.get(
                API_URL,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.warning(
                    "Crossref date lookup returned HTTP %s for %d DOIs — "
                    "keeping OpenAlex dates",
                    resp.status_code, len(batch),
                )
                continue
            items = resp.json().get("message", {}).get("items", [])
        except requests.RequestException as exc:
            logger.warning(
                "Crossref date lookup failed for %d DOIs (%s) — "
                "keeping OpenAlex dates", len(batch), exc,
            )
            continue
        except ValueError as exc:
            logger.warning("Crossref returned invalid JSON: %s", exc)
            continue

        for item in items:
            doi = _normalise_doi(item.get("DOI", ""))
            if not doi:
                continue
            date = best_date(item)
            if date:
                resolved[doi] = date

    logger.info(
        "Crossref date lookup: %d/%d DOIs gained a more precise date",
        len(resolved), len(wanted),
    )
    return resolved
