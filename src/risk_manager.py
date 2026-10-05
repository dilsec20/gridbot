"""
Risk Manager for Grid Trading Bot.
Enforces safety limits: max loss, position size, balance checks.
"""

from logger import BotLogger
from binance_client import BinanceClient
from trading_rules import effective_leverage, position_budget


class RiskManager:
    """Monitors and enforces risk limits to protect capital."""

    def __init__(self, config: dict, client: BinanceClient, logger: BotLogger):
        self.config = config
        self.client = client
        self.logger = logger

        self.max_loss_usdt = config.get("max_loss_usdt", 100.0)
        self.max_position_usdt = float(config.get("max_position_usdt", 0) or 0)
        self.realized_pnl = 0.0
        self.initial_balance = 0.0
        self.peak_pnl = 0.0  # High-water mark for trailing profit protection

    def initialize(self):
        """Record initial balance for PnL tracking."""
        self.initial_balance = self.client.get_wallet_balance()
        self.peak_pnl = 0.0
        self.logger.risk(f"Initial balance: ${self.initial_balance:,.2f} USDT")
        self.logger.risk(f"Max loss limit: ${self.max_loss_usdt:,.2f}")
        self.logger.risk(
            "Grid notional is capped at "
            f"{min(60.0, float(self.config.get('max_position_balance_percent', 60.0))):.1f}% "
            "of available free balance, with any lower configured USDT cap also applied."
        )

    def get_max_position_limit(self) -> float:
        """Resolve the notional cap from free margin and any fixed dollar ceiling."""
        available_balance = float(self.client.get_balance())
        actual_lev = float(
            getattr(self.client, "actual_leverage", None)
            or self.config.get("leverage", 1)
            or 1
        )
        return position_budget(
            available_balance, self.config, leverage=actual_lev
        )

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

    def check_position_limit(
        self, side: str = "", quantity: float = 0.0, price: float = 0.0
    ) -> bool:
        """
        Check the largest one-sided exposure if pending orders and this order fill.
        """
        position = self.client.get_position()
        pos_side = str(position.get("side", "none")).lower()
        pos_size = float(position.get("size", 0) or 0)
        pos_notional = abs(float(position.get("notional", 0) or 0))
        if pos_notional == 0 and pos_size != 0:
            pos_notional = abs(pos_size) * float(price or 0)

        if pos_side in ("short", "sell") or pos_size < 0:
            signed_position = -pos_notional
        elif pos_side in ("long", "buy") or pos_size > 0:
            signed_position = pos_notional
        else:
            signed_position = 0.0

        pending_buys = 0.0
        pending_sells = 0.0
        for order in self.client.get_open_orders():
            order_side = str(order.get("side", "")).lower()
            order_price = float(order.get("price", 0) or 0)
            order_amount = float(order.get("remaining") or order.get("amount") or 0)
            order_notional = float(order.get("cost", 0) or order_amount * order_price)
            if order_side == "buy":
                pending_buys += order_notional
            elif order_side == "sell":
                pending_sells += order_notional

        candidate_notional = max(0.0, float(quantity)) * max(0.0, float(price))
        if side.lower() == "buy":
            pending_buys += candidate_notional
        elif side.lower() == "sell":
            pending_sells += candidate_notional

        # A one-way futures position can only be long or short at a time.
        notional = max(
            abs(signed_position + pending_buys),
            abs(signed_position - pending_sells),
        )

        max_position_limit = self.get_max_position_limit()
        if notional > max_position_limit:
            self.logger.risk(
                f"Projected position limit reached: ${notional:,.2f} > "
                f"${max_position_limit:,.2f} (includes pending orders; "
                f"{min(60.0, float(self.config.get('max_position_balance_percent', 60.0))):.1f}% wallet cap)"
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
        order_size = abs(float(quantity))
        is_reducing = (
            (side.lower() == "sell" and is_long and order_size <= abs(pos_size)) or
            (side.lower() == "buy" and is_short and order_size <= abs(pos_size))
        )

        if not is_reducing:
            # Check position limit for position-expanding orders
            try:
                within_limit = self.check_position_limit(side, quantity, price)
            except Exception as e:
                self.logger.error(f"Failed to verify projected position exposure: {e}")
                return False
            if not within_limit:
                self.logger.risk(f"Order blocked: projected position limit reached ({side} {quantity} @ ${price:,.2f})")
                return False

            # Check available balance
            try:
                balance = self.client.get_balance()
                leverage = effective_leverage(
                    self.config.get("symbol", ""),
                    self.config.get("leverage", 5),
                )
                if leverage <= 0:
                    self.logger.error(f"Invalid leverage configured for risk check: {leverage}")
                    return False
                required_margin = (quantity * price) / leverage

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

    def get_compounded_quantity(self, base_qty: float, current_price: float = 0.0, grid_levels_count: int = 10) -> float:
        """
        Calculate compounded order quantity based on realized equity growth,
        strictly capped by available liquid wallet balance and configured max_position_usdt limits.
        """
        try:
            if self.initial_balance <= 0 or base_qty <= 0:
                return base_qty

            # 1. Calculate growth ratio relative to initial balance
            realized_gain = max(0.0, self.realized_pnl)
            growth_ratio = (self.initial_balance + realized_gain) / self.initial_balance
            target_qty = base_qty * growth_ratio

            # 2. Cap each grid-side's aggregate notional to the allocation budget.
            if current_price > 0:
                max_position_limit = self.get_max_position_limit()
                orders_per_side = max(1, (grid_levels_count + 1) // 2)
                max_order_notional = max_position_limit / orders_per_side
                max_qty_by_position = max_order_notional / current_price
                target_qty = min(target_qty, max_qty_by_position)

            # 3. Do not compound when wallet balance cannot be verified.
            try:
                wallet_balance = float(self.client.get_wallet_balance())
                if wallet_balance <= 0:
                    return 0.0
            except Exception as e:
                self.logger.error(f"Failed to fetch wallet balance for compounding cap: {e}")
                return 0.0

            final_qty = max(0.0, round(target_qty, 6))
            return final_qty

        except Exception as e:
            self.logger.error(f"Error in get_compounded_quantity: {e}")
            return 0.0
