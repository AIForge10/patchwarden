from fastapi import FastAPI

from resolveloop import config
from resolveloop.store import init_db

from .runs import router as runs_router
from .webhooks import router as webhook_router


def create_app() -> FastAPI:
    app = FastAPI(title="ResolveLoop")
    app.state.settings = config

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    app.include_router(webhook_router)
    app.include_router(runs_router)
    return app


app = create_app()
