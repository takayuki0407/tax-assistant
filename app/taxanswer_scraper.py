"""Scraper for NTA タックスアンサー (Tax Answer) pages."""
from __future__ import annotations

import asyncio
import re
from typing import AsyncGenerator

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.nta.go.jp"
INDEX_PATH = "/taxes/shiraberu/taxanswer/code/index.htm"
REQUEST_DELAY = 0.3   # seconds between requests
TIMEOUT = 30.0

# URL subdirectory key → {title, article_count}
# article_count measured from index page (May 2026)
TAXANSWER_CATALOG: dict[str, dict] = {
    "shotoku": {"title": "所得税",              "article_count": 284},
    "gensen":  {"title": "源泉所得税",          "article_count": 70},
    "joto":    {"title": "譲渡所得",            "article_count": 74},
    "sozoku":  {"title": "相続税",              "article_count": 74},
    "zoyo":    {"title": "贈与税",              "article_count": 28},
    "hojin":   {"title": "法人税",              "article_count": 115},
    "shohi":   {"title": "消費税",              "article_count": 116},
    "inshi":   {"title": "印紙税・その他の国税", "article_count": 30},
    "hyoka":   {"title": "財産の評価",          "article_count": 29},
    "saigai":  {"title": "災害を受けたら",      "article_count": 18},
    "hotei":   {"title": "法定調書",            "article_count": 14},
    "fufuku":  {"title": "課税に不服なとき",    "article_count": 2},
}


class TaxAnswerError(Exception):
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
        raise TaxAnswerError(f"HTTP {e.response.status_code}: {url}") from e
    except httpx.RequestError as e:
        raise TaxAnswerError(f"通信エラー: {url}") from e


def _decode(content: bytes) -> str:
    for enc in ("shift_jis", "cp932", "utf-8"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


# ── Index parsing ─────────────────────────────────────────────────────────────

def _get_article_urls(index_html: str, category_key: str) -> list[str]:
    """Return ordered list of article page paths for the given category."""
    soup = BeautifulSoup(index_html, "html.parser")
    prefix = f"/taxes/shiraberu/taxanswer/{category_key}/"
    seen: set[str] = set()
    result: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        if href.startswith(prefix) and href.endswith(".htm") and href not in seen:
            seen.add(href)
            result.append(href)
    return result


# ── Article content extraction ────────────────────────────────────────────────

_NAV_WORDS = frozenset({"ホーム", "サイトマップ", "前へ", "次へ", "トップ", "Home"})


def _clean_text(s: str) -> str:
    return re.sub(r"[ \t\r\n]+", " ", s).strip()


def _extract_article(html: str) -> dict | None:
    """
    Parse a single タックスアンサー article page.

    Returns:
      {"title": str, "items": list[dict]}
    where items are:
      {"type": "heading", "level": int, "text": str}
      {"type": "para",    "text": str}
      {"type": "list",    "items": list[str]}
    """
    soup = BeautifulSoup(html, "html.parser")
    for t in soup.find_all(["script", "style", "nav", "footer", "header"]):
        t.decompose()

    # Article title from <h1>
    h1 = soup.find("h1")
    title = _clean_text(h1.get_text()) if h1 else ""
    if not title:
        page_title = soup.find("title")
        title = _clean_text(page_title.get_text()).split("｜")[0] if page_title else ""
    if not title:
        return None

    # Locate main content area
    main = (
        soup.find(id=re.compile(r"main|content|body", re.I))
        or soup.find("div", class_=re.compile(r"main|content", re.I))
        or soup.body
        or soup
    )

    items: list[dict] = []
    li_buf: list[str] = []

    def _flush_li() -> None:
        if li_buf:
            items.append({"type": "list", "items": list(li_buf)})
            li_buf.clear()

    for elem in main.find_all(
        ["h2", "h3", "h4", "p", "li", "dt", "dd"],
        recursive=True,
    ):
        tag = elem.name
        text = _clean_text(elem.get_text())
        if not text:
            continue

        if tag == "li":
            li_buf.append(text)
            continue

        _flush_li()

        if tag in ("h2", "h3", "h4"):
            # Skip heading that is the same as h1 title
            if text == title:
                continue
            level = {"h2": 3, "h3": 4, "h4": 4}[tag]
            items.append({"type": "heading", "level": level, "text": text})
        elif tag in ("p", "dt", "dd"):
            items.append({"type": "para", "text": text})

    _flush_li()

    # Drop leading navigation lists
    first_real = next(
        (i for i, it in enumerate(items)
         if it["type"] == "heading"
         or (it["type"] == "para" and not any(w in it["text"] for w in _NAV_WORDS))),
        0,
    )
    items = items[first_real:]

    return {"title": title, "items": items}


# ── Main scrape generator ─────────────────────────────────────────────────────

async def scrape_taxanswer(key: str) -> AsyncGenerator[dict, None]:
    """
    Async generator.  Yields dicts:
      {"type": "start",    "total": int, "title": str}
      {"type": "progress", "done":  int, "total": int, "article": str}
      {"type": "articles", "title": str, "articles": list[dict]}
      {"type": "error",    "message": str}
    """
    if key not in TAXANSWER_CATALOG:
        yield {"type": "error", "message": f"不明なカテゴリキー: {key}"}
        return

    title = TAXANSWER_CATALOG[key]["title"]

    async with _make_client() as client:
        # ── Fetch index page ───────────────────────────────────
        try:
            index_bytes = await _fetch(INDEX_PATH, client)
        except TaxAnswerError as e:
            yield {"type": "error", "message": str(e)}
            return

        index_html = _decode(index_bytes)
        article_paths = _get_article_urls(index_html, key)

        if not article_paths:
            yield {"type": "error", "message": f"記事が見つかりません（カテゴリ: {key}）"}
            return

        total = len(article_paths)
        yield {"type": "start", "total": total, "title": title}

        # ── Fetch each article ────────────────────────────────
        articles: list[dict] = []
        for i, path in enumerate(article_paths):
            short = path.split("/")[-1].replace(".htm", "")
            yield {"type": "progress", "done": i, "total": total, "article": short}

            try:
                page_bytes = await _fetch(path, client)
                page_html = _decode(page_bytes)
                article = _extract_article(page_html)
                if article:
                    articles.append(article)
            except TaxAnswerError:
                pass  # skip failed pages silently

            await asyncio.sleep(REQUEST_DELAY)

        yield {"type": "progress", "done": total, "total": total, "article": "変換中"}
        yield {"type": "articles", "title": title, "articles": articles}
