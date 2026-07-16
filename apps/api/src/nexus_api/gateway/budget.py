"""Monthly budget enforcement per provider key.

`provider_key.spend_usd` tracks the current calendar month's spend;
`spend_month` records which month it belongs to, so spend lazily resets when
the month rolls over.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_api.db.models import ProviderKey
from nexus_api.gateway.pricing import estimate_cost_usd
from nexus_api.gateway.types import ErrorKind, GatewayError

BUDGET_WARNING_RATIO = Decimal("0.8")


def _current_month() -> date:
    return datetime.now(UTC).date().replace(day=1)


def _row(session: Session, provider: str) -> ProviderKey:
    row = session.scalars(select(ProviderKey).where(ProviderKey.provider == provider)).one_or_none()
    if row is None:
        raise GatewayError(ErrorKind.auth, provider, "no API key stored for this provider")
    return row


def effective_spend(row: ProviderKey) -> Decimal:
    """Spend for the current month (0 if the recorded month has rolled over)."""
    if row.spend_month != _current_month():
        return Decimal(0)
    return row.spend_usd


def check_budget(session: Session, provider: str) -> ProviderKey:
    """Return the key row, or raise if this month's budget is exhausted."""
    row = _row(session, provider)
    if row.monthly_budget_usd is not None and effective_spend(row) >= row.monthly_budget_usd:
        raise GatewayError(
            ErrorKind.budget,
            provider,
            f"monthly budget of ${row.monthly_budget_usd} reached "
            f"(spent ${effective_spend(row)}); raise the budget in settings to continue",
        )
    return row


def record_spend(
    session: Session,
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> Decimal:
    """Add this request's estimated cost to the current month's spend."""
    row = _row(session, provider)
    month = _current_month()
    if row.spend_month != month:
        row.spend_usd = Decimal(0)
        row.spend_month = month
    cost = estimate_cost_usd(provider, model, input_tokens, output_tokens)
    row.spend_usd += cost
    session.flush()
    return cost
