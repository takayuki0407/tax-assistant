"""Convert scraped 通達 pages to Markdown (single file per 通達)."""
from __future__ import annotations

import re
from datetime import date


def _safe_base(s: str, max_bytes: int = 200) -> str:
    """Replace unsafe chars, truncate to max_bytes UTF-8."""
    safe = re.sub(r'[\\/:*?"<>|　\s]', "_", s)
    encoded = safe.encode("utf-8")
    if len(encoded) <= max_bytes:
        return safe
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + "…"


def generate_tsutatsu_markdown(title: str, pages: list[dict]) -> str:
    """
    Convert scraped 通達 pages to a single Markdown string.
    Always returns one file (NotebookLM source = 1 通達).
    """
    lines: list[str] = [
        f"# {title}",
        "",
        f"**取得日**: {date.today().isoformat()}  ",
        "**出典**: 国税庁 (https://www.nta.go.jp)  ",
        "",
        "---",
        "",
    ]

    for page in pages:
        for item in page.get("items", []):
            _render_item(item, lines)

    return "\n".join(lines)


def tsutatsu_filename(title: str) -> str:
    return f"{_safe_base(title)}.md"


# ── Rendering ─────────────────────────────────────────────────────────────────

def _render_item(item: dict, lines: list[str]) -> None:
    t = item.get("type")

    if t == "heading":
        level = min(item.get("level", 3), 4)
        text = item.get("text", "").strip()
        if text:
            lines.append("#" * level + " " + text)
            lines.append("")

    elif t == "article":
        num = item.get("num", "")
        caption = item.get("caption")
        body = item.get("body", "")
        heading = f"#### {num}"
        if caption:
            heading += f"　（{caption}）"
        lines.append(heading)
        lines.append("")
        if body:
            lines.append(body)
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

    elif t == "table":
        md = item.get("markdown", "").strip()
        if md:
            lines.append(md)
            lines.append("")
