"""
scraper.nature_scraper — Scraper for *Nature* (Springer Nature).

Target:  https://www.nature.com/nature/current-issue
Layout:  The page usually redirects to a canonical path like
         ``/nature/volumes/620/issues/7970`` and includes a large cover
         image hosted on the Springer Nature CDN, plus a "This Week" or
         "Cover Story" section linking to the featured article.

NOTE:  CSS selectors are based on the layout observed as of early 2025.
       Springer Nature redesigns occasionally; selectors may need updating.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BaseScraper, CoverArticleRaw

logger = logging.getLogger(__name__)


class NatureScraper(BaseScraper):
    """Scraper for *Nature* (Springer Nature)."""

    JOURNAL_NAME = "Nature"
    BASE_URL = "https://www.nature.com"
    TOC_URL = f"{BASE_URL}/nature/current-issue"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_current_issue(self) -> Optional[CoverArticleRaw]:
        """Scrape the current issue of *Nature*."""
        logger.info("Scraping current issue of %s ...", self.JOURNAL_NAME)
        return self._scrape_toc_page(self.TOC_URL)

    def scrape_issue(self, volume: str, issue: str) -> Optional[CoverArticleRaw]:
        """Scrape a specific back-issue of *Nature*."""
        url = f"{self.BASE_URL}/nature/volumes/{volume}/issues/{issue}"
        logger.info("Scraping %s vol.%s issue %s ...", self.JOURNAL_NAME, volume, issue)
        return self._scrape_toc_page(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_toc_page(self, toc_url: str) -> Optional[CoverArticleRaw]:
        """Core scraping logic for a Nature TOC page."""
        soup = self._fetch_and_parse(toc_url)
        if soup is None:
            logger.error("Failed to fetch TOC page: %s", toc_url)
            return None

        raw = CoverArticleRaw(journal=self.JOURNAL_NAME)

        # --- Volume / issue / date ---
        self._extract_issue_metadata(soup, raw)

        # --- Cover image ---
        self._extract_cover_image(soup, raw)

        # --- Cover story / lead article ---
        self._extract_cover_story(soup, raw)

        # --- Enrich from article page ---
        if raw.article_url:
            self._enrich_from_article_page(raw)

        if not raw.cover_image_url:
            logger.warning("No cover image found for %s — proceeding without cover", toc_url)

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
        """Extract volume, issue number, and publication date.

        The canonical URL after redirect typically looks like:
            /nature/volumes/620/issues/7970
        The page also carries structured ``<meta>`` tags with citation info.
        """
        # Try meta tags first (most reliable).
        meta_vol = soup.select_one("meta[name='citation_volume']")
        if meta_vol:
            raw.volume = meta_vol.get("content", "")
        meta_issue = soup.select_one("meta[name='citation_issue']")
        if meta_issue:
            raw.issue = meta_issue.get("content", "")
        meta_date = soup.select_one("meta[name='citation_publication_date']")
        if meta_date:
            raw.date = meta_date.get("content", "")[:10]

        # Fallback: parse the page heading.
        # TODO: Verify selector — Nature uses something like:
        #   <span class="c-journal-heading__date">19 June 2025</span>
        if not raw.date:
            date_tag = soup.select_one(
                ".c-journal-heading__date, [data-test='issue-date'], "
                "[class*='issueDate']"
            )
            if date_tag:
                from dateutil.parser import parse as parse_date
                try:
                    raw.date = parse_date(
                        self._clean_text(date_tag.get_text())
                    ).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    pass

        # Fallback volume/issue from URL path.
        if not raw.volume or not raw.issue:
            # Look for canonical link in <head>.
            canon = soup.select_one("link[rel='canonical']")
            if canon:
                m = re.search(r"/volumes/(\d+)/issues/(\d+)", canon.get("href", ""))
                if m:
                    raw.volume = raw.volume or m.group(1)
                    raw.issue = raw.issue or m.group(2)

    # --- Cover image -----------------------------------------------------

    def _extract_cover_image(self, soup, raw: CoverArticleRaw) -> None:
        """Locate the cover image.

        Nature hosts cover images on the Springer Nature CDN, typically:
            https://media.springernature.com/w580/nature-cms/uploads/…/cover.jpg
        The page usually wraps it in a ``<picture>`` or ``<img>`` tag.

        IMPORTANT: Must skip SVG files (header logos) and only grab actual
        raster cover images (jpg/png/webp).
        """
        def _is_valid_cover(tag) -> bool:
            """Return True if the img tag points to a real cover image."""
            src = (tag.get("src") or tag.get("data-src") or "").lower()
            # Skip SVG files — these are logos/headers, not covers
            if src.endswith(".svg") or "/header" in src or "/logo" in src:
                return False
            # Must be an actual image file
            if not src:
                return False
            return True

        img = None

        # Strategy 1 — dedicated cover wrapper on the TOC page.
        for candidate in soup.select(
            ".c-issue-cover img, [data-test='issue-cover'] img, "
            ".issue-cover-image img"
        ):
            if _is_valid_cover(candidate):
                img = candidate
                break

        # Strategy 2 — img whose src matches CDN pattern for uploads (not headers).
        if not img:
            for candidate in soup.select("img[src*='springernature.com']"):
                src = (candidate.get("src") or "").lower()
                if "uploads" in src and _is_valid_cover(candidate):
                    img = candidate
                    break

        if not img:
            for candidate in soup.select("img[src*='nature-cms']"):
                src = (candidate.get("src") or "").lower()
                if "uploads" in src and _is_valid_cover(candidate):
                    img = candidate
                    break

        # Strategy 3 — any cover-related class with a raster image.
        if not img:
            for candidate in soup.select("[class*='cover'] img"):
                if _is_valid_cover(candidate):
                    img = candidate
                    break

        if img:
            src = img.get("src") or img.get("data-src") or ""
            raw.cover_image_url = self._abs_url(self.BASE_URL, src)

            # Try to get credit from alt text or a nearby figcaption.
            raw.cover_image_credit = self._clean_text(img.get("alt", ""))
            figcaption = img.find_parent("figure")
            if figcaption:
                caption_tag = figcaption.select_one("figcaption")
                if caption_tag:
                    raw.cover_image_credit = self._clean_text(caption_tag.get_text())

    # --- Cover story -----------------------------------------------------

    def _extract_cover_story(self, soup, raw: CoverArticleRaw) -> None:
        """Extract the cover story blurb and the featured article link.

        Nature's TOC page typically groups articles under sections.  The
        lead article section (or an explicit "Cover Story" block) contains
        the featured paper.
        """
        # TODO: Verify selectors against live HTML structure.

        # Look for a dedicated cover-story section.
        cover_section = soup.select_one(
            "[data-test='cover-story'], .cover-story, "
            "[class*='CoverStory'], [class*='cover-story']"
        )

        if not cover_section:
            # Fallback: grab the first editorial-summary or "This Week" block.
            cover_section = soup.select_one(
                ".c-section--this-week, [data-test='editorial-summary'], "
                "[class*='editorial-summary']"
            )

        if cover_section:
            raw.cover_description = self._clean_text(cover_section.get_text())
            # Find the first article link.
            link = cover_section.select_one("a[href*='/articles/']")
            if link:
                raw.article_url = self._abs_url(self.BASE_URL, link["href"])
                raw.article_title = self._clean_text(link.get_text())
                return

        # Fallback: just pick the very first research-article link on the page.
        first_article = soup.select_one(
            "a[href*='/articles/s41586-']"
        )
        if first_article:
            raw.article_url = self._abs_url(self.BASE_URL, first_article["href"])
            raw.article_title = self._clean_text(first_article.get_text())

    # --- Article enrichment ----------------------------------------------

    def _enrich_from_article_page(self, raw: CoverArticleRaw) -> None:
        """Fetch the article page and pull abstract, DOI, authors,
        article-level publication date, and fallback image."""
        soup = self._fetch_and_parse(raw.article_url)
        if soup is None:
            logger.warning("Could not fetch article page: %s", raw.article_url)
            return

        # --- Article-level publication date ---
        self._extract_article_date(soup, raw)

        # --- Title ---
        title_tag = soup.select_one(
            "h1.c-article-title, h1[data-test='article-title'], "
            "h1[itemprop='headline']"
        )
        if title_tag:
            raw.article_title = self._clean_text(title_tag.get_text())

        # --- Authors ---
        author_tags = soup.select(
            ".c-article-author-list__item a[data-test='author-name'], "
            "[itemprop='author'] [itemprop='name'], "
            ".c-author-list a"
        )
        if author_tags:
            raw.article_authors = [
                self._clean_text(a.get_text()) for a in author_tags
            ]

        # --- Abstract ---
        abstract_div = soup.select_one(
            "#Abs1-content, [data-test='article-abstract'], "
            ".c-article-section__content[id*='abstract'], "
            "[id='abstract'] .c-article-section__content"
        )
        if abstract_div:
            raw.article_abstract = self._clean_text(abstract_div.get_text())

        # --- DOI ---
        meta_doi = soup.select_one("meta[name='citation_doi']")
        if meta_doi:
            raw.article_doi = meta_doi.get("content", "")
        if not raw.article_doi:
            doi_tag = soup.select_one("a[data-track-action='view doi']")
            if doi_tag:
                m = re.search(r"(10\.\d{4,}/\S+)", doi_tag.get("href", ""))
                if m:
                    raw.article_doi = m.group(1).rstrip(".")

        # --- Fallback cover image from og:image ---
        if not raw.cover_image_url:
            self._extract_og_image(soup, raw)

        # --- Preprint URL ---
        for a_tag in soup.select("a[href]"):
            href = a_tag.get("href", "")
            if any(repo in href for repo in (
                "arxiv.org", "biorxiv.org", "medrxiv.org",
                "ssrn.com", "chemrxiv.org",
            )):
                raw.preprint_url = href
                break

    # --- Article date extraction -----------------------------------------

    @staticmethod
    def _extract_article_date(soup, raw: CoverArticleRaw) -> None:
        """Extract the article-level publication date from the Nature article page.

        Nature uses meta tags like:
            <meta name="citation_online_date" content="2026/01/15">
            <meta name="dc.date" content="2026-01-15">
            <meta name="citation_publication_date" content="2026/02/26">
        And also <time datetime="..."> elements.
        We prefer the earliest date (online/first-published date).
        """
        from dateutil.parser import parse as parse_date

        # Strategy 1: citation_online_date (first published online)
        meta_online = soup.select_one("meta[name='citation_online_date']")
        if meta_online:
            try:
                raw.article_date = parse_date(
                    meta_online.get("content", "")
                ).strftime("%Y-%m-%d")
            except (ValueError, OverflowError):
                pass

        # Strategy 2: dc.date meta tag
        if not raw.article_date:
            meta_dc = soup.select_one("meta[name='dc.date']")
            if meta_dc:
                try:
                    raw.article_date = parse_date(
                        meta_dc.get("content", "")
                    ).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    pass

        # Strategy 3: <time> elements with "Published:" context
        if not raw.article_date:
            for time_tag in soup.select("time[datetime]"):
                dt_str = time_tag.get("datetime", "")[:10]
                if dt_str and len(dt_str) == 10:
                    if not raw.article_date or dt_str < raw.article_date:
                        raw.article_date = dt_str

    @staticmethod
    def _extract_og_image(soup, raw: CoverArticleRaw) -> None:
        """Fallback: use og:image meta tag as article thumbnail."""
        og_img = soup.select_one("meta[property='og:image']")
        if og_img:
            url = og_img.get("content", "")
            if url and "default" not in url.lower() and "logo" not in url.lower():
                raw.cover_image_url = url
