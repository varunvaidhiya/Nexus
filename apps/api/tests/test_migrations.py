"""Migration round-trip test. Needs a real Postgres with pgvector available.

Skipped unless NEXUS_TEST_DATABASE_URL is set (CI provides a pgvector service).
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="NEXUS_TEST_DATABASE_URL not set")

EXPECTED_TABLES = {
    "source",
    "conversation",
    "message",
    "entity",
    "conversation_entity",
    "task",
    "goal",
    "goal_task",
    "memory_note",
    "provider_key",
    "profile_snapshot",
}


def _alembic_config() -> Config:
    api_root = Path(__file__).parent.parent
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "migrations"))
    return config


def test_upgrade_and_downgrade() -> None:
    assert TEST_DATABASE_URL is not None
    os.environ["NEXUS_DATABASE_URL"] = TEST_DATABASE_URL
    from nexus_api.config import get_settings

    get_settings.cache_clear()
    config = _alembic_config()

    command.upgrade(config, "head")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        assert set(inspect(engine).get_table_names()) >= EXPECTED_TABLES
        with engine.connect() as conn:
            extensions = conn.execute(text("SELECT extname FROM pg_extension")).scalars().all()
            assert "vector" in extensions
            index_names = (
                conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'message'"))
                .scalars()
                .all()
            )
            assert "ix_message_embedding_hnsw" in index_names

        command.downgrade(config, "base")
        assert not (EXPECTED_TABLES & set(inspect(engine).get_table_names()))

        # And back up, so repeated runs are exercised.
        command.upgrade(config, "head")
    finally:
        engine.dispose()
