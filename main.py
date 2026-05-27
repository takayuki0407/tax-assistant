import io
import json
import re
import urllib.parse
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.api_client import close_client, get_law_data, search_laws
from app.exceptions import EGovAPIError, LawNotFoundError, XMLParseError
from app.markdown_generator import (
    MAX_SINGLE_FILE_CHARS,
    count_articles,
    generate_markdown,
    generate_split_markdown,
)
from app.models import LawSearchResult, MarkdownResponse
from app.tsutatsu_scraper import CATALOG as TSUTATSU_CATALOG, scrape_tsutatsu
from app.tsutatsu_md import generate_tsutatsu_markdown, tsutatsu_filename
from app.taxanswer_scraper import TAXANSWER_CATALOG, scrape_taxanswer
from app.taxanswer_md import generate_taxanswer_markdown, taxanswer_filename
from app.xml_parser import parse_law_tree


class BundleFile(BaseModel):
    filename: str
    content: str


# In-memory store for tsutatsu ZIP results (job_id → bytes)
_tsutatsu_results: dict[str, bytes] = {}


def _safe_filename(title: str, ext: str, max_bytes: int = 200) -> str:
    """Return a filename whose UTF-8 length stays within max_bytes."""
    safe = re.sub(r'[\\/:*?"<>|　\s]', "_", title)
    encoded = safe.encode("utf-8")
    if len(encoded) <= max_bytes:
        return f"{safe}{ext}"
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{truncated}…{ext}"

QUICK_SELECT_GROUPS = [
    {
        "group": "所得税",
        "laws": [
            {"law_title": "所得税法",       "search_query": "所得税法"},
            {"law_title": "所得税法施行令",  "search_query": "所得税法施行令"},
            {"law_title": "所得税法施行規則","search_query": "所得税法施行規則"},
        ],
    },
    {
        "group": "法人税・地方法人税",
        "laws": [
            {"law_title": "法人税法",           "search_query": "法人税法"},
            {"law_title": "法人税法施行令",      "search_query": "法人税法施行令"},
            {"law_title": "法人税法施行規則",    "search_query": "法人税法施行規則"},
            {"law_title": "地方法人税法",        "search_query": "地方法人税法"},
            {"law_title": "地方法人税法施行令",  "search_query": "地方法人税法施行令"},
            {"law_title": "地方法人税法施行規則","search_query": "地方法人税法施行規則"},
        ],
    },
    {
        "group": "消費税",
        "laws": [
            {"law_title": "消費税法",       "search_query": "消費税法"},
            {"law_title": "消費税法施行令",  "search_query": "消費税法施行令"},
            {"law_title": "消費税法施行規則","search_query": "消費税法施行規則"},
        ],
    },
    {
        "group": "相続税・贈与税",
        "laws": [
            {"law_title": "相続税法（相続税）",  "search_query": "相続税法"},
            {"law_title": "相続税法施行令",      "search_query": "相続税法施行令"},
            {"law_title": "相続税法施行規則",    "search_query": "相続税法施行規則"},
            {"law_title": "贈与税（相続税法）",  "search_query": "相続税法"},
        ],
    },
    {
        "group": "租税特別措置",
        "laws": [
            {"law_title": "租税特別措置法",       "search_query": "租税特別措置法"},
            {"law_title": "租税特別措置法施行令",  "search_query": "租税特別措置法施行令"},
            {"law_title": "租税特別措置法施行規則","search_query": "租税特別措置法施行規則"},
        ],
    },
]

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_client()


app = FastAPI(
    title="税法アシスタント",
    description="e-Gov法令APIから税法を取得し、NotebookLM用Markdownに変換します",
    lifespan=lifespan,
)


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/quickselect", response_model=list[dict])
async def get_quick_select():
    return QUICK_SELECT_GROUPS


@app.get("/api/search", response_model=list[LawSearchResult])
async def search(q: str = Query(..., min_length=1, description="法令名（部分一致）")):
    try:
        results = await search_laws(q)
        return results
    except LawNotFoundError:
        raise HTTPException(status_code=404, detail=f"「{q}」に該当する法令が見つかりません")
    except EGovAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)


