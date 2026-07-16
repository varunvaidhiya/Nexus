from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus_api import __version__
from nexus_api.config import Settings, get_settings
from nexus_api.logging import configure_logging
from nexus_api.routers.providers import router as providers_router


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

    app.include_router(providers_router)

    return app


app = create_app()
