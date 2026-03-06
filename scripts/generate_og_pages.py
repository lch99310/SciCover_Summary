#!/usr/bin/env python3
"""
generate_og_pages.py — Generate static HTML pages with Open Graph meta tags.

Social media crawlers (Facebook, LINE, Twitter, Discord, Slack, etc.) do NOT
execute JavaScript and ignore URL hash fragments.  Since SciCover uses
HashRouter (``/#/article/...``), shared links always show the default
``index.html`` OG tags — no article-specific preview.

This script creates a small HTML file for each article at:

    dist/article/{article-id}/index.html

Each file contains:
  - ``og:title``  — the article's bilingual title
  - ``og:image``  — the article's cover image (absolute URL)
  - ``og:description`` — short summary
  - A JavaScript redirect to ``/#/article/{id}`` so humans land on the SPA

Usage (called during deploy, after ``npm run build`` and data copy):

    python3 scripts/generate_og_pages.py frontend/dist
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

SITE_URL = "https://lch99310.github.io/SciCover_Summary"
SITE_NAME = "SciCover Summary"
DEFAULT_IMAGE = f"{SITE_URL}/og-default.jpg"


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

        # Read the full article JSON for richer metadata.
        article_path = dist / "data" / entry.get("path", "")
        title_zh = entry.get("title_zh", "")
        title_en = entry.get("title_en", "")
        cover_url = entry.get("cover_url", "")
        journal = entry.get("journal", "")
        date = entry.get("date", "")
        description = ""

        if article_path.exists():
            try:
                data = json.loads(article_path.read_text(encoding="utf-8"))
                summary = data.get("coverStory", {}).get("summary", {})
                desc_zh = summary.get("zh", "")
                desc_en = summary.get("en", "")
                # Use first ~120 chars of the Chinese summary as description.
                if desc_zh:
                    description = desc_zh[:150].rsplit("。", 1)[0] + "。"
                elif desc_en:
                    description = desc_en[:200]
            except (json.JSONDecodeError, OSError):
                pass

        # Build OG tags.
        og_title = f"{title_zh} | {title_en}" if title_zh and title_en else (title_zh or title_en or article_id)
        og_image = f"{SITE_URL}/{cover_url}" if cover_url else DEFAULT_IMAGE
        og_description = description or f"{journal} — {date}"
        og_url = f"{SITE_URL}/article/{article_id}"
        spa_url = f"{SITE_URL}/#/article/{article_id}"

        page_html = _build_html(
            og_title=og_title,
            og_description=og_description,
            og_image=og_image,
            og_url=og_url,
            spa_url=spa_url,
            article_id=article_id,
        )

        out_dir = dist / "article" / article_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(page_html, encoding="utf-8")
        count += 1

    print(f"Generated {count} OG pages in {dist / 'article'}")


def _build_html(
    *,
    og_title: str,
    og_description: str,
    og_image: str,
    og_url: str,
    spa_url: str,
    article_id: str,
) -> str:
    t = html.escape(og_title)
    d = html.escape(og_description)
    i = html.escape(og_image)
    u = html.escape(og_url)
    s = html.escape(spa_url)

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>{t} — {html.escape(SITE_NAME)}</title>

<!-- Open Graph -->
<meta property="og:type" content="article"/>
<meta property="og:title" content="{t}"/>
<meta property="og:description" content="{d}"/>
<meta property="og:image" content="{i}"/>
<meta property="og:url" content="{u}"/>
<meta property="og:site_name" content="{html.escape(SITE_NAME)}"/>

<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{t}"/>
<meta name="twitter:description" content="{d}"/>
<meta name="twitter:image" content="{i}"/>

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
