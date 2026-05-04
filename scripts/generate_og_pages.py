#!/usr/bin/env python3
"""
generate_og_pages.py — Generate static HTML pages with Open Graph meta tags
and Schema.org ScholarlyArticle JSON-LD.

Social media crawlers (Facebook, LINE, Twitter, Discord, Slack, etc.) do NOT
execute JavaScript and ignore URL hash fragments.  Since SciCover uses
HashRouter (``/#/article/...``), shared links always show the default
``index.html`` OG tags — no article-specific preview.

This script creates a small HTML file for each article at:

    dist/article/{article-id}/index.html

Each file contains:
  - ``og:title``, ``og:description``, ``og:image`` — the bilingual title,
    short summary and cover image (absolute URL)
  - ``article:published_time``, ``article:modified_time``, ``article:author``
  - Schema.org ``ScholarlyArticle`` JSON-LD for Google rich results
  - A JavaScript redirect to ``/#/article/{id}`` so humans land on the SPA

Usage (called during deploy, after ``npm run build`` and data copy):

    python3 scripts/generate_og_pages.py frontend/dist
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

SITE_URL = "https://lch99310.github.io/SciCover_Summary"
SITE_NAME = "SciCover Summary"
DEFAULT_IMAGE = f"{SITE_URL}/apple-touch-icon.png"
PUBLISHER_AUTHOR = "Chung-Hao Lee"
AUTHOR_URL = "https://lch99310.github.io/chunghao_lee/"

# Mirrors frontend/src/lib/constants.ts DEFAULT_COVER_MAP — fallback when
# an article has no cover_url, so og:image still resolves to a real file.
JOURNAL_DEFAULT_COVERS: dict[str, str] = {
    "Science": "data/images/science/default-cover.jpg",
    "Nature": "data/images/nature/default-cover.jpg",
    "Cell": "data/images/cell/default-cover.jpg",
    "Political Geography": "data/images/political-geography/default-cover.jpg",
    "International Organization": "data/images/international-organization/default-cover.jpg",
    "American Sociological Review": "data/images/american-sociological-review/default-cover.jpg",
}


def _resolve_image(cover_url: str, journal: str, dist: Path) -> str:
    """Pick the best available og:image URL for an article.

    Priority: explicit cover_url → journal default-cover.jpg → site favicon.
    Returns an absolute URL.
    """
    if cover_url:
        candidate = dist / cover_url
        if candidate.exists():
            return f"{SITE_URL}/{cover_url}"

    journal_default = JOURNAL_DEFAULT_COVERS.get(journal)
    if journal_default:
        candidate = dist / journal_default
        if candidate.exists():
            return f"{SITE_URL}/{journal_default}"

    return DEFAULT_IMAGE


def generate(dist_dir: str) -> None:
    dist = Path(dist_dir)
    index_file = dist / "data" / "index.json"

    if not index_file.exists():
        print(f"WARNING: {index_file} not found — skipping OG page generation")
        return

    index = json.loads(index_file.read_text(encoding="utf-8"))
    articles = index.get("articles", [])

    count = 0
    for entry in articles:
        article_id = entry.get("id", "")
        if not article_id:
            continue

        article_path = dist / "data" / entry.get("path", "")
        title_zh = entry.get("title_zh", "")
        title_en = entry.get("title_en", "")
        cover_url = entry.get("cover_url", "")
        journal = entry.get("journal", "")
        date = entry.get("date", "")
        description = ""
        authors: list[str] = []
        doi_url = ""
        modified_date = date

        if article_path.exists():
            try:
                article_data = json.loads(article_path.read_text(encoding="utf-8"))
                summary = article_data.get("coverStory", {}).get("summary", {})
                desc_zh = summary.get("zh", "")
                desc_en = summary.get("en", "")
                if desc_zh:
                    description = desc_zh[:150].rsplit("。", 1)[0] + "。"
                elif desc_en:
                    description = desc_en[:200]

                key_article = article_data.get("coverStory", {}).get("keyArticle", {})
                authors = key_article.get("authors", []) or []
                doi = key_article.get("doi", "")
                if doi:
                    doi_url = doi if doi.startswith("http") else f"https://doi.org/{doi}"

                meta = article_data.get("_meta", {})
                created_at = meta.get("created_at", "")
                if created_at:
                    modified_date = created_at
            except (json.JSONDecodeError, OSError):
                pass

        og_title = (
            f"{title_zh} | {title_en}"
            if title_zh and title_en
            else (title_zh or title_en or article_id)
        )
        og_image = _resolve_image(cover_url, journal, dist)
        og_description = description or f"{journal} — {date}"
        og_url = f"{SITE_URL}/article/{article_id}/"
        spa_url = f"{SITE_URL}/#/article/{article_id}"

        json_ld = _build_json_ld(
            url=og_url,
            title=og_title,
            description=og_description,
            image=og_image,
            journal=journal,
            date_published=date,
            date_modified=modified_date,
            authors=authors,
            doi_url=doi_url,
        )

        page_html = _build_html(
            og_title=og_title,
            og_description=og_description,
            og_image=og_image,
            og_url=og_url,
            spa_url=spa_url,
            date_published=date,
            date_modified=modified_date,
            json_ld=json_ld,
        )

        out_dir = dist / "article" / article_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(page_html, encoding="utf-8")
        count += 1

    print(f"Generated {count} OG pages in {dist / 'article'}")


def _build_json_ld(
    *,
    url: str,
    title: str,
    description: str,
    image: str,
    journal: str,
    date_published: str,
    date_modified: str,
    authors: list[str],
    doi_url: str,
) -> str:
    """Build a Schema.org ScholarlyArticle JSON-LD block.

    The summary itself is a derivative work; ``isBasedOn`` points at the DOI
    of the original peer-reviewed article so search engines understand the
    relationship.
    """
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": title[:110],
        "description": description,
        "image": image,
        "url": url,
        "inLanguage": ["zh-Hant", "en"],
        "datePublished": date_published,
        "dateModified": date_modified,
        "author": {
            "@type": "Person",
            "name": PUBLISHER_AUTHOR,
            "url": AUTHOR_URL,
        },
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "url": SITE_URL,
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": url,
        },
    }

    if doi_url:
        data["isBasedOn"] = {
            "@type": "ScholarlyArticle",
            "url": doi_url,
            "publisher": {"@type": "Organization", "name": journal},
            "author": [{"@type": "Person", "name": a} for a in authors[:20]],
        }

    return json.dumps(data, ensure_ascii=False, indent=2)


def _build_html(
    *,
    og_title: str,
    og_description: str,
    og_image: str,
    og_url: str,
    spa_url: str,
    date_published: str,
    date_modified: str,
    json_ld: str,
) -> str:
    t = html.escape(og_title)
    d = html.escape(og_description)
    i = html.escape(og_image)
    u = html.escape(og_url)
    s = html.escape(spa_url)
    pub = html.escape(date_published)
    mod = html.escape(date_modified)

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{t} — {html.escape(SITE_NAME)}</title>
<meta name="description" content="{d}"/>
<link rel="canonical" href="{u}"/>

<!-- Open Graph -->
<meta property="og:type" content="article"/>
<meta property="og:title" content="{t}"/>
<meta property="og:description" content="{d}"/>
<meta property="og:image" content="{i}"/>
<meta property="og:url" content="{u}"/>
<meta property="og:site_name" content="{html.escape(SITE_NAME)}"/>
<meta property="og:locale" content="zh_TW"/>
<meta property="og:locale:alternate" content="en_US"/>
<meta property="article:published_time" content="{pub}"/>
<meta property="article:modified_time" content="{mod}"/>
<meta property="article:author" content="{html.escape(PUBLISHER_AUTHOR)}"/>

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{t}"/>
<meta name="twitter:description" content="{d}"/>
<meta name="twitter:image" content="{i}"/>

<!-- Schema.org ScholarlyArticle -->
<script type="application/ld+json">
{json_ld}
</script>

<!-- Redirect humans to the SPA -->
<script>window.location.replace("{s}");</script>
<noscript><meta http-equiv="refresh" content="0;url={s}"/></noscript>
</head>
<body>
<p>Redirecting to <a href="{s}">{t}</a>…</p>
</body>
</html>
"""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dist-dir>")
        sys.exit(1)
    generate(sys.argv[1])
