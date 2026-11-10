"""FastAPI-Anwendung: interne API + Auslieferung der gebauten Oberfläche (nur dieser Dienst wird veröffentlicht)."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text as sql

from ..config import VERSION, get_settings
from ..db import session_scope
from . import admin, analysis, auth, postings

log = logging.getLogger("workforce.web")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
       "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def create_app() -> FastAPI:
    s = get_settings()
    dev = s.env == "development"
    app = FastAPI(title="WorkForce", version=VERSION, docs_url="/api/docs" if dev else None, redoc_url=None, openapi_url="/api/openapi.json" if dev else None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response: Response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        try:
            with session_scope() as db:
                db.execute(sql("SELECT 1"))
                rev = db.execute(sql("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            return JSONResponse({"status": "ok", "version": VERSION, "schema": rev})
        except Exception as exc:  # noqa: BLE001
            log.error("Healthcheck fehlgeschlagen", extra={"error": repr(exc)})
            return JSONResponse({"status": "error"}, status_code=503)

    for r in (auth.router, postings.router, analysis.router, admin.router):
        app.include_router(r)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str) -> None:
        raise HTTPException(404, "Unbekannter API-Pfad")

    static = Path(s.static_dir)
    if (static / "index.html").exists():
        if (static / "assets").exists():
            app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = (static / path).resolve()
            if path and candidate.is_file() and static.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