@app.get("/api/law/{law_id}/markdown")
async def get_markdown(law_id: str):
    try:
        law_data = await get_law_data(law_id)
    except EGovAPIError as e:
        raise HTTPException(status_code=502, detail=e.message)
    except XMLParseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        doc = parse_law_tree(law_data["tree"], metadata=law_data)
    except XMLParseError as e:
        raise HTTPException(
            status_code=422,
            detail=f"{str(e)}。e-Gov法令検索 (https://laws.e-gov.go.jp) から手動でダウンロードしてください。",
        )

    md = generate_markdown(doc)
    article_count = count_articles(doc)

    if len(md) <= MAX_SINGLE_FILE_CHARS:
        return JSONResponse(content=MarkdownResponse(
            filename=_safe_filename(doc.law_title, ".md"),
            content=md,
            char_count=len(md),
            article_count=article_count,
            is_split=False,
        ).model_dump())

    # Large law: split by chapter and return ZIP
    split_files = generate_split_markdown(doc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, content in split_files:
            zf.writestr(fname, content.encode("utf-8"))
    buf.seek(0)

    zip_filename = _safe_filename(doc.law_title, ".zip")
    # RFC 6266: encode non-ASCII filename for Content-Disposition header
    encoded_name = urllib.parse.quote(zip_filename)

    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@app.post("/api/bundle")
async def bundle_markdown(files: list[BundleFile]):
    """Receive collected markdown content and return a single ZIP file."""
    if not files:
        raise HTTPException(status_code=400, detail="ファイルが指定されていません")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            info = zipfile.ZipInfo(f.filename)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.flag_bits |= 0x800  # set UTF-8 encoding flag (EFS)
            zf.writestr(info, f.content.encode("utf-8"))
    buf.seek(0)

    zip_filename = f"税法_NotebookLM用_{date.today().strftime('%Y%m%d')}.zip"
    encoded_name = urllib.parse.quote(zip_filename)

    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


# ── 基本通達 endpoints ─────────────────────────────────────────────────────────

@app.get("/api/tsutatsu", response_model=list[dict])
async def get_tsutatsu_list():
    """Return list of available 基本通達."""
    return [
        {"key": key, "title": info["title"]}
        for key, info in TSUTATSU_CATALOG.items()
    ]


@app.get("/api/tsutatsu/{key}/stream")
async def stream_tsutatsu(key: str):
    """SSE stream: progress events while scraping, then emits job_id when done."""
    if key not in TSUTATSU_CATALOG:
        raise HTTPException(status_code=404, detail="通達が見つかりません")

    async def generator():
        job_id = str(uuid.uuid4())
        pages: list[dict] = []
        title = TSUTATSU_CATALOG[key]["title"]

        try:
            async for event in scrape_tsutatsu(key):
                etype = event.get("type")
                if etype in ("start", "progress"):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif etype == "sections":
                    pages = event.get("pages", [])
                elif etype == "error":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    return

            # Build single .md file
            md_content = generate_tsutatsu_markdown(title, pages)
            _tsutatsu_results[job_id] = md_content.encode("utf-8")

            done_evt = {"type": "done", "job_id": job_id, "chars": len(md_content)}
            yield f"data: {json.dumps(done_evt, ensure_ascii=False)}\n\n"

        except Exception as e:
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/tsutatsu/{key}/result/{job_id}")
async def download_tsutatsu_result(key: str, job_id: str):
    """Download single .md file produced by the stream endpoint."""
    data = _tsutatsu_results.pop(job_id, None)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="結果が見つかりません（既にダウンロード済みかタイムアウトした可能性があります）",
        )
    title = TSUTATSU_CATALOG.get(key, {}).get("title", key)
    md_filename = _safe_filename(title, ".md")
    encoded_name = urllib.parse.quote(md_filename)
    return Response(
        content=data,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


# ── タックスアンサー endpoints ─────────────────────────────────────────────────

# In-memory store for taxanswer results (job_id → bytes)
_taxanswer_results: dict[str, bytes] = {}


@app.get("/api/taxanswer", response_model=list[dict])
async def get_taxanswer_list():
    """Return list of available タックスアンサー categories."""
    return [
        {"key": key, "title": info["title"], "article_count": info["article_count"]}
        for key, info in TAXANSWER_CATALOG.items()
    ]


@app.get("/api/taxanswer/{key}/stream")
async def stream_taxanswer(key: str):
    """SSE stream: progress events while scraping, then emits job_id when done."""
    if key not in TAXANSWER_CATALOG:
        raise HTTPException(status_code=404, detail="カテゴリが見つかりません")

    async def generator():
        job_id = str(uuid.uuid4())
        title = TAXANSWER_CATALOG[key]["title"]

        try:
            articles: list[dict] = []
            async for event in scrape_taxanswer(key):
                etype = event.get("type")
                if etype in ("start", "progress"):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                elif etype == "articles":
                    articles = event.get("articles", [])
                elif etype == "error":
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    return

            md_content = generate_taxanswer_markdown(title, articles)
            _taxanswer_results[job_id] = md_content.encode("utf-8")

            done_evt = {
                "type": "done",
                "job_id": job_id,
                "chars": len(md_content),
                "article_count": len(articles),
            }
            yield f"data: {json.dumps(done_evt, ensure_ascii=False)}\n\n"

        except Exception as e:
            err = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/taxanswer/{key}/result/{job_id}")
async def download_taxanswer_result(key: str, job_id: str):
    """Download single .md file produced by the stream endpoint."""
    data = _taxanswer_results.pop(job_id, None)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail="結果が見つかりません（既にダウンロード済みかタイムアウトした可能性があります）",
        )
    title = TAXANSWER_CATALOG.get(key, {}).get("title", key)
    md_filename = _safe_filename(f"タックスアンサー_{title}", ".md")
    encoded_name = urllib.parse.quote(md_filename)
    return Response(
        content=data,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


# Serve static files (after API routes to avoid conflicts)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
