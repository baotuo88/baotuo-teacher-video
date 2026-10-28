"""The web app: API, project files, the sandboxed preview, and the built frontend."""

from __future__ import annotations

import asyncio
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from . import auth, config, routes_projects, routes_settings, routes_stages, store, thumbs
from .jobs import manager

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("audio/wav", ".wav")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    manager.recover()
    for p in store.list_projects():
        try:
            store.link_engine(config.PROJECTS_DIR / p["id"])
        except OSError:
            pass
    # the style picker's pictures, made once in the background
    warm = asyncio.create_task(thumbs.warm(delay=20))
    yield
    warm.cancel()


app = FastAPI(title="baotuo-teacher-video", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

OPEN = ("/api/auth/", "/preview/", "/assets/", "/favicon")


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    needs = path.startswith("/api/") or path.startswith("/files/")
    if auth.enabled() and needs and not path.startswith(OPEN) and not auth.valid_session(request.cookies.get(auth.COOKIE)):
        return JSONResponse({"detail": "需要登录"}, status_code=401)
    return await call_next(request)


app.include_router(routes_settings.router)
app.include_router(routes_projects.router)
app.include_router(routes_stages.router)


@app.get("/files/{pid}/{rel:path}")
def project_file(pid: str, rel: str, download: int = 0) -> FileResponse:
    """A project's own files (sheets, audio, films) for the app; never the engine links or .studio/."""
    d = store.pdir(pid)
    f = store.safe_path(d, rel)
    headers = {"cache-control": "no-cache"}
    return FileResponse(f, filename=f.name if download else None, headers=headers,
                        content_disposition_type="attachment" if download else "inline")


@app.get("/preview/{pid}/{token}/{rel:path}")
def preview(pid: str, token: str, rel: str) -> Response:
    """The engine's own player, on a signed path: the page code runs in a sandboxed (opaque-origin) iframe that carries
    no cookie, so fonts and scripts are fetched cross-origin and need CORS."""
    if not auth.valid_preview(pid, token):
        raise HTTPException(403, "预览链接过期了，刷新页面")
    d = store.pdir(pid)
    f = store.safe_path(d, rel or "index.html", allow_links=True)
    headers = {"access-control-allow-origin": "*", "cache-control": "no-cache"}
    if f.suffix in (".woff2", ".woff", ".ttf", ".css") and ("engine_modules" in rel or rel.startswith("engine/")):
        headers["cache-control"] = "public, max-age=86400"
    return FileResponse(f, headers=headers)


# ── the frontend (a single-page app) ──

@app.get("/{rel:path}", include_in_schema=False)
def spa(rel: str) -> Response:
    if rel.startswith(("api/", "files/", "preview/")):
        raise HTTPException(404)
    root = config.FRONTEND_DIR
    if rel:
        f = (root / rel).resolve()
        if root.resolve() in f.parents and f.is_file():
            cache = "public, max-age=31536000, immutable" if rel.startswith("assets/") else "no-cache"
            return FileResponse(f, headers={"cache-control": cache})
    index = root / "index.html"
    if not index.exists():
        return Response("前端还没构建：cd frontend && npm run build", media_type="text/plain; charset=utf-8", status_code=503)
    return FileResponse(index, headers={"cache-control": "no-cache"})
