"""
scraper — Journal article fetchers for SciCover.

Primary approach: OpenAlex API (``OpenAlexFetcher``).
Legacy web scrapers are retained for backward compatibility but are no
longer used by the default pipeline.
"""

from .openalex_fetcher import OpenAlexFetcher, JOURNAL_REGISTRY, JOURNAL_ALIASES

# Legacy web scrapers — kept for backward compatibility.
from .science_scraper import ScienceScraper
from .nature_scraper import NatureScraper
from .cell_scraper import CellScraper
from .polgeog_scraper import PolGeogScraper
from .intorg_scraper import IntOrgScraper
from .asr_scraper import ASRScraper

ALL_SCRAPERS = [
    ScienceScraper,
    NatureScraper,
    CellScraper,
    PolGeogScraper,
    IntOrgScraper,
    ASRScraper,
]

__all__ = [
    "OpenAlexFetcher",
    "JOURNAL_REGISTRY",
    "JOURNAL_ALIASES",
    "ScienceScraper",
    "NatureScraper",
    "CellScraper",
    "PolGeogScraper",
    "IntOrgScraper",
    "ASRScraper",
    "ALL_SCRAPERS",
]
