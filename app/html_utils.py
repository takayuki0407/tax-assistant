"""Shared HTML-to-Markdown utilities."""
from __future__ import annotations

import re

from bs4 import Tag


def table_to_markdown(table_elem: Tag) -> str:
    """Convert a BeautifulSoup <table> element to a Markdown table string.

    Handles:
    - <thead>/<tbody>/<tfoot> section elements
    - colspan expansion (fills spanned columns with empty cells)
    - Pipe character escaping in cell text

    Returns empty string if the table has no usable rows.
    """
    # ── Collect <tr> elements respecting section wrappers ────────────────
    all_tr: list[Tag] = []
    for section in table_elem.find_all(["thead", "tbody", "tfoot"], recursive=False):
        all_tr.extend(section.find_all("tr", recursive=False))
    if not all_tr:
        all_tr = table_elem.find_all("tr", recursive=False)
    if not all_tr:
        # Deep fallback for tables without section wrappers
        all_tr = table_elem.find_all("tr")

    # ── Build rows as lists of cell text ─────────────────────────────────
    rows_data: list[list[str]] = []
    for tr in all_tr:
        cells: list[str] = []
        for cell in tr.find_all(["th", "td"]):
            text = re.sub(r"[ \t\r\n]+", " ", cell.get_text()).strip()
            text = text.replace("|", "｜")           # escape Markdown pipe
            text = text.replace("\n", " ")
            colspan = max(1, _int_attr(cell, "colspan"))
            cells.append(text)
            for _ in range(colspan - 1):             # fill spanned columns
                cells.append("")
        if any(cells):
            rows_data.append(cells)

    if not rows_data:
        return ""

    max_cols = max(len(row) for row in rows_data)
    if max_cols == 0:
        return ""

    # Pad every row to the same width
    for row in rows_data:
        while len(row) < max_cols:
            row.append("")

    # ── Render Markdown table ─────────────────────────────────────────────
    sep = "| " + " | ".join(["---"] * max_cols) + " |"
    lines: list[str] = []
    lines.append("| " + " | ".join(rows_data[0]) + " |")
    lines.append(sep)
    for row in rows_data[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def _int_attr(tag: Tag, attr: str, default: int = 1) -> int:
    try:
        return int(tag.get(attr, default))
    except (ValueError, TypeError):
        return default
