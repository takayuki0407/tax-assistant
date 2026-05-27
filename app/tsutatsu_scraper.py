"""Scraper for NTA (国税庁) 基本通達 pages."""
from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.nta.go.jp"
REQUEST_DELAY = 0.4  # seconds between requests (be polite)
TIMEOUT = 30.0

CATALOG: dict[str, dict] = {
    # ── 基本通達 ────────────────────────────────────────────────────────────
    "hojin": {
        "title": "法人税基本通達",
        "toc_path": "/law/tsutatsu/kihon/hojin/01.htm",
        "content_prefix": "/law/tsutatsu/kihon/hojin/",
    },
    "shotoku": {
        "title": "所得税基本通達",
        "toc_path": "/law/tsutatsu/kihon/shotoku/01.htm",
        "content_prefix": "/law/tsutatsu/kihon/shotoku/",
    },
    "shohi": {
        "title": "消費税法基本通達",
        "toc_path": "/law/tsutatsu/kihon/shohi/01.htm",
        "content_prefix": "/law/tsutatsu/kihon/shohi/",
    },
    "sozoku": {
        "title": "相続税法基本通達",
        "toc_path": "/law/tsutatsu/kihon/sisan/sozoku2/01.htm",
        "content_prefix": "/law/tsutatsu/kihon/sisan/sozoku2/",
    },
    "hyoka": {
        "title": "財産評価基本通達",
        "toc_path": "/law/tsutatsu/kihon/sisan/hyoka_new/01.htm",
        "content_prefix": "/law/tsutatsu/kihon/sisan/hyoka_new/",
    },
    "renketsu": {
        "title": "連結納税基本通達",
        "toc_path": "/law/tsutatsu/kihon/renketsu/01.htm",
        "content_prefix": "/law/tsutatsu/kihon/renketsu/",
    },
    # ── 措置法通達（deep_toc: 2段階クロール）───────────────────────────────
    # index ページが各通達の 01.htm のみにリンクしているため、
    # 01.htm から更にコンテンツページを収集する必要がある
    "sochiho_hojin": {
        "title": "法人税法関係措置法通達",
        "toc_path": "/law/tsutatsu/kobetsu/hojin/sochiho/sotihou.htm",
        "content_prefix": "/law/tsutatsu/kobetsu/hojin/sochiho/",
        "deep_toc": True,
    },
    "sochiho_shotoku": {
        "title": "所得税法関係措置法通達",
        "toc_path": "/law/tsutatsu/kobetsu/shotoku/sochiho/sotihou.htm",
        "content_prefix": "/law/tsutatsu/kobetsu/shotoku/sochiho/",
        "deep_toc": True,
    },
    "sochiho_sozoku": {
        "title": "相続税・贈与税法関係措置法通達",
        "toc_path": "/law/tsutatsu/kobetsu/sozoku/sochiho/sotihou.htm",
        "content_prefix": "/law/tsutatsu/kobetsu/sozoku/sochiho/",
        "deep_toc": True,
    },
}

# Hyphen variants used in NTA 通達 article numbers:
#   U+002D  -   HYPHEN-MINUS
#   U+2212  −   MINUS SIGN  (most common in NTA pages)
#   U+FF0D  －  FULLWIDTH HYPHEN-MINUS
#   U+2010  ‐   HYPHEN
_H = r"[-−－‐]"

# Article number pattern: e.g. 1-1-1  1−1−1  3-5  14-1-2
_ART_NUM_RE = re.compile(
    rf"^(\d+{_H}\d+(?:{_H}\d+)?)[　\s]*(（[^）]*）)?[　\s]*(.*)",
    re.DOTALL,
)
# Detect article number prefix in a <strong> tag
_STRONG_NUM_RE = re.compile(rf"^\d+{_H}\d+")

# Subdirectory exclusions in TOC links
_EXCLUDE_DIRS = {"zenbun", "menu", "index"}


class TsutatsuError(Exception):
    pass


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; TaxAssistantBot/1.0; "
                "+https://github.com/takayuki0407/tax-assistant)"
            )
        },
        timeout=TIMEOUT,
        follow_redirects=True,
    )


async def _fetch(path: str, client: httpx.AsyncClient) -> bytes:
    url = BASE_URL + path
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPStatusError as e:
        raise TsutatsuError(f"HTTP {e.response.status_code}: {url}") from e
    except httpx.RequestError as e:
        raise TsutatsuError(f"通信エラー: {url}") from e


