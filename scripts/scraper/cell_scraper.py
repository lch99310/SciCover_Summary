"""
scraper.cell_scraper — Scraper for *Cell* (Cell Press / Elsevier).

Target:  https://www.cell.com/cell/current
Layout:  Cell Press sites share a common template.  The TOC page displays
         a cover image, an "On the Cover" blurb, and sections grouping
         articles by type.

NOTE:  CSS selectors are based on the layout observed as of early 2025.
       Cell Press occasionally refreshes its design; update as needed.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BaseScraper, CoverArticleRaw

logger = logging.getLogger(__name__)


class CellScraper(BaseScraper):
    """Scraper for *Cell* (Cell Press)."""

    JOURNAL_NAME = "Cell"
    BASE_URL = "https://www.cell.com"
    TOC_URL = f"{BASE_URL}/cell/current"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_current_issue(self) -> Optional[CoverArticleRaw]:
        """Scrape the current issue of *Cell*."""
        logger.info("Scraping current issue of %s ...", self.JOURNAL_NAME)
        return self._scrape_toc_page(self.TOC_URL)

    def scrape_issue(self, volume: str, issue: str) -> Optional[CoverArticleRaw]:
        """Scrape a specific back-issue of *Cell*."""
        url = f"{self.BASE_URL}/cell/vol-{volume}/issue-{issue}"
        logger.info("Scraping %s vol.%s issue %s ...", self.JOURNAL_NAME, volume, issue)
        return self._scrape_toc_page(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_toc_page(self, toc_url: str) -> Optional[CoverArticleRaw]:
        """Core scraping logic for a Cell TOC page."""
        soup = self._fetch_and_parse(toc_url)
        if soup is None:
            logger.error("Failed to fetch TOC page: %s", toc_url)
            return None

        raw = CoverArticleRaw(journal=self.JOURNAL_NAME)

        # --- Volume / issue / date ---
        self._extract_issue_metadata(soup, raw)

        # --- Cover image ---
        self._extract_cover_image(soup, raw)

        # --- "On the Cover" text & linked article ---
        self._extract_cover_story(soup, raw)

        # --- Enrich from the article page ---
        if raw.article_url:
            self._enrich_from_article_page(raw)

        if not raw.cover_image_url:
            logger.warning("No cover image found for %s — skipping", toc_url)
            return None

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
        """Pull volume, issue number, and date from the TOC page.

        Cell Press pages typically have a banner like:
            <div class="issue-info">Volume 188, Issue 13, June 26, 2025</div>
        """
        # TODO: Verify selector against live HTML structure.
        info_tag = soup.select_one(
            ".issue-info, .issueTocHeader, [class*='issueInfo'], "
            "[class*='toc-header'] .issue-meta"
        )
        if info_tag:
            text = self._clean_text(info_tag.get_text())
            m_vol = re.search(r"Volume\s+(\d+)", text, re.IGNORECASE)
            if m_vol:
                raw.volume = m_vol.group(1)
            m_iss = re.search(r"Issue\s+(\d+)", text, re.IGNORECASE)
            if m_iss:
                raw.issue = m_iss.group(1)

            # Date — e.g. "June 26, 2025" or "26 June 2025"
            from dateutil.parser import parse as parse_date
            date_match = re.search(
                r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+\w+\s+\d{4})", text
            )
            if date_match:
                try:
                    raw.date = parse_date(date_match.group(1)).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    pass

        # Fallback: meta tags.
        if not raw.volume:
            meta = soup.select_one("meta[name='citation_volume']")
            if meta:
                raw.volume = meta.get("content", "")
        if not raw.issue:
            meta = soup.select_one("meta[name='citation_issue']")
            if meta:
                raw.issue = meta.get("content", "")
        if not raw.date:
            meta = soup.select_one("meta[name='citation_publication_date']")
            if meta:
                raw.date = meta.get("content", "")[:10]

    # --- Cover image -----------------------------------------------------

    def _extract_cover_image(self, soup, raw: CoverArticleRaw) -> None:
        """Find the cover image.

        Cell Press typically renders the cover in a wrapper:
            <div class="cover-image">
              <img src="https://…/cover.jpg" alt="…" />
            </div>
        The image URL is often on the Elsevier CDN (els-cdn.com or
        cell.com/cms/…).
        """
        # TODO: Verify selectors against live HTML structure.

        # Strategy 1 — dedicated cover wrapper.
        img = soup.select_one(
            ".cover-image img, .toc-cover img, "
            "[class*='coverImage'] img, [class*='CoverImage'] img, "
            ".issue-cover img"
        )
        if not img:
            # Strategy 2 — any image whose src mentions "cover" or the CDN.
            img = soup.select_one("img[src*='cover']")
        if not img:
            img = soup.select_one("img[src*='els-cdn']")

        if img:
            src = img.get("src") or img.get("data-src") or ""
            raw.cover_image_url = self._abs_url(self.BASE_URL, src)
            raw.cover_image_credit = self._clean_text(img.get("alt", ""))

    # --- Cover story -----------------------------------------------------

    def _extract_cover_story(self, soup, raw: CoverArticleRaw) -> None:
        """Extract the "On the Cover" blurb and the linked article.

        Cell Press pages often have a section:
            <div class="on-the-cover">
              <p>On the Cover: …</p>
              <a href="/cell/fulltext/S0092-8674(25)…">…</a>
            </div>
        """
        # TODO: Verify selectors against live HTML structure.

        # Look for explicit "On the Cover" block.
        cover_section = soup.select_one(
            ".on-the-cover, [class*='onTheCover'], [class*='OnTheCover'], "
            "[class*='about-the-cover'], .cover-description"
        )

        if not cover_section:
            # Fallback: search for paragraphs containing "on the cover".
            for tag in soup.select("p, div"):
                text = tag.get_text().lower()
                if "on the cover" in text or "cover image" in text:
                    cover_section = tag
                    break

        if cover_section:
            raw.cover_description = self._clean_text(cover_section.get_text())

            # Find article link — Cell uses /fulltext/ or /abstract/ paths.
            link = cover_section.select_one(
                "a[href*='/fulltext/'], a[href*='/abstract/']"
            )
            if link:
                raw.article_url = self._abs_url(self.BASE_URL, link["href"])
                raw.article_title = self._clean_text(link.get_text())
                return

        # Ultimate fallback: grab the first research-article link.
        first_article = soup.select_one(
            "a[href*='/cell/fulltext/S0092-8674']"
        )
        if first_article:
            raw.article_url = self._abs_url(self.BASE_URL, first_article["href"])
            raw.article_title = self._clean_text(first_article.get_text())

    # --- Article enrichment ----------------------------------------------

    def _enrich_from_article_page(self, raw: CoverArticleRaw) -> None:
        """Fetch the article page and pull abstract, authors, and DOI."""
        soup = self._fetch_and_parse(raw.article_url)
        if soup is None:
            logger.warning("Could not fetch article page: %s", raw.article_url)
            return

        # --- Title ---
        title_tag = soup.select_one(
            "h1.article-header__title, h1[class*='article-title'], "
            "meta[name='citation_title']"
        )
        if title_tag:
            if title_tag.name == "meta":
                raw.article_title = title_tag.get("content", "")
            else:
                raw.article_title = self._clean_text(title_tag.get_text())

        # --- Authors ---
        # TODO: Verify selectors — Cell Press uses:
        #   <span class="author-name" ...>First Last</span>
        author_tags = soup.select(
            ".author-name, [class*='authorName'], "
            "meta[name='citation_author']"
        )
        if author_tags:
            authors = []
            for tag in author_tags:
                if tag.name == "meta":
                    authors.append(tag.get("content", ""))
                else:
                    authors.append(self._clean_text(tag.get_text()))
            raw.article_authors = authors

        # --- Abstract ---
        abstract_div = soup.select_one(
            "#abstracts, .abstract, [class*='Abstract'], "
            "[id='abstract'] .section-paragraph"
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

        # --- Pages ---
        meta_fp = soup.select_one("meta[name='citation_firstpage']")
        meta_lp = soup.select_one("meta[name='citation_lastpage']")
        if meta_fp and meta_lp:
            raw.article_pages = (
                f"{meta_fp.get('content', '')}-{meta_lp.get('content', '')}"
            )

        # --- Preprint URL ---
        for a_tag in soup.select("a[href]"):
            href = a_tag.get("href", "")
            if any(repo in href for repo in (
                "arxiv.org", "biorxiv.org", "medrxiv.org",
                "ssrn.com", "chemrxiv.org",
            )):
                raw.preprint_url = href
                break
