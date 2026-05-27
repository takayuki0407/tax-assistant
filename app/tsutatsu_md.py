"""Convert scraped 通達 pages to Markdown."""
from __future__ import annotations

import re
from datetime import date

MAX_CHARS_PER_FILE = 350_000


def _safe_base(s: str, max_bytes: int = 200) -> str:
    """Replace unsafe chars, truncate to max_bytes UTF-8."""
    safe = re.sub(r'[\\/:*?"<>|　\s]', "_", s)
    encoded = safe.encode("utf-8")
    if len(encoded) <= max_bytes:
        return safe
    return encoded[:max_bytes].decode("utf-8", errors="ignore") + "…"


def generate_tsutatsu_markdown(
    title: str,
    pages: list[dict],
) -> list[tuple[str, str]]:
    """
    Convert scraped 通達 to (filename, markdown_content) pairs.
    Returns a single file if total chars <= MAX_CHARS_PER_FILE,
    otherwise splits by H2 chapter.
    """
    header_lines = _build_header(title)
    body_lines: list[str] = []

    for page in pages:
        for item in page.get("items", []):
            _render_item(item, body_lines)

    all_lines = header_lines + body_lines
    full_content = "\n".join(all_lines)

    safe_title = _safe_base(title)

    if len(full_content) <= MAX_CHARS_PER_FILE:
        return [(f"{safe_title}.md", full_content)]

    return _split_by_chapter(title, safe_title, header_lines, body_lines)


# ── Rendering ─────────────────────────────────────────────────────────────────

def _build_header(title: str) -> list[str]:
    return [
        f"# {title}",
        "",
        f"**取得日**: {date.today().isoformat()}  ",
        "**出典**: 国税庁 (https://www.nta.go.jp)  ",
        "",
        "---",
        "",
    ]


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


# ── Splitting ─────────────────────────────────────────────────────────────────

def _split_by_chapter(
    title: str,
    safe_title: str,
    header_lines: list[str],
    body_lines: list[str],
) -> list[tuple[str, str]]:
    """Split body at ## headings; prepend a mini-header to each chunk."""
    chunks: list[tuple[str, list[str]]] = []   # (chapter_name, lines)
    current_name = "前文"
    current_lines: list[str] = list(header_lines)

    for line in body_lines:
        if line.startswith("## "):
            # Save previous chunk
            if len("\n".join(current_lines)) > 200:   # skip near-empty chunks
                chunks.append((current_name, current_lines))
            current_name = line[3:].strip()
            current_lines = [
                f"# {title} — {current_name}",
                "",
                f"**出典**: 国税庁 (https://www.nta.go.jp)  ",
                "",
                "---",
                "",
                line,
            ]
        else:
            current_lines.append(line)

    if current_lines:
        chunks.append((current_name, current_lines))

    if not chunks:
        return [(f"{safe_title}.md", "\n".join(header_lines + body_lines))]

    result: list[tuple[str, str]] = []
    for ch_name, ch_lines in chunks:
        content = "\n".join(ch_lines)
        base = _safe_base(f"{safe_title}_{ch_name}")
        result.append((f"{base}.md", content))

    return result
