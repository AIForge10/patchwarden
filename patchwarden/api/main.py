from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from patchwarden import config
from patchwarden.config import validate_startup
from patchwarden.sandbox.e2b_runner import use_e2b
from patchwarden.store import init_db

from .demo import demo_status
from .demo import router as demo_router
from .runs import router as runs_router
from .webhooks import router as webhook_router

UI_DIR = Path(__file__).resolve().parents[1] / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup(app.state.settings)
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="PatchWarden", lifespan=lifespan)
    app.state.settings = config

    app.include_router(webhook_router)
    app.include_router(runs_router)
    app.include_router(demo_router)
    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

    @app.get("/health")
    def health() -> dict:
        """Liveness for hosts. Never includes secret values."""
        settings = app.state.settings
        try:
            sandbox = "e2b" if use_e2b() else "local"
        except RuntimeError:
            sandbox = "misconfigured"
        return {
            "ok": True,
            "model": settings.NEBIUS_MODEL_REASONING or None,
            "model_configured": bool(settings.NEBIUS_API_KEY and settings.NEBIUS_MODEL_REASONING),
            "github_configured": bool(settings.GITHUB_TOKEN and settings.GITHUB_TARGET_REPO),
            "open_pr_on_verified": settings.OPEN_PR_ON_VERIFIED,
            "sandbox": sandbox,
            "tavily_configured": bool(settings.TAVILY_API_KEY),
            "live_demo": demo_status(settings)["enabled"],
        }

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/ui/")

    return app


app = create_app()
