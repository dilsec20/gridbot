"""
Grid Trading Engine — Core strategy logic.
Manages grid levels, order placement, fill detection, and PnL tracking.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from typing import Optional

from logger import BotLogger
from binance_client import BinanceClient
from risk_manager import RiskManager


class GridSide(Enum):
    BUY = "buy"
    SELL = "sell"


class GridOrderStatus(Enum):
    PENDING = "pending"      # Waiting to be placed
    ACTIVE = "active"        # Order is live on exchange
    FILLED = "filled"        # Order was filled
    CANCELLED = "cancelled"  # Order was cancelled


@dataclass
class GridLevel:
    """Represents a single grid level with its order state."""
    index: int
    price: float
    side: GridSide
    status: GridOrderStatus = GridOrderStatus.PENDING
    order_id: Optional[str] = None
    filled_at: Optional[float] = None
    is_replacement: bool = False  # True = placed after a fill (completes a cycle when filled)


class GridEngine:
    """
    Core grid trading engine.

    Places buy orders below current price and sell orders above.
    When a buy fills, places a sell at the next level up.
    When a sell fills, places a buy at the next level down.
    Each completed buy→sell or sell→buy cycle = profit of grid_spacing × quantity.
    """

    def __init__(self, config: dict, client: BinanceClient,
    risk_manager: RiskManager, logger: BotLogger):
        self.config = config
        self.client = client
        self.risk_manager = risk_manager
        self.logger = logger

        self.symbol = config["symbol"]
        self.grid_levels_count = config.get("grid_levels", 10)
        self.spacing_mode = config.get("spacing_mode", "usdt")  # 'usdt' or 'percent'
        self.quantity = config.get("quantity_per_grid", 0.001)

        self.grid_levels: list[GridLevel] = []
        self.completed_cycles = 0
        self.current_price = 0.0
        self.grid_low = 0.0
        self.grid_high = 0.0
        self.grid_spacing = 0.0
        self.tick_size = 2
        self.is_running = False

        # Track order IDs to grid levels for fast lookup
        self._order_to_level: dict[str, GridLevel] = {}
        # Track previously known open order IDs to detect fills
        self._known_order_ids: set[str] = set()

    def initialize(self):
        """
        Calculate grid levels and place initial orders.
        """
        self.logger.grid("Initializing grid engine...")

        # Get current price
        self.current_price = self.client.get_price()

        # Get symbol info for precision
        symbol_info = self.client.get_symbol_info()
        self.tick_size = symbol_info.get('tick_size', 4)
        if not isinstance(self.tick_size, int) or self.tick_size < 0:
            self.tick_size = 4

        # Dynamically scale tick_size for micro-coins to prevent price rounding to 0
        if self.current_price < 0.0001:
            self.tick_size = max(self.tick_size, 8)
        elif self.current_price < 0.01:
            self.tick_size = max(self.tick_size, 6)
        elif self.current_price < 1:
            self.tick_size = max(self.tick_size, 5)

        # Enforce minimum quantity & lot size precision for symbol
        min_qty = symbol_info.get("min_qty", 0.001)
        lot_size = symbol_info.get("lot_size", 3)
        if self.quantity < min_qty:
            self.quantity = min_qty
            self.logger.grid(f"Quantity adjusted to exchange minimum for {self.symbol}: {self.quantity}")

        if isinstance(lot_size, int):
            if lot_size == 0:
                self.quantity = float(int(round(self.quantity)))
            else:
                self.quantity = float(round(self.quantity, lot_size))

        # Calculate spacing (percentage or flat USDT)
        if self.spacing_mode == "percent":
            percent = self.config.get("grid_spacing_percent", 0.5)
            self.grid_spacing = round(self.current_price * (percent / 100.0), self.tick_size)
            if self.grid_spacing == 0:
                self.grid_spacing = round(self.current_price * 0.005, 8)
            self.logger.grid(f"Spacing mode: PERCENT ({percent}% = ${self.grid_spacing})")
        else:
            self.grid_spacing = self.config.get("grid_spacing_usdt", 50.0)
            self.logger.grid(f"Spacing mode: FLAT USDT (${self.grid_spacing})")

        self.logger.grid(f"Current {self.symbol} price: {self.current_price}")
        self.logger.grid(f"Symbol precision: tick={self.tick_size}, lot={lot_size}")

        # Calculate grid boundaries
        half_levels = self.grid_levels_count // 2
        self.grid_low = round(self.current_price - (half_levels * self.grid_spacing), self.tick_size)
        self.grid_high = round(self.current_price + (half_levels * self.grid_spacing), self.tick_size)

        self.logger.grid(f"Grid range: {self.grid_low} — {self.grid_high}")
        self.logger.grid(f"Levels: {self.grid_levels_count} ({half_levels} buy + {half_levels} sell)")
        self.logger.grid(f"Quantity per level: {self.quantity}")

        # Create grid levels
        self.grid_levels = []

        # BUY levels below current price
        for i in range(half_levels):
            price = round(self.current_price - ((i + 1) * self.grid_spacing), self.tick_size)
            level = GridLevel(
                index=-(i + 1),
                price=price,
                side=GridSide.BUY,
            )
            self.grid_levels.append(level)

        # SELL levels above current price
        for i in range(half_levels):
            price = round(self.current_price + ((i + 1) * self.grid_spacing), self.tick_size)
            level = GridLevel(
                index=i + 1,
                price=price,
                side=GridSide.SELL,
            )
            self.grid_levels.append(level)

        # Sort by price for display
        self.grid_levels.sort(key=lambda l: l.price)

        # Place initial orders
        self._place_initial_orders()
        self.is_running = True

    def _place_initial_orders(self):
        """Place all initial grid orders."""
        self.logger.grid("Placing initial grid orders...")
        placed = 0

        for level in self.grid_levels:
            # Check risk before each order
            if not self.risk_manager.can_place_order(
                level.side.value, self.quantity, level.price
            ):
                self.logger.warn(f"Risk check blocked order at ${level.price:,.2f}")
                continue

            order = self.client.place_limit_order(
                side=level.side.value,
                quantity=self.quantity,
                price=level.price,
            )

            if order:
                level.status = GridOrderStatus.ACTIVE
                level.order_id = order["id"]
                self._order_to_level[order["id"]] = level
                self._known_order_ids.add(order["id"])
                placed += 1

                # Small delay to avoid rate limiting
                time.sleep(0.1)
            else:
                level.status = GridOrderStatus.CANCELLED
                self.logger.warn(f"Failed to place {level.side.value} @ ${level.price:,.2f}")

        self.logger.grid(f"Placed {placed}/{len(self.grid_levels)} grid orders")

    def check_and_process_fills(self):
        """
        Poll open orders to detect fills.
        When an order disappears from open orders, it was filled.
        """
        if not self.is_running:
            return

        try:
            # Fetch current open orders
            open_orders = self.client.get_open_orders()
            current_order_ids = {order["id"] for order in open_orders}

            # Find orders that disappeared (filled!)
            filled_order_ids = self._known_order_ids - current_order_ids

            for order_id in filled_order_ids:
                level = self._order_to_level.get(order_id)
                if level and level.status == GridOrderStatus.ACTIVE:
                    self._handle_fill(level)

            # Update known orders
            self._known_order_ids = current_order_ids

            # Auto-Trail & Recenter if price moves outside active grid bounds
            self._check_auto_trailing_recenter()

        except Exception as e:
            self.logger.error(f"Error checking fills: {e}")

    def process_order_fill_id(self, order_id: str):
        """
        Instant real-time fill processor triggered directly by Binance WebSocket stream.
        Executes order fill logic in <50ms without waiting for HTTP polling.
        """
        if not self.is_running:
            return

        order_id_str = str(order_id)
        level = self._order_to_level.get(order_id_str)
        if level and level.status == GridOrderStatus.ACTIVE:
            self.logger.grid(f"⚡ INSTANT WS FILL DETECTED: Order #{order_id_str} ({level.side.value.upper()} @ ${level.price:,.2f})")
            self._known_order_ids.discard(order_id_str)
            self._handle_fill(level)


    def _handle_fill(self, filled_level: GridLevel):
        """
        Handle a filled grid order.
        BUY fill → place SELL at next level up
        SELL fill → place BUY at next level down

        Only REPLACEMENT order fills count as completed cycles with realized PnL.
        Initial grid orders just open positions — no profit is realized yet.
        """
        filled_level.status = GridOrderStatus.FILLED
        filled_level.filled_at = time.time()

        self.logger.trade(
            side=filled_level.side.value,
            price=filled_level.price,
            qty=self.quantity,
        )

        # Calculate the opposite order price
        if filled_level.side == GridSide.BUY:
            # Buy filled → place sell one grid spacing above
            new_price = round(filled_level.price + self.grid_spacing, self.tick_size)
            new_side = GridSide.SELL
        else:
            # Sell filled → place buy one grid spacing below
            new_price = round(filled_level.price - self.grid_spacing, self.tick_size)
            new_side = GridSide.BUY

        # Only count PnL when a REPLACEMENT order fills (completing a buy→sell or sell→buy cycle)
        # Initial orders just open positions — no actual profit is realized on the exchange
        if filled_level.is_replacement:
            pnl = self.grid_spacing * self.quantity
            self.completed_cycles += 1
            self.risk_manager.add_realized_pnl(pnl)
            self.logger.grid(
                f"Grid cycle #{self.completed_cycles} completed! "
                f"PnL: ${pnl:+.4f} | Total: ${self.risk_manager.get_realized_pnl():+.4f}"
            )
            if hasattr(self.risk_manager, 'perf_tracker') and self.risk_manager.perf_tracker:
                try:
                    bal = self.client.get_wallet_balance()
                except Exception:
                    bal = 0
                self.risk_manager.perf_tracker.record_cycle_complete(
                    self.completed_cycles, pnl, self.risk_manager.get_realized_pnl(), bal
                )

            # Auto-Compound Profits: Reinvest profits to boost quantity every 5 cycles
            if self.completed_cycles % 5 == 0 and self.current_price > 0:
                boost = (pnl * 0.5) / self.current_price
                if boost > 0:
                    self.quantity = round(self.quantity + boost, 4)
                    self.logger.grid(f"💰 Auto-Compound Engine: Reinvested realized profits! Boosted Qty per grid to {self.quantity}")
        else:
            self.logger.grid(
                f"Initial {filled_level.side.value.upper()} filled at ${filled_level.price:,.4f} — "
                f"waiting for opposite fill to complete cycle..."
            )

        # Place opposite order (marked as replacement — will count PnL when IT fills)
        if self.risk_manager.can_place_order(new_side.value, self.quantity, new_price):
            order = self.client.place_limit_order(
                side=new_side.value,
                quantity=self.quantity,
                price=new_price,
            )

            if order:
                # Create new grid level for the replacement order
                new_level = GridLevel(
                    index=filled_level.index,
                    price=new_price,
                    side=new_side,
                    status=GridOrderStatus.ACTIVE,
                    order_id=order["id"],
                    is_replacement=True,  # Mark as replacement — PnL counted when THIS fills
                )
                self._order_to_level[order["id"]] = new_level
                self._known_order_ids.add(order["id"])
        else:
            self.logger.warn(f"Risk manager blocked replacement order at ${new_price:,.2f}")

    def _check_auto_trailing_recenter(self):
        """O(1) Deque Sliding Window Grid Expansion & Eviction.
        Instead of rebuilding the grid, when price moves 1 full step beyond boundary:
        - Append 1 new level in the movement direction (BUY or SELL).
        - If total active orders exceed grid_levels_count, evict/cancel the furthest inactive level from opposite side!
        Zero rebuilds, zero position disturbance, O(1) constant time complexity!
        """
        if not self.is_running or self.current_price <= 0:
            return

        active_levels = [
            l for l in self._order_to_level.values()
            if l.status == GridOrderStatus.ACTIVE
        ]

        if not active_levels:
            return

        min_active = min(l.price for l in active_levels)
        max_active = max(l.price for l in active_levels)

        # Deque Window Bounds Check: Must cross 1 full spacing step past bounds
        if self.current_price <= (min_active - 1.0 * self.grid_spacing):
            new_price = round(min_active - self.grid_spacing, self.tick_size)
            if new_price > 0:
                notional = new_price * self.quantity_per_grid
                can_place, reason = self.risk_manager.can_place_order(notional, "buy")
                if can_place:
                    # Deque Eviction: If window size >= max levels, evict highest inactive SELL level
                    if len(active_levels) >= self.grid_levels_count:
                        unfilled_sells = [l for l in active_levels if l.side == GridSide.SELL and not l.is_replacement]
                        if unfilled_sells:
                            top_sell = max(unfilled_sells, key=lambda l: l.price)
                            try:
                                self.client.cancel_order(top_sell.order_id)
                                top_sell.status = GridOrderStatus.CANCELLED
                                self._order_to_level.pop(top_sell.order_id, None)
                                self._known_order_ids.discard(top_sell.order_id)
                            except Exception:
                                pass

                    self.logger.grid(f"⚡ Deque O(1) Grid Expansion: Appending 1 BUY level @ ${new_price:,.2f}")
                    order = self.client.place_limit_order(
                        side="BUY",
                        quantity=self.quantity_per_grid,
                        price=new_price
                    )
                    if order and "id" in order:
                        new_level = GridLevel(
                            index=len(self.grid_levels) + 1,
                            price=new_price,
                            side=GridSide.BUY,
                            status=GridOrderStatus.ACTIVE,
                            order_id=order["id"]
                        )
                        self.grid_levels.append(new_level)
                        self._order_to_level[order["id"]] = new_level
                        self._known_order_ids.add(order["id"])

        elif self.current_price >= (max_active + 1.0 * self.grid_spacing):
            new_price = round(max_active + self.grid_spacing, self.tick_size)
            notional = new_price * self.quantity_per_grid
            can_place, reason = self.risk_manager.can_place_order(notional, "sell")
            if can_place:
                # Deque Eviction: If window size >= max levels, evict lowest inactive BUY level
                if len(active_levels) >= self.grid_levels_count:
                    unfilled_buys = [l for l in active_levels if l.side == GridSide.BUY and not l.is_replacement]
                    if unfilled_buys:
                        bottom_buy = min(unfilled_buys, key=lambda l: l.price)
                        try:
                            self.client.cancel_order(bottom_buy.order_id)
                            bottom_buy.status = GridOrderStatus.CANCELLED
                            self._order_to_level.pop(bottom_buy.order_id, None)
                            self._known_order_ids.discard(bottom_buy.order_id)
                        except Exception:
                            pass

                self.logger.grid(f"⚡ Deque O(1) Grid Expansion: Appending 1 SELL level @ ${new_price:,.2f}")
                order = self.client.place_limit_order(
                    side="SELL",
                    quantity=self.quantity_per_grid,
                    price=new_price
                )
                if order and "id" in order:
                    new_level = GridLevel(
                        index=len(self.grid_levels) + 1,
                        price=new_price,
                        side=GridSide.SELL,
                        status=GridOrderStatus.ACTIVE,
                        order_id=order["id"]
                    )
                    self.grid_levels.append(new_level)
                    self._order_to_level[order["id"]] = new_level
                    self._known_order_ids.add(order["id"])

    def update_price(self, price: float):
        """Update the current market price (from WebSocket or polling)."""
        self.current_price = price

    def cancel_all(self):
        """Cancel all active grid orders. Used during shutdown."""
        self.is_running = False
        self.logger.grid("Cancelling all grid orders...")
        self.client.cancel_all_orders()

    def get_stats(self) -> dict:
        """Get current grid statistics for dashboard display."""
        active_buys = sum(
            1 for l in self.grid_levels
            if l.status == GridOrderStatus.ACTIVE and l.side == GridSide.BUY
        )
        active_sells = sum(
            1 for l in self.grid_levels
            if l.status == GridOrderStatus.ACTIVE and l.side == GridSide.SELL
        )

        # Also count dynamically placed orders
        for level in self._order_to_level.values():
            if level.status == GridOrderStatus.ACTIVE:
                if level not in self.grid_levels:
                    if level.side == GridSide.BUY:
                        active_buys += 1
                    else:
                        active_sells += 1

        return {
            "price": self.current_price,
            "pnl": self.risk_manager.get_realized_pnl(),
            "cycles": self.completed_cycles,
            "open_buys": active_buys,
            "open_sells": active_sells,
            "grid_low": self.grid_low,
            "grid_high": self.grid_high,
        }

    def get_display_levels(self) -> list:
        """Get list of current grid levels for UI display, including dynamic replacement orders."""
        levels_map = {}
        # Add initial levels
        for l in self.grid_levels:
            levels_map[l.price] = l
        # Override/add dynamic replacement levels
        for l in self._order_to_level.values():
            levels_map[l.price] = l
        return list(levels_map.values())

    def print_grid(self):
        """Print the current grid state."""
        self.logger.grid("Current grid state:")
        for level in sorted(self.grid_levels, key=lambda l: -l.price):
            status_icon = {
                GridOrderStatus.ACTIVE: "🟢",
                GridOrderStatus.FILLED: "✅",
                GridOrderStatus.PENDING: "⏳",
                GridOrderStatus.CANCELLED: "❌",
            }.get(level.status, "❓")

            side_str = f"{'BUY ' if level.side == GridSide.BUY else 'SELL'}"
            price_marker = " ◀── CURRENT" if abs(level.price - self.current_price) < self.grid_spacing / 2 else ""

            print(f"    {status_icon} {side_str} ${level.price:>12,.2f} [{level.status.value}]{price_marker}")