def _decode(content: bytes) -> str:
    """Try Shift-JIS first, then CP932, UTF-8."""
    for enc in ("shift_jis", "cp932", "utf-8"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


# ── TOC parsing ───────────────────────────────────────────────────────────────

def _extract_toc_links(html: str, prefix: str) -> list[str]:
    """Return ordered list of content-page paths extracted from the TOC page."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    result: list[str] = []

    for a in soup.find_all("a", href=True):
        raw: str = a["href"].split("#")[0].strip()

        # Must be an absolute path under the content prefix
        if not raw.startswith(prefix):
            continue

        # Normalise: ensure leading slash
        href = raw if raw.startswith("/") else "/" + raw

        # Skip the TOC page itself (e.g. /hojin/01.htm)
        tail = href[len(prefix):]           # e.g. "01.htm" or "01/01_01.htm"
        if "/" not in tail:                 # top-level file → skip
            continue

        # Skip excluded directories
        first_dir = tail.split("/")[0]
        if first_dir in _EXCLUDE_DIRS:
            continue

        if href not in seen:
            seen.add(href)
            result.append(href)

    return result


# ── Content parsing ───────────────────────────────────────────────────────────

def _clean_text(s: str) -> str:
    """Collapse whitespace, remove leading/trailing blanks."""
    return re.sub(r"[ \t\r\n]+", " ", s).strip()


_CHAPTER_RE = re.compile(r"^第\d+章(?:の\d+)?[　\s]")   # 第1章, 第2章の2 etc.
_SECTION_RE = re.compile(r"^第\d+節(?:の\d+)?[　\s]")   # 第1節, 第2節の2 etc.
_SUBITEM_RE = re.compile(r"^\(\d+\)[　\s]|^（\d+）[　\s]")  # (1), （1） sub-items


def _extract_content(html: str) -> list[dict]:
    """
    Parse one 通達 content page.

    NTA HTML conventions (observed):
    - Chapter titles often appear as <p> matching 第N章
    - Section headings appear as <h1>/<h2>/<h3> depending on page
    - Article captions like （見出し語） appear as <h2>/<h3>
      immediately before the article <p>
    - Article text: <p> starting with "N−N−N　..." (U+2212 minus)
    - Sub-items: <p> starting with (1) / （1）

    Returns list of items:
      {"type": "heading",  "level": 2|3|4, "text": str}
      {"type": "article",  "num": str, "caption": str|None, "body": str}
      {"type": "para",     "text": str}
      {"type": "list",     "items": list[str]}
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    main = (
        soup.find(id=re.compile(r"main|content|body", re.I))
        or soup.find("div", class_=re.compile(r"main|content", re.I))
        or soup.body
        or soup
    )

    items: list[dict] = []
    pending_caption: str | None = None   # H captured before an article
    pending_sublist: list[str] = []      # (1)(2)… items for current article
    pending_list: list[str] | None = None  # <li> accumulator

    def _flush_sublist() -> None:
        """Attach accumulated sub-items as list to last article."""
        nonlocal pending_sublist
        if pending_sublist and items:
            items.append({"type": "list", "items": list(pending_sublist)})
        pending_sublist = []

    def _flush_li() -> None:
        nonlocal pending_list
        if pending_list:
            items.append({"type": "list", "items": list(pending_list)})
            pending_list = None

    for elem in main.find_all(
        ["h1", "h2", "h3", "h4", "h5", "p", "li", "dt", "dd", "table"],
        recursive=True,
    ):
        tag = elem.name

        # ── <li> accumulation ─────────────────────────────────
        if tag == "li":
            text = _clean_text(elem.get_text())
            if text:
                if pending_list is None:
                    pending_list = []
                pending_list.append(text)
            continue

        _flush_li()

        # ── Table placeholder ─────────────────────────────────
        if tag == "table":
            _flush_sublist()
            items.append({"type": "para", "text": "[表省略]"})
            pending_caption = None
            continue

        # ── Headings ──────────────────────────────────────────
        if tag in ("h1", "h2", "h3", "h4", "h5"):
            text = _clean_text(elem.get_text())
            if not text:
                continue
            # Parenthetical captions like （法人でない社団の範囲） or (法人でない…)
            # → store as pending_caption for the next article
            if re.match(r"^[（(]", text):
                _flush_sublist()
                pending_caption = text.strip("（）()")
            else:
                # Structural heading: emit and clear caption state
                _flush_sublist()
                pending_caption = None
                level = int(tag[1])
                # Remap NTA heading levels to MD levels (H1→##, H2→###, H3+→####)
                md_level = min(level + 1, 4)
                items.append({"type": "heading", "level": md_level, "text": text})
            continue

        # ── Definition terms ──────────────────────────────────
        if tag in ("dt", "dd"):
            text = _clean_text(elem.get_text())
            if text:
                items.append({"type": "para", "text": text})
            continue

        # ── Paragraphs ────────────────────────────────────────
        if tag == "p":
            full_text = _clean_text(elem.get_text())
            if not full_text:
                continue

            # ① Chapter/section pattern in <p> → heading
            if _CHAPTER_RE.match(full_text):
                _flush_sublist()
                pending_caption = None
                items.append({"type": "heading", "level": 2, "text": full_text})
                continue
            if _SECTION_RE.match(full_text):
                _flush_sublist()
                pending_caption = None
                items.append({"type": "heading", "level": 3, "text": full_text})
                continue

            # ② Sub-item pattern (1) / （1） → defer as list
            if _SUBITEM_RE.match(full_text):
                pending_sublist.append(full_text)
                continue

            # ③ Try article number detection via <strong> child
            article_num: str | None = None
            for strong in elem.find_all("strong"):
                s = _clean_text(strong.get_text())
                if _STRONG_NUM_RE.match(s):
                    article_num = s.rstrip("　 　")
                    break

            # ④ Try direct text match
            if article_num is None:
                m = _ART_NUM_RE.match(full_text)
                if m:
                    article_num = m.group(1)

            if article_num:
                _flush_sublist()
                # Extract body: text after the number
                rest = full_text[len(article_num):].lstrip("　 　")
                # Inline caption in （）?
                inline_cap_m = re.match(r"^（([^）]*)）[　\s　]*", rest)
                if inline_cap_m:
                    cap = inline_cap_m.group(1)
                    body = rest[inline_cap_m.end():]
                else:
                    cap = pending_caption   # use H-tag caption from previous element
                    body = rest

                items.append({
                    "type": "article",
                    "num": article_num,
                    "caption": cap or None,
                    "body": _clean_text(body),
                })
                pending_caption = None   # consumed
            else:
                _flush_sublist()
                pending_caption = None
                items.append({"type": "para", "text": full_text})

    _flush_sublist()
    _flush_li()

    # Remove stray navigation lists that appear before the first article/heading
    # (NTA pages have breadcrumb <li> elements outside <nav>)
    _NAV_WORDS = {"ホーム", "サイトマップ", "前へ", "次へ", "トップ", "Home", "Top"}
    first_content = next(
        (i for i, it in enumerate(items)
         if it["type"] == "article"
         or (it["type"] == "heading" and it["level"] <= 3)),
        len(items),
    )
    items = [
        it for i, it in enumerate(items)
        if i >= first_content
        or it["type"] != "list"
        or not any(w in " ".join(it["items"]) for w in _NAV_WORDS)
    ]

    return items


# ── Main scrape generator ─────────────────────────────────────────────────────

async def scrape_tsutatsu(key: str) -> AsyncGenerator[dict, None]:
    """
    Async generator.  Yields dicts:
      {"type": "start",    "total": int, "title": str}
      {"type": "progress", "done":  int, "total": int, "section": str}
      {"type": "sections", "title": str, "pages": list[dict]}
      {"type": "error",    "message": str}
    """
    if key not in CATALOG:
        yield {"type": "error", "message": f"不明な通達キー: {key}"}
        return

    info = CATALOG[key]
    title = info["title"]
    prefix = info["content_prefix"]
    deep_toc = info.get("deep_toc", False)

    async with _make_client() as client:
        # ── Fetch TOC ──────────────────────────────────────────
        try:
            toc_bytes = await _fetch(info["toc_path"], client)
        except TsutatsuError as e:
            yield {"type": "error", "message": str(e)}
            return

        toc_html = _decode(toc_bytes)

        if deep_toc:
            # 2段階クロール: メインTOC → サブTOC(各通達の01.htm) → コンテンツページ
            sub_toc_paths = _extract_toc_links(toc_html, prefix)
            links: list[str] = []
            seen_content: set[str] = set(sub_toc_paths)  # サブTOCページ自体は除外
            for sub_path in sub_toc_paths:
                try:
                    sub_bytes = await _fetch(sub_path, client)
                    sub_html = _decode(sub_bytes)
                    for link in _extract_toc_links(sub_html, prefix):
                        if link not in seen_content:
                            seen_content.add(link)
                            links.append(link)
                    await asyncio.sleep(REQUEST_DELAY)
                except TsutatsuError:
                    pass
        else:
            links = _extract_toc_links(toc_html, prefix)

        if not links:
            yield {
                "type": "error",
                "message": f"目次ページからリンクを取得できませんでした: {info['toc_path']}",
            }
            return

        total = len(links)
        yield {"type": "start", "total": total, "title": title}

        # ── Fetch each content page ───────────────────────────
        all_pages: list[dict] = []
        for i, path in enumerate(links):
            section_label = path.split("/")[-1].replace(".htm", "")
            yield {
                "type": "progress",
                "done": i,
                "total": total,
                "section": section_label,
            }

            try:
                page_bytes = await _fetch(path, client)
                page_html = _decode(page_bytes)
                content_items = _extract_content(page_html)
            except TsutatsuError:
                content_items = []

            all_pages.append({"path": path, "items": content_items})
            await asyncio.sleep(REQUEST_DELAY)

        yield {"type": "progress", "done": total, "total": total, "section": "変換中"}
        yield {"type": "sections", "title": title, "pages": all_pages}
