from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import (check_and_record_rate_limit, get_document, get_db,
                     list_documents, save_document)
from app.services.fetcher import FetchError, fetch_and_normalize

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["prefix"] = get_settings().root_path

MAX_HISTORY_ITEMS = 100


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


@router.get("/")
async def index(request: Request, db=Depends(get_db)):
    recent = await list_documents(db, limit=8)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"recent": recent, "error": None},
    )


@router.post("/print")
async def create_printable(
    request: Request,
    url: str = Form(""),
    db=Depends(get_db),
):
    """Fetch a URL, stash a printable copy in history, and open the print view."""
    settings = get_settings()

    allowed = await check_and_record_rate_limit(
        db,
        ip=_client_ip(request),
        route="print",
        limit=settings.rate_limit_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        recent = await list_documents(db, limit=8)
        return templates.TemplateResponse(
            request,
            "index.html",
            {"recent": recent, "error": "Too many requests — please slow down and try again in a minute.", "url": url},
            status_code=429,
        )

    try:
        result = await fetch_and_normalize(url, settings)
    except FetchError as exc:
        recent = await list_documents(db, limit=8)
        return templates.TemplateResponse(
            request,
            "index.html",
            {"recent": recent, "error": str(exc), "url": url},
            status_code=400,
        )

    doc_id = await save_document(
        db,
        url=url,
        final_url=result.final_url,
        title=result.title,
        source=result.source,
        content_type=result.content_type,
        content=result.content,
    )
    return RedirectResponse(
        f"{settings.root_path}/d/{doc_id}",
        status_code=303,
        headers={"HX-Redirect": f"{settings.root_path}/d/{doc_id}"},
    )


@router.get("/d/{doc_id}")
async def print_view(request: Request, doc_id: int, db=Depends(get_db)):
    doc = await get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    paper = request.query_params.get("paper", "a4")
    if paper not in ("a4", "letter"):
        paper = "a4"
    return templates.TemplateResponse(
        request,
        "print.html",
        {"doc": doc, "paper": paper},
    )


@router.get("/history")
async def history(request: Request, db=Depends(get_db)):
    docs = await list_documents(db, limit=MAX_HISTORY_ITEMS)
    return templates.TemplateResponse(request, "history.html", {"docs": docs})


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}