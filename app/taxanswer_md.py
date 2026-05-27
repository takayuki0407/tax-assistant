"""Convert タックスアンサー articles to a single Markdown file."""
from __future__ import annotations

import re
from datetime import date


def generate_taxanswer_markdown(title: str, articles: list[dict]) -> str:
    """
    Convert a list of scraped タックスアンサー articles to Markdown.
    One file per tax category (NotebookLM source = 1 カテゴリ).
    """
    lines: list[str] = [
        f"# タックスアンサー {title}",
        "",
        f"**取得日**: {date.today().isoformat()}  ",
        "**出典**: 国税庁 タックスアンサー (https://www.nta.go.jp)  ",
        f"**記事数**: {len(articles)}件  ",
        "",
        "---",
        "",
    ]

    for article in articles:
        art_title = article.get("title", "").strip()
        if not art_title:
            continue

        lines.append(f"## {art_title}")
        lines.append("")

        for item in article.get("items", []):
            t = item.get("type", "")

            if t == "heading":
                level = min(item.get("level", 3), 4)
                text = item.get("text", "").strip()
                if text:
                    lines.append("#" * level + " " + text)
                    lines.append("")

            elif t == "para":
                text = item.get("text", "").strip()
                if text:
                    lines.append(text)
                    lines.append("")

            elif t == "list":
                for li in item.get("items", []):
                    lines.append(f"- {li}")
                lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def taxanswer_filename(title: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|　\s]', "_", title)
    encoded = safe.encode("utf-8")
    if len(encoded) > 200:
        safe = encoded[:200].decode("utf-8", errors="ignore") + "…"
    return f"タックスアンサー_{safe}.md"
