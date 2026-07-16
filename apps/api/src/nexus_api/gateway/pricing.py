"""Best-effort cost estimation in USD per model.

Prices are (input, output) dollars per million tokens, matched by model-ID
prefix (longest prefix wins). Unknown models cost 0 — token counts are always
recorded, so spend can be reconciled later. Keeping this table small and
editable is deliberate; provider price lists drift.
"""

from decimal import Decimal

_MTOK = Decimal(1_000_000)

# provider -> [(model prefix, input $/MTok, output $/MTok)]
_PRICES: dict[str, list[tuple[str, Decimal, Decimal]]] = {
    "anthropic": [
        ("claude-fable-5", Decimal("10.00"), Decimal("50.00")),
        ("claude-opus-4", Decimal("5.00"), Decimal("25.00")),
        ("claude-sonnet-5", Decimal("3.00"), Decimal("15.00")),
        ("claude-sonnet-4", Decimal("3.00"), Decimal("15.00")),
        ("claude-haiku-4", Decimal("1.00"), Decimal("5.00")),
    ],
    "openai": [
        ("gpt-5", Decimal("1.25"), Decimal("10.00")),
        ("gpt-4o-mini", Decimal("0.15"), Decimal("0.60")),
        ("gpt-4o", Decimal("2.50"), Decimal("10.00")),
        ("gpt-4.1", Decimal("2.00"), Decimal("8.00")),
        ("o3", Decimal("2.00"), Decimal("8.00")),
    ],
    "deepseek": [
        ("deepseek-chat", Decimal("0.27"), Decimal("1.10")),
        ("deepseek-reasoner", Decimal("0.55"), Decimal("2.19")),
    ],
    "gemini": [
        ("gemini-2.5-pro", Decimal("1.25"), Decimal("10.00")),
        ("gemini-2.5-flash", Decimal("0.30"), Decimal("2.50")),
    ],
    # OpenRouter routes to models whose IDs embed the upstream vendor
    # ("anthropic/claude-..."); prices vary per route, so estimate 0 unless a
    # prefix below matches.
    "openrouter": [],
}


def estimate_cost_usd(
    provider: str, model: str, input_tokens: int | None, output_tokens: int | None
) -> Decimal:
    table = sorted(_PRICES.get(provider, []), key=lambda row: len(row[0]), reverse=True)
    for prefix, input_price, output_price in table:
        if model.startswith(prefix):
            cost = (
                Decimal(input_tokens or 0) * input_price
                + Decimal(output_tokens or 0) * output_price
            ) / _MTOK
            return cost.quantize(Decimal("0.000001"))
    return Decimal(0)
