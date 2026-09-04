"""FastAPI application factory.

Wires together the API router, the static frontend, and global error handling.
Kept separate from `app.py` (the runnable entry point) so tests can build the
application without starting a server.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from claimiq import APP_NAME, __version__
from claimiq.api.routes import router as api_router
from claimiq.config import STATIC_DIR

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title=APP_NAME, version=__version__, docs_url="/api/docs")

    app.include_router(api_router)

    # --- Global error handling -------------------------------------------
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
        return JSONResponse(
            status_code=422,
            content={"error": "Invalid request", "details": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        )

    # --- Frontend ---------------------------------------------------------
    index_file = STATIC_DIR / "index.html"

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(index_file, media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()
