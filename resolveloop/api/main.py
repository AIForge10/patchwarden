from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from resolveloop import config
from resolveloop.config import validate_startup
from resolveloop.store import init_db

from .runs import router as runs_router
from .webhooks import router as webhook_router

UI_DIR = Path(__file__).resolve().parents[1] / "ui"


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup(app.state.settings)
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ResolveLoop", lifespan=lifespan)
    app.state.settings = config

    app.include_router(webhook_router)
    app.include_router(runs_router)
    app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/ui/")

    return app


app = create_app()
