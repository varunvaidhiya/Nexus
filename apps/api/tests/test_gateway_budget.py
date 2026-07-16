"""Pricing and budget tests (budget tests need Postgres)."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from nexus_api.gateway import budget
from nexus_api.gateway.pricing import estimate_cost_usd
from nexus_api.gateway.types import ErrorKind, GatewayError

TEST_DATABASE_URL = os.environ.get("NEXUS_TEST_DATABASE_URL")


def test_pricing_known_model() -> None:
    # 1M input + 1M output on claude-sonnet-5 = $3 + $15
    assert estimate_cost_usd("anthropic", "claude-sonnet-5", 1_000_000, 1_000_000) == Decimal("18")


def test_pricing_prefix_match_prefers_longest() -> None:
    mini = estimate_cost_usd("openai", "gpt-4o-mini", 1_000_000, 0)
    full = estimate_cost_usd("openai", "gpt-4o", 1_000_000, 0)
    assert mini == Decimal("0.15")
    assert full == Decimal("2.50")


def test_pricing_unknown_model_is_zero() -> None:
    assert estimate_cost_usd("openrouter", "some/experimental-model", 5000, 5000) == Decimal(0)
    assert estimate_cost_usd("anthropic", "claude-sonnet-5", None, None) == Decimal(0)


@pytest.fixture
def db_session() -> Session:
    if not TEST_DATABASE_URL:
        pytest.skip("NEXUS_TEST_DATABASE_URL not set")
    # Schema is provided by the session-scoped migrated_db fixture (conftest).
    engine = create_engine(TEST_DATABASE_URL)
    with Session(engine) as session, session.begin():
        session.execute(text("DELETE FROM provider_key"))
        yield session
        session.rollback()
    engine.dispose()


def _add_key(session: Session, budget_usd: str | None) -> None:
    from nexus_api.db.models import ProviderKey

    session.add(
        ProviderKey(
            provider="anthropic",
            encrypted_key=b"blob",
            monthly_budget_usd=Decimal(budget_usd) if budget_usd else None,
        )
    )
    session.flush()


def test_budget_missing_key_is_auth_error(db_session: Session) -> None:
    with pytest.raises(GatewayError) as excinfo:
        budget.check_budget(db_session, "anthropic")
    assert excinfo.value.kind == ErrorKind.auth


def test_spend_accrues_and_blocks_at_budget(db_session: Session) -> None:
    _add_key(db_session, "0.10")
    budget.check_budget(db_session, "anthropic")

    # ~$0.105 of claude-sonnet-5 usage (5k in, 6k out)
    cost = budget.record_spend(db_session, "anthropic", "claude-sonnet-5", 5_000, 6_000)
    assert cost == Decimal("0.105")

    with pytest.raises(GatewayError) as excinfo:
        budget.check_budget(db_session, "anthropic")
    assert excinfo.value.kind == ErrorKind.budget


def test_spend_resets_on_month_rollover(db_session: Session) -> None:
    from nexus_api.db.models import ProviderKey

    _add_key(db_session, "0.10")
    budget.record_spend(db_session, "anthropic", "claude-sonnet-5", 5_000, 6_000)

    # Pretend the recorded spend belongs to last month.
    row = db_session.query(ProviderKey).filter_by(provider="anthropic").one()
    row.spend_month = (datetime.now(UTC).date().replace(day=1)) - timedelta(days=1)
    db_session.flush()

    assert budget.effective_spend(row) == Decimal(0)
    budget.check_budget(db_session, "anthropic")  # no longer blocked

    cost = budget.record_spend(db_session, "anthropic", "claude-haiku-4-5", 1_000, 1_000)
    row = db_session.query(ProviderKey).filter_by(provider="anthropic").one()
    assert row.spend_usd == cost  # reset, then accrued fresh


def test_no_budget_never_blocks(db_session: Session) -> None:
    _add_key(db_session, None)
    budget.record_spend(db_session, "anthropic", "claude-opus-4-8", 10_000_000, 10_000_000)
    budget.check_budget(db_session, "anthropic")
