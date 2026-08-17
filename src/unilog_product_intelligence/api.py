"""FastAPI application for the UNILOG product intelligence workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
REPORT = ROOT / "docs" / "research" / "row-2-live-check-final.json"


def create_app() -> FastAPI:
    """Create the API and serve the evidence-first workspace UI."""

    settings = get_settings()
    app = FastAPI(title="UniLog Product Intelligence", version="0.1.0")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    @app.get("/api/products", tags=["products"])
    def products() -> dict[str, Any]:
        if not REPORT.exists():
            return {"results": []}
        payload = json.loads(REPORT.read_text(encoding="utf-8"))
        return {"results": payload.get("results", [])}

    if FRONTEND.exists():
        app.mount("/frontend", StaticFiles(directory=FRONTEND), name="frontend")

        @app.get("/", include_in_schema=False)
        def home() -> FileResponse:
            return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()


def run() -> None:
    """Run the development server through the packaged console script."""

    import uvicorn

    uvicorn.run("unilog_product_intelligence.api:app", host="127.0.0.1", port=8000)