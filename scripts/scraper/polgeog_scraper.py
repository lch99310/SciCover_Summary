"""
scraper.polgeog_scraper — Scraper for *Political Geography* (Elsevier).

Target:  https://www.sciencedirect.com/journal/political-geography
Layout:  ScienceDirect journal pages show a table of contents with article
         listings.  Political Geography is a bimonthly journal (6 issues/year).
         Social-science journals typically have no cover image — the scraper
         extracts the lead article's graphical abstract if available.

Preprint repositories: SSRN, SocArXiv.

NOTE:  CSS selectors are based on the Elsevier / ScienceDirect layout
       observed as of early 2025.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BaseScraper, CoverArticleRaw

logger = logging.getLogger(__name__)


class PolGeogScraper(BaseScraper):
    """Scraper for *Political Geography* (Elsevier / ScienceDirect)."""

    JOURNAL_NAME = "Political Geography"
    BASE_URL = "https://www.sciencedirect.com"
    TOC_URL = f"{BASE_URL}/journal/political-geography/articles-in-press"

    # Publication frequency metadata (bimonthly, ~6 issues/year).
    PUBLICATION_FREQUENCY = "bimonthly"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_current_issue(self) -> Optional[CoverArticleRaw]:
        """Scrape the current/latest articles from *Political Geography*."""
        logger.info("Scraping current issue of %s ...", self.JOURNAL_NAME)
        # Try current issue first, fall back to articles-in-press
        current_url = f"{self.BASE_URL}/journal/political-geography/vol/latest"
        raw = self._scrape_toc_page(current_url)
        if raw is None:
            logger.info("Falling back to articles-in-press ...")
            raw = self._scrape_toc_page(self.TOC_URL)
        return raw

    def scrape_issue(self, volume: str, issue: str) -> Optional[CoverArticleRaw]:
        """Scrape a specific back-issue of *Political Geography*."""
        url = f"{self.BASE_URL}/journal/political-geography/vol/{volume}/issue/{issue}"
        logger.info("Scraping %s vol.%s issue %s ...", self.JOURNAL_NAME, volume, issue)
        return self._scrape_toc_page(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_toc_page(self, toc_url: str) -> Optional[CoverArticleRaw]:
        """Core scraping logic for a ScienceDirect TOC page."""
        soup = self._fetch_and_parse(toc_url)
        if soup is None:
            logger.error("Failed to fetch TOC page: %s", toc_url)
            return None

        raw = CoverArticleRaw(journal=self.JOURNAL_NAME)

        # --- Volume / issue / date ---
        self._extract_issue_metadata(soup, raw)

        # --- Lead article ---
        self._extract_lead_article(soup, raw)

        # --- Enrich from the article page ---
        if raw.article_url:
            self._enrich_from_article_page(raw)

        logger.info(
            "Scraped %s vol.%s #%s — %s",
            self.JOURNAL_NAME,
            raw.volume,
            raw.issue,
            raw.article_title or "(no title)",
        )
        return raw

    # --- Metadata --------------------------------------------------------

    def _extract_issue_metadata(self, soup, raw: CoverArticleRaw) -> None:
        """Pull volume, issue number, and date from the TOC page."""
        # ScienceDirect uses: <h2 class="js-issue-status">Volume 115, January 2026</h2>
        header = soup.select_one(
            ".js-issue-status, .issue-heading, "
            "h2[class*='issue'], .u-text-bold"
        )
        if header:
            text = self._clean_text(header.get_text())
            m_vol = re.search(r"Volume\s+(\d+)", text, re.IGNORECASE)
            if m_vol:
                raw.volume = m_vol.group(1)
            m_iss = re.search(r"Issue\s+(\d+)", text, re.IGNORECASE)
            if m_iss:
                raw.issue = m_iss.group(1)

            from dateutil.parser import parse as parse_date
            date_match = re.search(
                r"(\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})", text
            )
            if date_match:
                try:
                    raw.date = parse_date(date_match.group(1)).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    pass

        # Fallback: meta tags
        if not raw.date:
            meta = soup.select_one("meta[name='citation_publication_date']")
            if meta:
                raw.date = meta.get("content", "")[:10]

    # --- Lead article ----------------------------------------------------

    def _extract_lead_article(self, soup, raw: CoverArticleRaw) -> None:
        """Find the lead/featured article from the TOC.

        ScienceDirect lists articles as:
            <div class="result-list">
              <ol> <li class="js-article-list-item"> ... </li> </ol>
            </div>
        """
        # Look for the first research article
        first_article = soup.select_one(
            ".js-article-list-item a.result-list-title-link, "
            "a[class*='article-content-title'], "
            "dt.article-content a, "
            ".article-list-item a[href*='/science/article/']"
        )
        if not first_article:
            # Broader fallback
            first_article = soup.select_one("a[href*='/science/article/pii/']")

        if first_article:
            raw.article_url = self._abs_url(self.BASE_URL, first_article.get("href", ""))
            raw.article_title = self._clean_text(first_article.get_text())

        # Try to find graphical abstract as cover image
        ga_img = soup.select_one(
            "img[src*='graphical-abstract'], img[src*='fx1'], "
            "img[class*='graphical'], .graphical-abstract img"
        )
        if ga_img:
            src = ga_img.get("src") or ga_img.get("data-src") or ""
            raw.cover_image_url = self._abs_url(self.BASE_URL, src)

    # --- Article enrichment ----------------------------------------------

    def _enrich_from_article_page(self, raw: CoverArticleRaw) -> None:
        """Fetch the article page and pull abstract, authors, DOI, and
        graphical abstract if available."""
        soup = self._fetch_and_parse(raw.article_url)
        if soup is None:
            logger.warning("Could not fetch article page: %s", raw.article_url)
            return

        # --- Title ---
        title_tag = soup.select_one(
            "h1.article-title, span.title-text, "
            "meta[name='citation_title']"
        )
        if title_tag:
            if title_tag.name == "meta":
                raw.article_title = title_tag.get("content", "")
            else:
                raw.article_title = self._clean_text(title_tag.get_text())

        # --- Authors ---
        author_tags = soup.select(
            ".author-group a.author, .author span.text, "
            "meta[name='citation_author']"
        )
        if author_tags:
            authors = []
            for tag in author_tags:
                if tag.name == "meta":
                    authors.append(tag.get("content", ""))
                else:
                    name = self._clean_text(tag.get_text())
                    if name and name not in authors:
                        authors.append(name)
            raw.article_authors = authors

        # --- Abstract ---
        abstract_div = soup.select_one(
            ".abstract, #abstracts, [id*='abstract'], "
            ".Abstracts, div[class*='abstract']"
        )
        if abstract_div:
            raw.article_abstract = self._clean_text(abstract_div.get_text())

        # --- DOI ---
        meta_doi = soup.select_one("meta[name='citation_doi']")
        if meta_doi:
            raw.article_doi = meta_doi.get("content", "")
        if not raw.article_doi:
            doi_link = soup.select_one("a[href*='doi.org/10.']")
            if doi_link:
                m = re.search(r"(10\.\d{4,}/\S+)", doi_link.get("href", ""))
                if m:
                    raw.article_doi = m.group(1).rstrip(".")

        # --- Cover image (graphical abstract) ---
        if not raw.cover_image_url:
            ga_img = soup.select_one(
                "img[src*='fx1'], .graphical-abstract img, "
                "img[alt*='Graphical abstract'], "
                "figure img[src*='gr1']"
            )
            if ga_img:
                src = ga_img.get("src") or ga_img.get("data-src") or ""
                raw.cover_image_url = self._abs_url(self.BASE_URL, src)

        # --- Preprint URL (check for SSRN or SocArXiv links) ---
        for a_tag in soup.select("a[href]"):
            href = a_tag.get("href", "")
            if any(repo in href for repo in (
                "arxiv.org", "biorxiv.org", "medrxiv.org",
                "ssrn.com", "socopen.org", "osf.io/preprints/socarxiv",
                "chemrxiv.org",
            )):
                raw.preprint_url = href
                break
