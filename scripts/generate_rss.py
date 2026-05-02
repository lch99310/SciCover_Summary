#!/usr/bin/env python3
"""
generate_rss.py — Emit ``feed.xml`` (Atom 1.0) into the build output.

Atom is preferred over RSS 2.0 because it has a stricter spec and clearer
i18n / datetime handling.  Most readers (Feedly, Inoreader, NetNewsWire)
support both transparently.

Items link to the static stub URL (``/article/{id}/``) so feed-reader users
land on a page with proper OG meta and a JS redirect into the SPA.

Usage (called during deploy, after OG-page generation):

    python3 scripts/generate_rss.py frontend/dist
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

SITE_URL = "https://lch99310.github.io/SciCover_Summary"
SITE_NAME = "SciCover Summary"
SITE_TAGLINE = (
    "AI-powered bilingual summaries of the latest Open Access research "
    "from Science, Nature, Cell, and leading social-science journals."
)
AUTHOR_NAME = "Chung-Hao Lee"
AUTHOR_URL = "https://lch99310.github.io/chunghao_lee/"
MAX_ITEMS = 20


def generate(dist_dir: str) -> None:
    dist = Path(dist_dir)
    index_file = dist / "data" / "index.json"

    if not index_file.exists():
        print(f"WARNING: {index_file} not found — skipping RSS generation")
        return

    index = json.loads(index_file.read_text(encoding="utf-8"))
    last_updated = index.get("lastUpdated") or _now_iso()
    articles = index.get("articles", [])[:MAX_ITEMS]

    items_xml: list[str] = []
    for entry in articles:
        article_id = entry.get("id", "")
        if not article_id:
            continue

        title_zh = entry.get("title_zh", "")
        title_en = entry.get("title_en", "")
        title = f"{title_zh} | {title_en}" if title_zh and title_en else (
            title_zh or title_en or article_id
        )
        journal = entry.get("journal", "")
        date = entry.get("date", "") or "1970-01-01"
        article_path = dist / "data" / entry.get("path", "")

        summary_zh = ""
        summary_en = ""
        if article_path.exists():
            try:
                article = json.loads(article_path.read_text(encoding="utf-8"))
                summary = article.get("coverStory", {}).get("summary", {})
                summary_zh = summary.get("zh", "")
                summary_en = summary.get("en", "")
            except (json.JSONDecodeError, OSError):
                pass

        snippet = summary_zh[:280] if summary_zh else summary_en[:300]
        url = f"{SITE_URL}/article/{article_id}/"
        published = _to_atom_date(date)

        items_xml.append(
            "  <entry>\n"
            f"    <id>{escape(url)}</id>\n"
            f"    <title>{escape(title)}</title>\n"
            f'    <link rel="alternate" type="text/html" href="{escape(url)}"/>\n'
            f"    <published>{escape(published)}</published>\n"
            f"    <updated>{escape(published)}</updated>\n"
            f"    <category term=\"{escape(journal)}\"/>\n"
            f"    <author><name>{escape(AUTHOR_NAME)}</name></author>\n"
            f"    <summary type=\"text\">{escape(snippet)}</summary>\n"
            "  </entry>"
        )

    feed_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="zh-Hant">\n'
        f"  <title>{escape(SITE_NAME)}</title>\n"
        f"  <subtitle>{escape(SITE_TAGLINE)}</subtitle>\n"
        f"  <link rel=\"alternate\" type=\"text/html\" href=\"{escape(SITE_URL)}/\"/>\n"
        f"  <link rel=\"self\" type=\"application/atom+xml\" href=\"{escape(SITE_URL)}/feed.xml\"/>\n"
        f"  <id>{escape(SITE_URL)}/</id>\n"
        f"  <updated>{escape(_to_atom_date(last_updated))}</updated>\n"
        "  <author>\n"
        f"    <name>{escape(AUTHOR_NAME)}</name>\n"
        f"    <uri>{escape(AUTHOR_URL)}</uri>\n"
        "  </author>\n"
        + "\n".join(items_xml)
        + "\n</feed>\n"
    )

    (dist / "feed.xml").write_text(feed_xml, encoding="utf-8")
    print(f"Wrote feed.xml with {len(items_xml)} entries")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_atom_date(value: str) -> str:
    """Coerce an ISO-ish date string to an Atom (RFC 3339) timestamp."""
    if not value:
        return _now_iso()
    try:
        # Accept full ISO 8601 (with offset) or bare YYYY-MM-DD.
        if len(value) == 10:
            dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return _now_iso()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dist-dir>")
        sys.exit(1)
    generate(sys.argv[1])
