import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import (delete_document, get_db, list_documents)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["prefix"] = get_settings().root_path

MAX_HISTORY_ITEMS = 100


def _is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))


def require_admin(request: Request) -> bool:
    """Guards the state-changing admin actions (delete from history)."""
    if not _is_admin(request):
        raise HTTPException(status_code=401, detail="Unauthorized — log in at /admin/login")
    return True


@router.get("/login")
async def login_page(request: Request):
    if _is_admin(request):
        return RedirectResponse(f"{get_settings().root_path}/admin", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"error": False})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    password = (form.get("password") or "").strip()
    configured = get_settings().admin_password
    if configured and secrets.compare_digest(password, configured):
        request.session["is_admin"] = True
        return RedirectResponse(f"{get_settings().root_path}/admin", status_code=303)
    return templates.TemplateResponse(
        request, "admin_login.html", {"error": True}, status_code=401
    )


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(f"{get_settings().root_path}/admin/login", status_code=303)


@router.get("")
async def admin_page(request: Request, db=Depends(get_db)):
    if not _is_admin(request):
        return RedirectResponse(f"{get_settings().root_path}/admin/login", status_code=303)
    docs = await list_documents(db, limit=MAX_HISTORY_ITEMS)
    deleted = 1 if request.query_params.get("deleted") == "1" else 0
    return templates.TemplateResponse(
        request, "admin.html", {"docs": docs, "deleted": deleted}
    )


@router.post("/delete/{doc_id}")
async def delete_doc(request: Request, doc_id: int, db=Depends(get_db)):
    require_admin(request)
    deleted = await delete_document(db, doc_id)
    return RedirectResponse(
        f"{get_settings().root_path}/admin?deleted={int(deleted)}",
        status_code=303,
        headers={"HX-Redirect": f"{get_settings().root_path}/admin"},
    )
