"""
Parser for the e-Gov API v2 JSON tree format.
Each node: {"tag": str, "attr": dict, "children": list[str | node]}
"""
from __future__ import annotations
from .exceptions import XMLParseError
from .models import (
    LawDocument, Chapter, Section, Article, Paragraph, Item, SubItem
)


_SKIP_TAGS = {"TableStruct", "Fig", "ArithFormula", "QuoteStruct", "TOC"}
_PLACEHOLDER = "[表・図省略]"


def parse_law_tree(tree: dict, metadata: dict | None = None) -> LawDocument:
    """
    Parse the e-Gov API v2 JSON tree into a LawDocument.
    metadata: optional dict from get_law_data() with promulgation_date, law_type, etc.
    """
    if tree.get("tag") != "Law":
        raise XMLParseError(f"予期しないルート要素: {tree.get('tag')}")

    law_num = _child_text(tree, "LawNum") or ""
    attr = tree.get("attr", {})

    body = _find(tree, "LawBody")
    if body is None:
        raise XMLParseError("LawBody 要素が見つかりません")

    law_title = _child_text(body, "LawTitle") or ""

    # Use clean metadata from API if available; fallback to tree attributes
    if metadata:
        promulgation_date = metadata.get("promulgation_date")
        law_type = metadata.get("law_type", attr.get("LawType", ""))
        law_num = metadata.get("law_num") or law_num
        law_title = metadata.get("law_title_from_api") or law_title
    else:
        promulgation_date = None
        law_type = attr.get("LawType", "")

    chapters: list[Chapter] = []

    main = _find(body, "MainProvision")
    if main is not None:
        chapters.extend(_parse_main_provision(main))

    # 各 SupplProvision を Section として保持（ラベル付き）
    # SupplProvisionLabel テキスト自体は全件「附　則」のことが多く、
    # 制定/改正の区別は AmendLawNum 属性（改正附則のみ存在）で行う
    suppl_sections: list[Section] = []
    for idx, suppl in enumerate(_find_all(body, "SupplProvision")):
        label_text = _child_text(suppl, "SupplProvisionLabel") or "附則"
        amend_num = suppl.get("attr", {}).get("AmendLawNum", "")
        if amend_num:
            # 改正附則: "附　則（令和○年...法律第○号）" 形式にする
            label_text = f"{label_text}（{amend_num}）"
        # AmendLawNum なし → 制定附則（"附　則" のまま）
        articles = _collect_suppl_articles(suppl)
        if articles:
            suppl_sections.append(
                Section(num=str(idx), title=label_text, articles=articles)
            )
    if suppl_sections:
        chapters.append(
            Chapter(num="附則", title="附　則", sections=suppl_sections, articles=[])
        )

    law_id = attr.get("LawId", "")

    return LawDocument(
        law_id=law_id,
        law_num=law_num,
        law_title=law_title,
        law_type=law_type,
        promulgation_date=promulgation_date,
        chapters=chapters,
    )


def _parse_main_provision(main: dict) -> list[Chapter]:
    chapters: list[Chapter] = []

    # Case 1: Part (編) 構造 — 所得税法・法人税法など
    part_els = _find_all(main, "Part")
    if part_els:
        for part_el in part_els:
            part_num = part_el.get("attr", {}).get("Num", "")
            part_title = _child_text(part_el, "PartTitle") or f"第{part_num}編"
            chapter_els = _find_all(part_el, "Chapter")
            if chapter_els:
                # 通常ケース: Part 内の Chapter を既存 _parse_chapter で処理
                for ch_el in chapter_els:
                    chapters.append(_parse_chapter(ch_el))
            else:
                # 例外ケース: Chapter なしで Article が直下（所得税法 第六編 など）
                articles = [_parse_article(a) for a in _find_all(part_el, "Article")]
                if articles:
                    chapters.append(Chapter(num=part_num, title=part_title,
                                            sections=[], articles=articles))
        return chapters

    # Case 2: Chapter が直下にある（消費税法・相続税法など）
    chapter_els = _find_all(main, "Chapter")
    if chapter_els:
        for ch_el in chapter_els:
            chapters.append(_parse_chapter(ch_el))
        return chapters

    # Case 3: Article が直下にある（省令など）
    articles = [_parse_article(a) for a in _find_all(main, "Article")]
    if articles:
        chapters.append(Chapter(num="0", title="", articles=articles))
    return chapters


