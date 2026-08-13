"""FastAPI application factory for the backend foundation."""

from fastapi import FastAPI

from .config import get_settings


def create_app() -> FastAPI:
    """Create the API without loading product data or making external calls."""

    settings = get_settings()
    app = FastAPI(title="UniLog Product Intelligence", version="0.1.0")

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()


def run() -> None:
    """Run the development server through the packaged console script."""

    import uvicorn

    uvicorn.run("unilog_product_intelligence.api:app", host="127.0.0.1", port=8000)
