"""
download_categories.py
──────────────────────
6 カテゴリの国税法令を検索結果ごと一括ダウンロードする。

出力先:
    output/所得税/       ← 「所得税法」検索結果 全件
    output/法人税/       ← 「法人税法」検索結果 全件
    output/消費税/       ← 「消費税法」検索結果 全件
    output/相続税/       ← 「相続税法」検索結果 全件
    output/租税特別措置/ ← 「租税特別措置法」検索結果 全件

既存ファイルはスキップする（中断再実行 OK）。

使い方:
    python download_categories.py
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.api_client import close_client, get_law_data, search_laws
from app.exceptions import EGovAPIError, LawNotFoundError, XMLParseError
from app.markdown_generator import (
    MAX_SINGLE_FILE_CHARS,
    generate_markdown,
    generate_split_markdown,
)
from app.xml_parser import parse_law_tree

OUTPUT_DIR = Path(__file__).parent / "output"

CATEGORIES = [
    {"folder": "所得税",       "search_query": "所得税法"},
    {"folder": "法人税",       "search_query": "法人税法"},
    {"folder": "消費税",       "search_query": "消費税法"},
    {"folder": "相続税",       "search_query": "相続税法"},
    {"folder": "租税特別措置", "search_query": "租税特別措置法"},
]


def _safe_fn(title: str, ext: str, max_bytes: int = 200) -> str:
    safe = re.sub(r'[\\/:*?"<>|　\s]', "_", title)
    enc = safe.encode("utf-8")
    if len(enc) > max_bytes:
        safe = enc[:max_bytes].decode("utf-8", errors="ignore") + "…"
    return f"{safe}{ext}"


async def download_one(law_id: str, title: str, dest_dir: Path) -> tuple[str, str]:
    """
    Returns ("ok", info) / ("skip", fname) / ("error", msg)
    """
    # skip チェック: 単ファイルまたは split 先頭ファイルが存在すれば skip
    safe_prefix = re.sub(r'[\\/:*?"<>|　\s]', "_", title)
    single = dest_dir / _safe_fn(title, ".md")
    existing = list(dest_dir.glob(f"{safe_prefix}*.md"))
    if single.exists() or existing:
        return ("skip", title)

    # 本文取得
    try:
        law_data = await get_law_data(law_id)
    except EGovAPIError as e:
        return ("error", f"{title}: {e}")

    # パース
    try:
        doc = parse_law_tree(law_data["tree"], metadata=law_data)
    except XMLParseError as e:
        return ("error", f"{title}: {e}")

    # 保存
    md = generate_markdown(doc)
    real_title = doc.law_title or title

    if len(md) <= MAX_SINGLE_FILE_CHARS:
        fname = _safe_fn(real_title, ".md")
        (dest_dir / fname).write_text(md, encoding="utf-8")
        return ("ok", f"{fname}  ({len(md):,} chars)")
    else:
        split_files = generate_split_markdown(doc)
        for fname, content in split_files:
            (dest_dir / fname).write_text(content, encoding="utf-8")
        summary = f"{len(split_files)} ファイル: " + ", ".join(f for f, _ in split_files)
        return ("ok", summary)


async def download_category(folder: str, search_query: str) -> tuple[int, int, int]:
    """Returns (ok, skipped, errors)."""
    dest_dir = OUTPUT_DIR / folder
    dest_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"【{folder}】  検索: 「{search_query}」")
    print(f"{'='*60}")

    # 検索
    try:
        results = await search_laws(search_query)
    except LawNotFoundError:
        print(f"  ERROR: 法令が見つかりません")
        return 0, 0, 1
    except EGovAPIError as e:
        print(f"  ERROR: 検索失敗: {e}")
        return 0, 0, 1

    print(f"  {len(results)} 件ヒット → {dest_dir.relative_to(OUTPUT_DIR.parent)}")

    ok = skipped = errors = 0
    for r in results:
        t0 = time.time()
        status, info = await download_one(r.law_id, r.law_title, dest_dir)
        elapsed = time.time() - t0

        if status == "ok":
            ok += 1
            print(f"  ✓ {r.law_title[:55]}  ({elapsed:.1f}s)")
            print(f"      → {info}")
        elif status == "skip":
            skipped += 1
            print(f"  skip {r.law_title[:60]}")
        else:
            errors += 1
            print(f"  ERROR {info}")

    return ok, skipped, errors


async def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    t_all = time.time()
    print(f"出力先: {OUTPUT_DIR.resolve()}\n")

    total_ok = total_skip = total_err = 0

    for cat in CATEGORIES:
        ok, skip, err = await download_category(cat["folder"], cat["search_query"])
        total_ok   += ok
        total_skip += skip
        total_err  += err

    await close_client()

    elapsed = time.time() - t_all
    all_files = list(OUTPUT_DIR.rglob("*.md"))
    total_bytes = sum(f.stat().st_size for f in all_files)

    print(f"\n{'='*60}")
    print("完了サマリー")
    print(f"{'='*60}")
    print(f"  取得: {total_ok} 件  スキップ: {total_skip} 件  エラー: {total_err} 件")
    for cat in CATEGORIES:
        d = OUTPUT_DIR / cat["folder"]
        files = list(d.glob("*.md")) if d.exists() else []
        size_kb = sum(f.stat().st_size for f in files) / 1024
        print(f"  {cat['folder']:<12} {len(files):>3} ファイル  {size_kb:>7.0f} KB")
    print(f"  output/ 配下合計: {len(all_files)} ファイル  {total_bytes/1024/1024:.1f} MB")
    print(f"  経過時間: {elapsed/60:.1f} 分")
    print(f"  出力先  : {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
