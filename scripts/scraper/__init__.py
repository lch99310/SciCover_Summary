"""
scraper — Journal cover-page scrapers for SciCover.

Re-exports every concrete scraper so callers can simply write:

    from scraper import ScienceScraper, NatureScraper, CellScraper
"""

from scraper.science_scraper import ScienceScraper
from scraper.nature_scraper import NatureScraper
from scraper.cell_scraper import CellScraper

ALL_SCRAPERS = [ScienceScraper, NatureScraper, CellScraper]

__all__ = [
    "ScienceScraper",
    "NatureScraper",
    "CellScraper",
    "ALL_SCRAPERS",
]
