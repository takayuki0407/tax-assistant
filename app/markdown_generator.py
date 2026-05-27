from __future__ import annotations
import re
from datetime import date
from .models import LawDocument, Chapter, Section, Article, Paragraph, Item

MAX_SINGLE_FILE_CHARS = 490_000
# 附則に多数の SupplProvision がある場合（所得税法は 351 件）、
# 目次に全件展開すると読みにくくなるため、この閾値を超えたら章レベルのみ表示する
TOC_SECTION_EXPAND_LIMIT = 30


def generate_markdown(doc: LawDocument) -> str:
    lines: list[str] = []

    # Header
    lines.append(f"# {doc.law_title}")
    lines.append("")
    if doc.law_num:
        lines.append(f"**法令番号**: {doc.law_num}  ")
    if doc.law_type:
        lines.append(f"**法令種別**: {doc.law_type}  ")
    if doc.promulgation_date:
        lines.append(f"**公布日**: {doc.promulgation_date}  ")
    if doc.last_amended:
        lines.append(f"**最終改正**: {doc.last_amended}  ")
    lines.append(f"**取得日**: {date.today().isoformat()}  ")
    lines.append("**出典**: e-Gov法令検索 (https://laws.e-gov.go.jp)  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Table of contents
    lines.append("## 目次")
    lines.append("")
    for ch in doc.chapters:
        if ch.num == "0":
            continue
        lines.append(f"- [{ch.title}](#{_anchor(ch.title)})")
        if len(ch.sections) <= TOC_SECTION_EXPAND_LIMIT:
            for sec in ch.sections:
                lines.append(f"  - [{sec.title}](#{_anchor(sec.title)})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Body
    for ch in doc.chapters:
        _render_chapter(ch, lines)

    return "\n".join(lines)


def generate_split_markdown(doc: LawDocument) -> list[tuple[str, str]]:
    """Returns list of (filename, content), greedily packing chapters into files
    up to MAX_SINGLE_FILE_CHARS each to minimise the total file count."""

    # Step 1: Render each chapter body to a string
    rendered: list[tuple[str, str]] = []
    for ch in doc.chapters:
        body_lines: list[str] = []
        _render_chapter(ch, body_lines)
        title = ch.title if ch.num != "0" else doc.law_title
        rendered.append((title, "\n".join(body_lines)))

    # Step 2: Greedy bin-pack chapters into files ≤ MAX_SINGLE_FILE_CHARS
    HEADER_COST = 300  # approximate per-file header overhead in chars
    bins: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_size = HEADER_COST

    for title, body in rendered:
        item_size = len(body) + 4  # +4 for blank separator between chapters
        if current and current_size + item_size > MAX_SINGLE_FILE_CHARS:
            bins.append(current)
            current = [(title, body)]
            current_size = HEADER_COST + item_size
        else:
            current.append((title, body))
            current_size += item_size
    if current:
        bins.append(current)

    # Step 3: Produce final file content for each bin
    files: list[tuple[str, str]] = []
    seen_filenames: dict[str, int] = {}
    total_bins = len(bins)

    for i, bin_items in enumerate(bins):
        lines: list[str] = []
        first_title = bin_items[0][0]
        last_title = bin_items[-1][0]
        file_label = first_title if len(bin_items) == 1 else f"{first_title}〜{last_title}"

        lines.append(f"# {doc.law_title} — {file_label}")
        lines.append("")
        lines.append(f"**法令番号**: {doc.law_num}  ")
        lines.append(f"**取得日**: {date.today().isoformat()}  ")
        lines.append("**出典**: e-Gov法令検索 (https://laws.e-gov.go.jp)  ")
        if total_bins > 1:
            lines.append(f"**ファイル**: {i + 1} / {total_bins}  ")
        lines.append("")
        lines.append("---")
        lines.append("")

        for _, body in bin_items:
            lines.append(body)

        safe_label = re.sub(r'[\\/:*?"<>|　\s]', "_", file_label)
        safe_law = re.sub(r'[\\/:*?"<>|　\s]', "_", doc.law_title)
        base = f"{safe_law}_{safe_label}"
        encoded = base.encode("utf-8")
        if len(encoded) > 200:
            base = encoded[:200].decode("utf-8", errors="ignore") + "…"

        filename = f"{base}.md"
        if filename in seen_filenames:
            seen_filenames[filename] += 1
            filename = f"{base}_{seen_filenames[filename]}.md"
        else:
            seen_filenames[filename] = 1

        files.append((filename, "\n".join(lines)))

    return files


def count_articles(doc: LawDocument) -> int:
    count = 0
    for ch in doc.chapters:
        count += len(ch.articles)
        for sec in ch.sections:
            count += len(sec.articles)
    return count


def _render_chapter(ch: Chapter, lines: list[str]) -> None:
    if ch.num != "0":
        lines.append(f"## {ch.title}")
        lines.append("")

    for art in ch.articles:
        _render_article(art, lines)

    for sec in ch.sections:
        _render_section(sec, lines)


def _render_section(sec: Section, lines: list[str]) -> None:
    lines.append(f"### {sec.title}")
    lines.append("")
    for art in sec.articles:
        _render_article(art, lines)


def _render_article(art: Article, lines: list[str]) -> None:
    heading = art.num
    if art.caption:
        heading = f"{art.num}　{art.caption}"
    lines.append(f"#### {heading}")
    lines.append("")

    for para in art.paragraphs:
        _render_paragraph(para, lines)

    lines.append("")


def _render_paragraph(para: Paragraph, lines: list[str]) -> None:
    if para.num:
        lines.append(f"**{para.num}**　{para.text}")
    else:
        lines.append(para.text)

    for item in para.items:
        _render_item(item, lines, indent=0)

    lines.append("")


def _render_item(item: Item, lines: list[str], indent: int) -> None:
    prefix = "　" * (indent + 1)  # 全角スペースでインデント
    if item.text:
        lines.append(f"{prefix}{item.num}　{item.text}")
    else:
        lines.append(f"{prefix}{item.num}")

    for sub in item.sub_items:
        sub_prefix = "　" * (indent + 2)
        lines.append(f"{sub_prefix}{sub.num}　{sub.text}")


def _anchor(text: str) -> str:
    """Convert heading text to a GitHub-Markdown-compatible anchor."""
    text = text.strip()
    # Remove punctuation that GitHub strips, keep Japanese characters
    text = re.sub(r'[（）()「」『』【】、。・]', "", text)
    text = text.replace("　", "-").replace(" ", "-")
    return text.lower()
