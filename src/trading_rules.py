"""Shared allocation and symbol-specific leverage rules."""

import math


DEFAULT_POSITION_ALLOCATION_PERCENT = 60.0
MAX_POSITION_ALLOCATION_PERCENT = 60.0
STABLECOIN_ASSETS = frozenset(
    {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI"}
)


def trading_mode(config: dict) -> str:
    """Resolve exchange mode, preferring current demo trading over legacy testnet."""
    if config.get("use_demo", False):
        return "DEMO"
    if config.get("use_testnet", True):
        return "TESTNET"
    return "LIVE"


def is_stablecoin_pair(symbol: str) -> bool:
    """Return True only when both contract assets are recognized stablecoins."""
    pair = str(symbol).split(":", 1)[0].replace("-", "/")
    assets = pair.split("/")
    return len(assets) == 2 and all(asset.upper() in STABLECOIN_ASSETS for asset in assets)


def effective_leverage(symbol: str, configured_leverage: float = 5, max_allowed: int = 20) -> int:
    """Use 10x for stablecoin pairs; allow user-configured leverage up to max_allowed (default 20x)."""
    if is_stablecoin_pair(symbol):
        return 10

    try:
        leverage = int(configured_leverage)
    except (TypeError, ValueError, OverflowError):
        leverage = 5
    return min(max_allowed, max(1, leverage))


def position_budget(
    balance: float, config: dict, leverage: float | None = None
) -> float:
    """Cap grid notional at 60% of wallet balance multiplied by leverage (or smaller hard USD cap)."""
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
    margin_budget = available_balance * allocation_percent / 100.0

    if leverage is None:
        try:
            leverage = float(config.get("leverage", 1) or 1)
        except (TypeError, ValueError, OverflowError):
            leverage = 1.0

    notional_budget = margin_budget * max(1.0, float(leverage))

    configured_cap = float(config.get("max_position_usdt", 0) or 0)
    if not math.isfinite(configured_cap):
        raise ValueError("Maximum position amount must be finite.")
    if configured_cap > 0:
        return min(notional_budget, configured_cap)
    return notional_budget
