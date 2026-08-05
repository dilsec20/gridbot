"""
Risk Manager for Grid Trading Bot.
Enforces safety limits: max loss, position size, balance checks.
"""

from logger import BotLogger
from binance_client import BinanceClient


class RiskManager:
    """Monitors and enforces risk limits to protect capital."""

    def __init__(self, config: dict, client: BinanceClient, logger: BotLogger):
        self.config = config
        self.client = client
        self.logger = logger

        self.max_loss_usdt = config.get("max_loss_usdt", 100.0)
        self.max_position_usdt = config.get("max_position_usdt", 500.0)
        self.realized_pnl = 0.0
        self.initial_balance = 0.0
        self.peak_pnl = 0.0  # High-water mark for trailing profit protection

    def initialize(self):
        """Record initial balance for PnL tracking."""
        self.initial_balance = self.client.get_wallet_balance()
        self.peak_pnl = 0.0
        self.logger.risk(f"Initial balance: ${self.initial_balance:,.2f} USDT")
        self.logger.risk(f"Max loss limit: ${self.max_loss_usdt:,.2f}")
        self.logger.risk(f"Max position limit: ${self.max_position_usdt:,.2f}")

    def add_realized_pnl(self, pnl: float):
        """Track realized PnL from completed grid cycles."""
        self.realized_pnl += pnl

    def check_max_loss(self) -> bool:
        """
        Check if total loss (realized + unrealized) exceeds max loss limit
        or drops by max_loss_usdt from peak PnL (Trailing Profit Protection).
        Returns True if safe, False if stop triggered.
        """
        position = self.client.get_position()
        unrealized_pnl = position.get("unrealized_pnl", 0)
        total_pnl = self.realized_pnl + unrealized_pnl

        # Update high-water mark peak PnL
        if total_pnl > self.peak_pnl:
            self.peak_pnl = total_pnl

        # 1. Hard Max Loss Check from initial balance
        if total_pnl < -self.max_loss_usdt:
            self.logger.risk(
                f"⛔ MAX LOSS BREACHED! "
                f"Total PnL: ${total_pnl:,.2f} "
                f"(Realized: ${self.realized_pnl:,.2f}, "
                f"Unrealized: ${unrealized_pnl:,.2f}) "
                f"> Limit: -${self.max_loss_usdt:,.2f}"
            )
            return False

        # 2. Trailing Profit Protection Check:
        # If profit peaked above $10 and drops by max_loss_usdt from peak, lock in profit!
        if self.peak_pnl >= 10.0 and total_pnl <= (self.peak_pnl - self.max_loss_usdt):
            self.logger.risk(
                f"🛡️ TRAILING PROFIT PROTECTOR TRIGGERED! "
                f"Peak PnL reached +${self.peak_pnl:,.2f}. "
                f"Current Net PnL dropped to +${total_pnl:,.2f} (down ${self.max_loss_usdt:,.2f} from peak). "
                f"Locking in +${total_pnl:,.2f} NET PROFIT!"
            )
            return False

        return True

    def check_position_limit(self) -> bool:
        """
        Check if current position size is within limits.
        Returns True if safe, False if position is too large.
        """
        position = self.client.get_position()
        notional = abs(position.get("notional", 0))

        if notional > self.max_position_usdt:
            self.logger.risk(
                f"Position limit reached: ${notional:,.2f} > ${self.max_position_usdt:,.2f}"
            )
            return False

        return True

    def can_place_order(self, side: str, quantity: float, price: float) -> bool:
        """
        Pre-flight check before placing an order.
        Verifies balance, position limits, and max loss.
        """
        # Check max loss
        if not self.check_max_loss():
            return False

        # Get current position
        position = self.client.get_position()
        pos_side = str(position.get("side", "none")).lower()
        pos_size = float(position.get("size", 0) or 0)
        notional = float(position.get("notional", 0) or 0)

        # Determine if position is long or short
        is_long = (pos_side in ["long", "buy"]) or (pos_size > 0) or (notional > 0 and pos_side != "short")
        is_short = (pos_side in ["short", "sell"]) or (pos_size < 0) or (notional < 0)

        # A SELL order on a LONG position, or a BUY order on a SHORT position REDUCES position size.
        # Position-reducing orders must NEVER be blocked by position limits!
        is_reducing = (
            (side.lower() == "sell" and is_long and abs(pos_size) > 0) or
            (side.lower() == "buy" and is_short and abs(pos_size) > 0)
        )

        if not is_reducing:
            # Check position limit for position-expanding orders
            if not self.check_position_limit():
                self.logger.risk(f"Order blocked: position limit reached ({side} {quantity} @ ${price:,.2f})")
                return False

            # Check available balance
            try:
                balance = self.client.get_balance()
                required_margin = (quantity * price) / self.config.get("leverage", 5)

                if balance < required_margin:
                    self.logger.risk(
                        f"Insufficient balance: ${balance:,.2f} < required margin ${required_margin:,.2f}"
                    )
                    return False
            except Exception as e:
                self.logger.error(f"Failed to check balance for risk: {e}")
                return False

        return True

    def perform_safety_check(self) -> bool:
        """
        Periodic safety check. Called every few seconds.
        Returns True if safe to continue, False if bot should stop.
        """
        if not self.check_max_loss():
            return False

        return True

    def get_total_pnl(self) -> float:
        """Get total PnL (realized + unrealized)."""
        position = self.client.get_position()
        unrealized = position.get("unrealized_pnl", 0)
        return self.realized_pnl + unrealized

    def get_realized_pnl(self) -> float:
        """Get realized PnL only."""
        return self.realized_pnl

    def get_compounded_quantity(self, current_qty: float, spacing_pct: float = 0.5) -> float:
        """Calculate compounded order quantity based on realized equity growth."""
        try:
            if self.initial_balance <= 0:
                return current_qty
            growth_ratio = max(1.0, (self.initial_balance + max(0.0, self.realized_pnl)) / self.initial_balance)
            new_qty = round(current_qty * growth_ratio, 6)
            return max(current_qty, new_qty)
        except Exception:
            return current_qty