def _parse_chapter(ch_el: dict) -> Chapter:
    num = ch_el.get("attr", {}).get("Num", "")
    title = _child_text(ch_el, "ChapterTitle") or f"第{num}章"

    sections: list[Section] = []
    articles: list[Article] = []

    for child in _elements(ch_el):
        tag = child.get("tag", "")
        if tag == "Section":
            sections.append(_parse_section(child))
        elif tag == "Article":
            articles.append(_parse_article(child))

    return Chapter(num=num, title=title, sections=sections, articles=articles)


def _parse_section(sec_el: dict) -> Section:
    num = sec_el.get("attr", {}).get("Num", "")
    title = _child_text(sec_el, "SectionTitle") or f"第{num}節"
    articles = [_parse_article(a) for a in _find_all(sec_el, "Article")]
    return Section(num=num, title=title, articles=articles)


def _parse_article(art_el: dict) -> Article:
    num = art_el.get("attr", {}).get("Num", "")
    caption = _child_text(art_el, "ArticleCaption")
    art_title = _child_text(art_el, "ArticleTitle") or f"第{num}条"
    paragraphs = [_parse_paragraph(p) for p in _find_all(art_el, "Paragraph")]
    return Article(num=art_title, caption=caption, paragraphs=paragraphs)


def _parse_paragraph(para_el: dict) -> Paragraph:
    num_node = _find(para_el, "ParagraphNum")
    num = ""
    if num_node is not None:
        t = _all_text(num_node).strip()
        if t:
            num = t

    sent_node = _find(para_el, "ParagraphSentence")
    text = _extract_text(sent_node) if sent_node else ""

    items = [_parse_item(i) for i in _find_all(para_el, "Item")]
    return Paragraph(num=num, text=text, items=items)


def _parse_item(item_el: dict) -> Item:
    num = _all_text(_find(item_el, "ItemTitle") or {}).strip() or item_el.get("attr", {}).get("Num", "")
    sent_node = _find(item_el, "ItemSentence")
    text = _extract_text(sent_node) if sent_node else ""

    sub_items: list[SubItem] = []
    for child in _elements(item_el):
        tag = child.get("tag", "")
        if tag.startswith("Subitem"):
            sub_num_node = _find(child, f"{tag}Title")
            sub_num = _all_text(sub_num_node or {}).strip()
            sub_sent_node = _find(child, f"{tag}Sentence")
            sub_text = _extract_text(sub_sent_node) if sub_sent_node else ""
            sub_items.append(SubItem(num=sub_num, text=sub_text))

    return Item(num=num, text=text, sub_items=sub_items)


def _collect_suppl_articles(suppl_el: dict) -> list[Article]:
    """Collect all articles from a SupplProvision element (flattened)."""
    articles: list[Article] = []
    for child in _elements(suppl_el):
        tag = child.get("tag", "")
        if tag == "Article":
            articles.append(_parse_article(child))
        elif tag == "Chapter":
            for art in _find_all(child, "Article"):
                articles.append(_parse_article(art))
    return articles


# ── Tree traversal helpers ──────────────────────────────────────────────────

def _elements(node: dict) -> list[dict]:
    """Return only element children (dicts) of node, skipping text nodes."""
    return [c for c in node.get("children", []) if isinstance(c, dict)]


def _find(node: dict, tag: str) -> dict | None:
    for child in node.get("children", []):
        if isinstance(child, dict) and child.get("tag") == tag:
            return child
    return None


def _find_all(node: dict, tag: str) -> list[dict]:
    return [c for c in node.get("children", []) if isinstance(c, dict) and c.get("tag") == tag]


def _child_text(node: dict, tag: str) -> str | None:
    child = _find(node, tag)
    if child is None:
        return None
    t = _all_text(child).strip()
    return t if t else None


def _all_text(node: dict | str) -> str:
    """Recursively collect all text in a node."""
    if isinstance(node, str):
        return node
    parts: list[str] = []
    for child in node.get("children", []):
        if isinstance(child, str):
            parts.append(child)
        elif isinstance(child, dict):
            if child.get("tag") in _SKIP_TAGS:
                parts.append(_PLACEHOLDER)
            else:
                parts.append(_all_text(child))
    return "".join(parts)


def _extract_text(node: dict) -> str:
    """Extract displayable text from a sentence container node."""
    return _all_text(node).strip()
