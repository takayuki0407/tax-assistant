import io
import re
import urllib.parse
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
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
from app.xml_parser import parse_law_tree


class BundleFile(BaseModel):
    filename: str
    content: str

QUICK_SELECT_LAWS = [
    {"law_title": "所得税法", "search_query": "所得税法"},
    {"law_title": "法人税法", "search_query": "法人税法"},
    {"law_title": "消費税法", "search_query": "消費税法"},
    {"law_title": "相続税法", "search_query": "相続税法"},
    {"law_title": "租税特別措置法", "search_query": "租税特別措置法"},
    {"law_title": "法人税法施行令", "search_query": "法人税法施行令"},
    {"law_title": "所得税法施行令", "search_query": "所得税法施行令"},
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
    return QUICK_SELECT_LAWS


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
    safe_title = re.sub(r'[\\/:*?"<>|　\s]', "_", doc.law_title)

    if len(md) <= MAX_SINGLE_FILE_CHARS:
        return JSONResponse(content=MarkdownResponse(
            filename=f"{safe_title}.md",
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

    zip_filename = f"{safe_title}.zip"
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


# Serve static files (after API routes to avoid conflicts)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
