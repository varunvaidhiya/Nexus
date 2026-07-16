import os
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest

# Throwaway credentials so crypto and auth work in tests. Set before
# nexus_api modules read settings.
os.environ.setdefault("NEXUS_MASTER_KEY", secrets.token_hex(32))
os.environ.setdefault("NEXUS_AUTH_TOKEN", secrets.token_urlsafe(32))

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> Iterator[None]:
    """Bring the test database to the current migration head exactly once.

    Individual fixtures must NOT create tables themselves (create_all leaves
    enums/tables behind without stamping alembic_version, which breaks the
    migration round-trip test on a fresh CI database).
    """
    if TEST_DATABASE_URL:
        from alembic import command
        from alembic.config import Config

        os.environ["NEXUS_DATABASE_URL"] = TEST_DATABASE_URL
        from nexus_api.config import get_settings

        get_settings.cache_clear()
        api_root = Path(__file__).parent.parent
        config = Config(str(api_root / "alembic.ini"))
        config.set_main_option("script_location", str(api_root / "migrations"))
        command.upgrade(config, "head")
    yield
