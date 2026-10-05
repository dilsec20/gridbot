"""Shared allocation and symbol-specific leverage rules."""

import math


DEFAULT_POSITION_ALLOCATION_PERCENT = 60.0
MAX_POSITION_ALLOCATION_PERCENT = 60.0
STABLECOIN_ASSETS = frozenset(
    {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"}
)


def is_stablecoin_pair(symbol: str) -> bool:
    """Return True only when both contract assets are recognized stablecoins."""
    pair = str(symbol).split(":", 1)[0].replace("-", "/")
    assets = pair.split("/")
    return len(assets) == 2 and all(asset.upper() in STABLECOIN_ASSETS for asset in assets)


def effective_leverage(symbol: str, configured_leverage: float = 5) -> int:
    """Use fixed 10x for stablecoin pairs and cap other pairs at 5x."""
    if is_stablecoin_pair(symbol):
        return 10

    try:
        leverage = int(configured_leverage)
    except (TypeError, ValueError, OverflowError):
        leverage = 5
    return min(5, max(1, leverage))


def position_budget(balance: float, config: dict) -> float:
    """Cap grid notional at 60% of wallet balance and any smaller hard USD cap."""
    available_balance = max(0.0, float(balance))
    allocation_percent = float(
        config.get(
            "max_position_balance_percent",
            DEFAULT_POSITION_ALLOCATION_PERCENT,
        )
    )
    if not math.isfinite(allocation_percent):
        raise ValueError("Position allocation percentage must be finite.")

    allocation_percent = min(
        MAX_POSITION_ALLOCATION_PERCENT, max(0.0, allocation_percent)
    )
    budget = available_balance * allocation_percent / 100.0

    configured_cap = float(config.get("max_position_usdt", 0) or 0)
    if not math.isfinite(configured_cap):
        raise ValueError("Maximum position amount must be finite.")
    if configured_cap > 0:
        budget = min(budget, configured_cap)
    return budget
