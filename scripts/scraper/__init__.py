"""
scraper — Journal cover-page scrapers for SciCover.

Re-exports every concrete scraper so callers can simply write:

    from scraper import ScienceScraper, NatureScraper, CellScraper
"""

# Natural sciences
from .science_scraper import ScienceScraper
from .nature_scraper import NatureScraper
from .cell_scraper import CellScraper

# Social sciences
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
    "ScienceScraper",
    "NatureScraper",
    "CellScraper",
    "PolGeogScraper",
    "IntOrgScraper",
    "ASRScraper",
    "ALL_SCRAPERS",
]
