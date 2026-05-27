"""
download_all.py
───────────────
e-Gov 法令・NTA 通達・タックスアンサーの全 Markdown を
./output/ フォルダへ一括ダウンロードする。

使い方:
    python download_all.py

既にファイルが存在する場合はスキップするので、
中断後の再実行でも重複取得しない。
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
import time
from pathlib import Path

# UTF-8 出力（Windows terminal 文字化け対策）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── インポート ─────────────────────────────────────────────────
from app.api_client import close_client, get_law_data, search_laws
from app.exceptions import EGovAPIError, LawNotFoundError, XMLParseError
from app.markdown_generator import (
    MAX_SINGLE_FILE_CHARS,
    generate_markdown,
    generate_split_markdown,
)
from app.taxanswer_md import generate_taxanswer_markdown, taxanswer_filename
from app.taxanswer_scraper import TAXANSWER_CATALOG, scrape_taxanswer
from app.tsutatsu_md import generate_tsutatsu_markdown, tsutatsu_filename
from app.tsutatsu_scraper import CATALOG as TSUTATSU_CATALOG, scrape_tsutatsu
from app.xml_parser import parse_law_tree

# ── 設定 ──────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"

# QUICK_SELECT_LAWS と同じセット。search_query で重複排除する。
_LAWS = [
    {"label": "所得税法",       "search_query": "所得税法"},
    {"label": "法人税法",       "search_query": "法人税法"},
    {"label": "消費税法",       "search_query": "消費税法"},
    {"label": "相続税法",       "search_query": "相続税法"},
    {"label": "租税特別措置法", "search_query": "租税特別措置法"},
    {"label": "法人税法施行令", "search_query": "法人税法施行令"},
    {"label": "所得税法施行令", "search_query": "所得税法施行令"},
]


# ── ファイル名ヘルパー ─────────────────────────────────────────
def _safe_fn(title: str, ext: str, max_bytes: int = 200) -> str:
    safe = re.sub(r'[\\/:*?"<>|　\s]', "_", title)
    enc = safe.encode("utf-8")
    if len(enc) > max_bytes:
        safe = enc[:max_bytes].decode("utf-8", errors="ignore") + "…"
    return f"{safe}{ext}"


# ── 共通 skip チェック ────────────────────────────────────────
def _skip(path: Path) -> bool:
    if path.exists():
        print(f"  skip  {path.name}（既存）")
        return True
    return False


# ─────────────────────────────────────────────────────────────
# 1. e-Gov 法令
# ─────────────────────────────────────────────────────────────
async def download_laws() -> tuple[int, int]:
    """Returns (succeeded, skipped)."""
    ok = skipped = 0
    print("\n" + "=" * 60)
    print("【1/3】 e-Gov 法令")
    print("=" * 60)

    for spec in _LAWS:
        q = spec["search_query"]
        print(f"\n▶ {q}")
        t0 = time.time()

        # ── 検索 ──────────────────────────────────────────────
        try:
            results = await search_laws(q)
        except LawNotFoundError:
            print(f"  ERROR 法令が見つかりません: {q}")
            continue
        except EGovAPIError as e:
            print(f"  ERROR 検索失敗: {e}")
            continue

        # 完全一致を優先、なければ先頭
        target = next((r for r in results if r.law_title == q), results[0])
        print(f"  法令ID: {target.law_id}  ({target.law_num})")

        # ── スキップ判定（単ファイル推定） ────────────────────
        # 大きな法令は split になるので、法令名プレフィックスが存在する
        # ファイルがあればスキップ。正確なスキップは取得後に行う。
        guess_single = OUTPUT_DIR / _safe_fn(q, ".md")
        existing = list(OUTPUT_DIR.glob(f"{re.sub(r'[\\/:*?\"<>|　\\s]', '_', q)}_*.md"))
        if guess_single.exists() or existing:
            print(f"  skip  既存ファイルあり（再取得したい場合は対象ファイルを削除してください）")
            skipped += 1
            continue

        # ── 本文取得 ──────────────────────────────────────────
        try:
            law_data = await get_law_data(target.law_id)
        except EGovAPIError as e:
            print(f"  ERROR 本文取得失敗: {e}")
            continue

        # ── パース ────────────────────────────────────────────
        try:
            doc = parse_law_tree(law_data["tree"], metadata=law_data)
        except XMLParseError as e:
            print(f"  ERROR パース失敗: {e}")
            continue

        # ── Markdown 生成・保存 ───────────────────────────────
        md = generate_markdown(doc)

        if len(md) <= MAX_SINGLE_FILE_CHARS:
            fname = _safe_fn(doc.law_title, ".md")
            (OUTPUT_DIR / fname).write_text(md, encoding="utf-8")
            print(f"  ✓  {fname}  ({len(md):,} chars, {time.time()-t0:.1f}s)")
        else:
            split_files = generate_split_markdown(doc)
            for fname, content in split_files:
                (OUTPUT_DIR / fname).write_text(content, encoding="utf-8")
            names = "  \n     ".join(f for f, _ in split_files)
            print(f"  ✓  {doc.law_title}  → {len(split_files)} ファイル ({time.time()-t0:.1f}s)")
            print(f"     {names}")

        ok += 1

    await close_client()
    return ok, skipped


# ─────────────────────────────────────────────────────────────
# 2. NTA 通達
# ─────────────────────────────────────────────────────────────
async def download_tsutatsu() -> tuple[int, int]:
    ok = skipped = 0
    print("\n" + "=" * 60)
    print("【2/3】 基本通達・措置法通達")
    print("=" * 60)

    for key, info in TSUTATSU_CATALOG.items():
        title = info["title"]
        fname = tsutatsu_filename(title)
        dest = OUTPUT_DIR / fname
        print(f"\n▶ {title}")

        if _skip(dest):
            skipped += 1
            continue

        t0 = time.time()
        pages: list[dict] = []
        error: str | None = None

        async for event in scrape_tsutatsu(key):
            et = event.get("type")
            if et == "start":
                print(f"  pages: {event['total']}")
            elif et == "progress":
                done = event["done"]
                total = event["total"]
                if done > 0 and (done % 30 == 0 or done == total):
                    print(f"  {done}/{total} ...")
            elif et == "sections":
                pages = event["pages"]
            elif et == "error":
                error = event["message"]

        if error:
            print(f"  ERROR: {error}")
            continue

        md = generate_tsutatsu_markdown(title, pages)
        dest.write_text(md, encoding="utf-8")
        print(f"  ✓  {fname}  ({len(md):,} chars, {time.time()-t0:.1f}s)")
        ok += 1

    return ok, skipped


# ─────────────────────────────────────────────────────────────
# 3. タックスアンサー
# ─────────────────────────────────────────────────────────────
async def download_taxanswer() -> tuple[int, int]:
    ok = skipped = 0
    print("\n" + "=" * 60)
    print("【3/3】 タックスアンサー")
    print("=" * 60)

    for key, info in TAXANSWER_CATALOG.items():
        title = info["title"]
        fname = taxanswer_filename(title)
        dest = OUTPUT_DIR / fname
        print(f"\n▶ {title}  (約 {info['article_count']} 件)")

        if _skip(dest):
            skipped += 1
            continue

        t0 = time.time()
        articles: list[dict] = []
        error: str | None = None

        async for event in scrape_taxanswer(key):
            et = event.get("type")
            if et == "progress":
                done = event["done"]
                total = event["total"]
                if done > 0 and (done % 50 == 0 or done == total):
                    print(f"  {done}/{total} ...")
            elif et == "articles":
                articles = event["articles"]
            elif et == "error":
                error = event["message"]

        if error:
            print(f"  ERROR: {error}")
            continue

        md = generate_taxanswer_markdown(title, articles)
        dest.write_text(md, encoding="utf-8")
        print(f"  ✓  {fname}  ({len(articles)} 件, {len(md):,} chars, {time.time()-t0:.1f}s)")
        ok += 1

    return ok, skipped


# ─────────────────────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────────────────────
async def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    total_start = time.time()
    print(f"出力先: {OUTPUT_DIR.resolve()}")

    law_ok,  law_skip  = await download_laws()
    tsu_ok,  tsu_skip  = await download_tsutatsu()
    tax_ok,  tax_skip  = await download_taxanswer()

    elapsed = time.time() - total_start
    files = sorted(OUTPUT_DIR.glob("*.md"))
    total_bytes = sum(f.stat().st_size for f in files)

    print("\n" + "=" * 60)
    print("完了サマリー")
    print("=" * 60)
    print(f"  法令           : {law_ok} 件取得 / {law_skip} 件スキップ")
    print(f"  通達           : {tsu_ok} 件取得 / {tsu_skip} 件スキップ")
    print(f"  タックスアンサー: {tax_ok} 件取得 / {tax_skip} 件スキップ")
    print(f"  output/ 合計   : {len(files)} ファイル  {total_bytes/1024/1024:.1f} MB")
    print(f"  経過時間       : {elapsed/60:.1f} 分")
    print(f"  出力先         : {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
