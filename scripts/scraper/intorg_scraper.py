"""
scraper.intorg_scraper — Scraper for *International Organization* (Cambridge
University Press).

Target:  https://www.cambridge.org/core/journals/international-organization
Layout:  Cambridge Core journal pages show a table of contents with article
         listings.  International Organization is a quarterly journal
         (4 issues/year).  It is one of the top IR/political-science journals.

Preprint repositories: SSRN, SocArXiv.

NOTE:  CSS selectors are based on the Cambridge Core layout observed as of
       early 2025.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import BaseScraper, CoverArticleRaw

logger = logging.getLogger(__name__)


class IntOrgScraper(BaseScraper):
    """Scraper for *International Organization* (Cambridge University Press)."""

    JOURNAL_NAME = "International Organization"
    BASE_URL = "https://www.cambridge.org"
    JOURNAL_PATH = "/core/journals/international-organization"
    TOC_URL = f"{BASE_URL}{JOURNAL_PATH}/latest-issue"

    # Publication frequency metadata (quarterly, 4 issues/year).
    PUBLICATION_FREQUENCY = "quarterly"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_current_issue(self) -> Optional[CoverArticleRaw]:
        """Scrape the current/latest issue of *International Organization*."""
        logger.info("Scraping current issue of %s ...", self.JOURNAL_NAME)
        return self._scrape_toc_page(self.TOC_URL)

    def scrape_issue(self, volume: str, issue: str) -> Optional[CoverArticleRaw]:
        """Scrape a specific back-issue of *International Organization*."""
        url = f"{self.BASE_URL}{self.JOURNAL_PATH}/issue/{volume}/{issue}"
        logger.info("Scraping %s vol.%s issue %s ...", self.JOURNAL_NAME, volume, issue)
        return self._scrape_toc_page(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scrape_toc_page(self, toc_url: str) -> Optional[CoverArticleRaw]:
        """Core scraping logic for a Cambridge Core TOC page."""
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

        # Try to get cover image from the issue page
        self._extract_cover_image(soup, raw)

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

        Cambridge Core typically shows:
            <h1>Volume 80, Issue 1 - January 2026</h1>
        or in the <title>:
            Latest issue | International Organization | Cambridge Core
        Also handles supplement issues like "Issue S1".
        """
        header = soup.select_one(
            ".journal-issue h1, .issue-title, "
            "h1[class*='issue'], .current-issue__details"
        )

        # Also try <title> tag as fallback for page metadata
        title_tag = soup.select_one("title")

        text = ""
        if header:
            text = self._clean_text(header.get_text())
        elif title_tag:
            text = self._clean_text(title_tag.get_text())

        if text:
            m_vol = re.search(r"Volume\s+(\d+)", text, re.IGNORECASE)
            if m_vol:
                raw.volume = m_vol.group(1)
            # Handle both "Issue 1" and "Issue S1" (supplement)
            m_iss = re.search(r"Issue\s+(\w+)", text, re.IGNORECASE)
            if m_iss:
                raw.issue = m_iss.group(1)

            from dateutil.parser import parse as parse_date
            # Try date after a dash: "Volume 79, Issue S1 - December 2025"
            date_match = re.search(r"-\s*(\w+\s+\d{4})", text)
            if not date_match:
                date_match = re.search(
                    r"(\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})", text
                )
            if date_match:
                try:
                    raw.date = parse_date(date_match.group(1)).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    pass

        # Fallback: meta tags
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

        # Also try to extract volume/issue from the page body text if still missing
        if not raw.volume or not raw.issue:
            for tag in soup.select("h1, h2, h3, .volume-issue"):
                tag_text = self._clean_text(tag.get_text())
                if not raw.volume:
                    m = re.search(r"Volume\s+(\d+)", tag_text, re.IGNORECASE)
                    if m:
                        raw.volume = m.group(1)
                if not raw.issue:
                    m = re.search(r"Issue\s+(\w+)", tag_text, re.IGNORECASE)
                    if m:
                        raw.issue = m.group(1)

    # --- Cover image -----------------------------------------------------

    def _extract_cover_image(self, soup, raw: CoverArticleRaw) -> None:
        """Find the journal cover image if available.

        Cambridge Core sometimes displays a cover image:
            <img class="cover-image" src="..." />
        """
        img = soup.select_one(
            ".cover-image img, img[class*='cover'], "
            ".journal-cover img, img[src*='cover']"
        )
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src:
                raw.cover_image_url = self._abs_url(self.BASE_URL, src)

    # --- Lead article ----------------------------------------------------

    def _extract_lead_article(self, soup, raw: CoverArticleRaw) -> None:
        """Find the lead/featured article from the TOC.

        Cambridge Core lists articles as:
            <li class="article-item"> ... <a href="/core/journals/.../article/..."> </li>
        """
        # Look for research articles (skip editorial material)
        first_article = soup.select_one(
            ".article-item a[href*='/article/'], "
            "li[class*='article'] a.part-link, "
            "a[class*='title'][href*='/article/'], "
            ".listing-citation a[href*='/article/']"
        )
        if not first_article:
            # Broader fallback
            first_article = soup.select_one("a[href*='/core/journals/'][href*='/article/']")

        if first_article:
            raw.article_url = self._abs_url(self.BASE_URL, first_article.get("href", ""))
            raw.article_title = self._clean_text(first_article.get_text())

    # --- Article enrichment ----------------------------------------------

    def _enrich_from_article_page(self, raw: CoverArticleRaw) -> None:
        """Fetch the article page and pull abstract, authors, DOI,
        article-level publication date, and fallback image."""
        soup = self._fetch_and_parse(raw.article_url)
        if soup is None:
            logger.warning("Could not fetch article page: %s", raw.article_url)
            return

        # --- Article-level publication date ---
        self._extract_article_date(soup, raw)

        # --- Title ---
        title_tag = soup.select_one(
            "h1.article-title, .article-title, "
            "meta[name='citation_title']"
        )
        if title_tag:
            if title_tag.name == "meta":
                raw.article_title = title_tag.get("content", "")
            else:
                raw.article_title = self._clean_text(title_tag.get_text())

        # --- Authors ---
        author_tags = soup.select(
            ".author a, .contrib-author, "
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
            ".abstract, [class*='abstract'], "
            "#abstract, [role='doc-abstract']"
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

        # --- Fallback cover image from og:image ---
        if not raw.cover_image_url:
            self._extract_og_image(soup, raw)

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

    # --- Article date extraction -----------------------------------------

    @staticmethod
    def _extract_article_date(soup, raw: CoverArticleRaw) -> None:
        """Extract article-level publication date from Cambridge Core page.

        Cambridge Core uses meta tags like:
            <meta name="citation_online_date" content="2025/12/01">
            <meta name="citation_publication_date" content="2025/12/01">
        Also looks for "Published online by Cambridge University Press" text.
        """
        from dateutil.parser import parse as parse_date

        # Strategy 1: citation_online_date
        meta_online = soup.select_one("meta[name='citation_online_date']")
        if meta_online:
            try:
                raw.article_date = parse_date(
                    meta_online.get("content", "")
                ).strftime("%Y-%m-%d")
            except (ValueError, OverflowError):
                pass

        # Strategy 2: citation_publication_date
        if not raw.article_date:
            meta_pub = soup.select_one("meta[name='citation_publication_date']")
            if meta_pub:
                try:
                    raw.article_date = parse_date(
                        meta_pub.get("content", "")
                    ).strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    pass

        # Strategy 3: "Published online" text
        if not raw.article_date:
            for tag in soup.select("span, div, p"):
                text = tag.get_text()
                if "Published online" in text:
                    date_match = re.search(
                        r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})", text
                    )
                    if date_match:
                        try:
                            raw.article_date = parse_date(date_match.group(1)).strftime("%Y-%m-%d")
                        except (ValueError, OverflowError):
                            pass
                        break

    @staticmethod
    def _extract_og_image(soup, raw: CoverArticleRaw) -> None:
        """Fallback: use og:image meta tag as article thumbnail."""
        og_img = soup.select_one("meta[property='og:image']")
        if og_img:
            url = og_img.get("content", "")
            if url and "default" not in url.lower() and "logo" not in url.lower():
                # Skip generic journal cover images from Cambridge
                if "covers/" not in url.lower():
                    raw.cover_image_url = url
