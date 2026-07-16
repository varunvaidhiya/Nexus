import logging

import structlog

from nexus_api.config import Settings


def configure_logging(settings: Settings) -> None:
    """Structured logging: pretty console output in dev, JSON in prod."""
    renderer: structlog.typing.Processor
    if settings.environment == "prod":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
