from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus_api import __version__
from nexus_api.auth import require_auth, require_ingest_auth
from nexus_api.config import Settings, get_settings
from nexus_api.logging import configure_logging
from nexus_api.routers.chat import router as chat_router
from nexus_api.routers.conversations import router as conversations_router
from nexus_api.routers.devices import router as devices_router
from nexus_api.routers.goals import router as goals_router
from nexus_api.routers.ingest import router as ingest_router
from nexus_api.routers.providers import router as providers_router
from nexus_api.routers.search import router as search_router
from nexus_api.routers.sources import router as sources_router
from nexus_api.routers.tasks import router as tasks_router
from nexus_api.routers.today import router as today_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(title="Nexus API", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # Every router mounted here is gated; only /healthz above is public.
    gated = [Depends(require_auth)]
    app.include_router(providers_router, dependencies=gated)
    app.include_router(chat_router, dependencies=gated)
    app.include_router(conversations_router, dependencies=gated)
    app.include_router(search_router, dependencies=gated)
    app.include_router(devices_router, dependencies=gated)
    app.include_router(sources_router, dependencies=gated)
    app.include_router(tasks_router, dependencies=gated)
    app.include_router(goals_router, dependencies=gated)
    app.include_router(today_router, dependencies=gated)
    # Ingest additionally accepts device tokens (agent/extension).
    app.include_router(ingest_router, dependencies=[Depends(require_ingest_auth)])

    return app


app = create_app()
