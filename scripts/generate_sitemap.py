#!/usr/bin/env python3
"""
generate_sitemap.py — Emit ``sitemap.xml`` and ``robots.txt`` into the build
output so search engines can discover article pages.

The site uses HashRouter, so SPA paths like ``#/article/...`` are not
crawlable.  However, ``generate_og_pages.py`` already produces a static stub
HTML at ``/article/{id}/`` for every article.  Those are the URLs we list.

Usage (called during deploy, after OG-page generation):

    python3 scripts/generate_sitemap.py frontend/dist
"""

from __future__ import annotations

import json
import sys
from datetime import date as _date
from pathlib import Path
from xml.sax.saxutils import escape

SITE_URL = "https://lch99310.github.io/SciCover_Summary"


def generate(dist_dir: str) -> None:
    dist = Path(dist_dir)
    index_file = dist / "data" / "index.json"

    urls: list[tuple[str, str, str, str]] = []
    # (loc, lastmod, changefreq, priority)
    today = _date.today().isoformat()

    urls.append((f"{SITE_URL}/", today, "daily", "1.0"))

    if index_file.exists():
        index = json.loads(index_file.read_text(encoding="utf-8"))
        articles = index.get("articles", [])
        for entry in articles:
            article_id = entry.get("id", "")
            if not article_id:
                continue
            article_date = entry.get("date", "") or today
            urls.append(
                (
                    f"{SITE_URL}/article/{article_id}/",
                    article_date,
                    "monthly",
                    "0.8",
                )
            )
    else:
        print(f"WARNING: {index_file} not found — sitemap will only contain home")

    sitemap_xml = _build_sitemap(urls)
    (dist / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")

    robots_txt = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n"
    )
    (dist / "robots.txt").write_text(robots_txt, encoding="utf-8")

    print(f"Wrote sitemap.xml with {len(urls)} URLs and robots.txt")


def _build_sitemap(urls: list[tuple[str, str, str, str]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, lastmod, changefreq, priority in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(loc)}</loc>")
        lines.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
        lines.append(f"    <changefreq>{escape(changefreq)}</changefreq>")
        lines.append(f"    <priority>{escape(priority)}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dist-dir>")
        sys.exit(1)
    generate(sys.argv[1])
