"""
scraper.science_scraper — Scraper for *Science* magazine (AAAS).

Target:  https://www.science.org/toc/science/current
Layout:  The table-of-contents page includes a large cover image and a
         "This Week's Cover" blurb that links to the featured research
         article.

NOTE:  CSS selectors are based on the site layout observed as of early 2025.
       The ``science.org`` front-end is a React SPA that sometimes serves
       pre-rendered HTML; selectors may need updating if AAAS redesigns.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BaseScraper, CoverArticleRaw

logger = logging.getLogger(__name__)


class ScienceScraper(BaseScraper):
    """Scraper for *Science* (AAAS)."""

    JOURNAL_NAME = "Science"
    BASE_URL = "https://www.science.org"
    TOC_URL = f"{BASE_URL}/toc/science/current"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_current_issue(self) -> Optional[CoverArticleRaw]:
        """Scrape the current issue of *Science*."""
        logger.info("Scraping current issue of %s ...", self.JOURNAL_NAME)
        return self._scrape_toc_page(self.TOC_URL)

    def scrape_issue(self, volume: str, issue: str) -> Optional[CoverArticleRaw]:
        """Scrape a specific back-issue of *Science*."""
        url = f"{self.BASE_URL}/toc/science/{volume}/{issue}"
        logger.info("Scraping %s vol.%s issue %s ...", self.JOURNAL_NAME, volume, issue)
        return self._scrape_toc_page(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_toc_page(self, toc_url: str) -> Optional[CoverArticleRaw]:
        """Core logic shared by both ``scrape_current_issue`` and
        ``scrape_issue``.
        """
        soup = self._fetch_and_parse(toc_url)
        if soup is None:
            logger.error("Failed to fetch TOC page: %s", toc_url)
            return None

        raw = CoverArticleRaw(journal=self.JOURNAL_NAME)

        # --- Volume / issue / date ---
        self._extract_issue_metadata(soup, raw)

        # --- Cover image ---
        self._extract_cover_image(soup, raw)

        # --- Cover description & linked article ---
        self._extract_cover_story(soup, raw)

        # --- Fetch the full article page for abstract / authors / DOI ---
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
        """Pull volume, issue number, and publication date from the TOC."""

        # TODO: Verify selector — Science uses a banner like
        #   <div class="journal-issue__vol">Vol 388, Issue 6753 • 20 Jun 2025</div>
        vol_tag = soup.select_one(
            ".journal-issue__vol, .issue-info-vol, [class*='issueInfo']"
        )
        if vol_tag:
            text = self._clean_text(vol_tag.get_text())
            # Typical pattern: "Vol 388, Issue 6753"
            m = re.search(r"Vol\s+(\d+)", text, re.IGNORECASE)
            if m:
                raw.volume = m.group(1)
            m = re.search(r"Issue\s+(\d+)", text, re.IGNORECASE)
            if m:
                raw.issue = m.group(1)

        # Date — look for a <time> element or parse from the banner text.
        time_tag = soup.select_one("time[datetime]")
        if time_tag and time_tag.get("datetime"):
            raw.date = time_tag["datetime"][:10]  # ISO date portion
        else:
            # Fallback: try to extract from the volume banner.
            if vol_tag:
                from dateutil.parser import parse as parse_date
                text = vol_tag.get_text()
                # Look for patterns like "20 Jun 2025" or "June 20, 2025"
                date_match = re.search(
                    r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})", text
                )
                if date_match:
                    try:
                        raw.date = parse_date(date_match.group(1)).strftime("%Y-%m-%d")
                    except (ValueError, OverflowError):
                        pass

    # --- Cover image -----------------------------------------------------

    def _extract_cover_image(self, soup, raw: CoverArticleRaw) -> None:
        """Find the high-res cover image URL.

        Science.org typically renders the cover as:
            <img src="…/largecover.jpg" …>
        or via a ``<picture>`` element with a ``srcset`` attribute.
        """
        # TODO: Verify selectors against live HTML structure.

        # Strategy 1 — ``img`` whose ``src`` contains "largecover" or "cover"
        img = soup.select_one("img[src*='largecover']")
        if not img:
            img = soup.select_one("img[src*='cover']")
        if not img:
            # Strategy 2 — look inside a wrapper div used for the TOC cover
            img = soup.select_one(
                ".cover-image img, .journal-issue__cover img, "
                "[class*='coverImage'] img, [class*='CoverImage'] img"
            )

        if img:
            src = img.get("src") or img.get("data-src") or ""
            raw.cover_image_url = self._abs_url(self.BASE_URL, src)
            raw.cover_image_credit = self._clean_text(img.get("alt", ""))

    # --- Cover story -----------------------------------------------------

    def _extract_cover_story(self, soup, raw: CoverArticleRaw) -> None:
        """Extract the 'This Week's Cover' blurb and locate the linked
        research article.

        The blurb usually lives in a section like:
            <div class="cover-story"> … <a href="/doi/…"> … </a></div>
        """
        # TODO: Verify selectors against live HTML structure.

        # Look for a cover-story container.
        cover_block = soup.select_one(
            ".cover-story, .about-cover, [class*='coverStory'], "
            "[class*='AboutCover'], [class*='about-the-cover']"
        )
        if cover_block:
            raw.cover_description = self._clean_text(cover_block.get_text())
            # Find the first article link inside the cover story.
            link = cover_block.select_one("a[href*='/doi/']")
            if link:
                raw.article_url = self._abs_url(self.BASE_URL, link["href"])
                raw.article_title = self._clean_text(link.get_text())
                return

        # Fallback — scan all paragraphs for "cover" mention and grab
        # the nearest article link.
        for p_tag in soup.select("p"):
            text = p_tag.get_text().lower()
            if "cover" in text and ("image" in text or "photo" in text or "illustration" in text):
                raw.cover_description = self._clean_text(p_tag.get_text())
                link = p_tag.find("a", href=re.compile(r"/doi/"))
                if link:
                    raw.article_url = self._abs_url(self.BASE_URL, link["href"])
                    raw.article_title = self._clean_text(link.get_text())
                break

    # --- Article enrichment ----------------------------------------------

    def _enrich_from_article_page(self, raw: CoverArticleRaw) -> None:
        """Fetch the full article page and pull abstract, authors, and DOI."""
        soup = self._fetch_and_parse(raw.article_url)
        if soup is None:
            logger.warning("Could not fetch article page: %s", raw.article_url)
            return

        # --- Title (canonical) ---
        title_tag = soup.select_one(
            "h1.article-title, h1[property='name'], .publicationContentTitle h1"
        )
        if title_tag:
            raw.article_title = self._clean_text(title_tag.get_text())

        # --- Authors ---
        # TODO: Verify selectors — Science lists authors in <span class="authors-list"> or similar.
        author_tags = soup.select(
            ".contributors a[href*='author'], "
            ".authors-list a, "
            "[class*='author-name']"
        )
        if author_tags:
            raw.article_authors = [
                self._clean_text(a.get_text()) for a in author_tags
            ]

        # --- Abstract ---
        abstract_div = soup.select_one(
            ".abstract, [role='doc-abstract'], .abstractSection"
        )
        if abstract_div:
            raw.article_abstract = self._clean_text(abstract_div.get_text())

        # --- DOI ---
        doi_tag = soup.select_one("a[href*='doi.org/10.']")
        if doi_tag:
            href = doi_tag["href"]
            m = re.search(r"(10\.\d{4,}/\S+)", href)
            if m:
                raw.article_doi = m.group(1).rstrip(".")
        if not raw.article_doi:
            # Fallback: extract from meta tag.
            meta = soup.select_one("meta[name='citation_doi']")
            if meta:
                raw.article_doi = meta.get("content", "")

        # --- Preprint URL ---
        for a_tag in soup.select("a[href]"):
            href = a_tag.get("href", "")
            if any(repo in href for repo in (
                "arxiv.org", "biorxiv.org", "medrxiv.org",
                "ssrn.com", "chemrxiv.org",
            )):
                raw.preprint_url = href
                break
