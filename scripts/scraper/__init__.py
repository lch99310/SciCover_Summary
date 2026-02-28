"""
scraper — Journal cover-page scrapers for SciCover.

Re-exports every concrete scraper so callers can simply write:

    from scraper import ScienceScraper, NatureScraper, CellScraper
"""

from .science_scraper import ScienceScraper
from .nature_scraper import NatureScraper
from .cell_scraper import CellScraper

ALL_SCRAPERS = [ScienceScraper, NatureScraper, CellScraper]

__all__ = [
    "ScienceScraper",
    "NatureScraper",
    "CellScraper",
    "ALL_SCRAPERS",
]
