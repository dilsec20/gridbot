"""
Grid Trading Engine — Core strategy logic.
Manages native deque grid levels, O(1) sliding window expansion, state-machine inventory bias balancing, and fill detection.
Includes exchange order rebuilding on startup and persistent state saving.
"""

import time
import json
import os
import bisect
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


class InventoryState(Enum):
    NORMAL = "normal"
    BIAS_LIMIT = "bias_limit"
    RECOVERY = "recovery"


@dataclass
class GridLevel:
    """Represents a single grid level with its order state."""
    price: float
    side: GridSide
    status: GridOrderStatus = GridOrderStatus.PENDING
    order_id: Optional[str] = None
    filled_at: Optional[float] = None
    is_replacement: bool = False  # True = placed after a fill (completes a cycle when filled)
    index: int = 0


class GridEngine:
    """
    Production-Hardened Core Grid Engine with:
    - Pure Native Deque O(1) Sliding Window
    - Trend Recovery State Machine (NORMAL, BIAS_LIMIT, RECOVERY)
    - Live Exchange Order Rebuilding on Startup (Reboot Resilience)
    - State Persistence (data/state.json)
    - Boundary Self-Healing & Invariant-Preserving Sorting
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

        # Inventory Exposure Configurable Thresholds & State Machine
        self.inventory_bias_limit_ratio = config.get("inventory_bias_limit", 0.65)
        self.inventory_state = InventoryState.NORMAL

        # Persistent State File Path
        self.state_file = os.path.join("data", "state.json")

        # Native O(1) Deque Grid Level Storage
        self.grid_levels: deque[GridLevel] = deque()
        self.completed_cycles = 0
        self.current_price = 0.0
        self.grid_low = 0.0
        self.grid_high = 0.0
        self.grid_spacing = 0.0
        self.tick_size = 2
        self.is_running = False

        # Live boundary prices maintained in O(1) time
        self.lowest_buy_price: float = 0.0
        self.highest_sell_price: float = 0.0

        # Track order IDs to grid levels for fast O(1) lookup
        self._order_to_level: dict[str, GridLevel] = {}
        self._known_order_ids: set[str] = set()

        # Load persistent state if available
        self._load_state()

    def _load_state(self):
        """Load persistent bot state from disk (data/state.json)."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.completed_cycles = data.get("completed_cycles", 0)
                    state_val = data.get("inventory_state", "normal")
                    try:
                        self.inventory_state = InventoryState(state_val)
                    except Exception:
                        self.inventory_state = InventoryState.NORMAL
                    self.logger.system(f"💾 Loaded persistent state: cycles={self.completed_cycles}, inventory_state={self.inventory_state.value}")
        except Exception as e:
            self.logger.error(f"Error loading state from {self.state_file}: {e}")

    def _save_state(self):
        """Save persistent bot state to disk (data/state.json)."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            state_data = {
                "completed_cycles": self.completed_cycles,
                "inventory_state": self.inventory_state.value,
                "realized_pnl": self.risk_manager.get_realized_pnl(),
                "last_updated": time.time()
            }
            with open(self.state_file, "w") as f:
                json.dump(state_data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving state to {self.state_file}: {e}")

    def initialize(self):
        """Calculate grid levels and place initial orders or rebuild from exchange."""
        self.logger.grid("Initializing production-hardened Deque grid engine...")

        # Get current price
        self.current_price = self.client.get_price()

        # Get symbol info for precision
        symbol_info = self.client.get_symbol_info()
        self.tick_size = symbol_info.get('tick_size', 4)
        if not isinstance(self.tick_size, int) or self.tick_size < 0:
            self.tick_size = 4

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

        half_levels = self.grid_levels_count // 2
        self.grid_low = round(self.current_price - (half_levels * self.grid_spacing), self.tick_size)
        self.grid_high = round(self.current_price + (half_levels * self.grid_spacing), self.tick_size)

        # Check if live exchange orders exist on Binance to rebuild state
        try:
            open_orders = self.client.get_open_orders()
            matching_orders = [o for o in open_orders if o.get("symbol") == self.symbol or not o.get("symbol")]
            if matching_orders and len(matching_orders) >= 2:
                self.logger.grid(f"🔄 Rebuilding Deque state from {len(matching_orders)} live exchange orders...")
                self._rebuild_from_exchange_orders(matching_orders)
                self.is_running = True
                self._save_state()
                return
        except Exception as e:
            self.logger.error(f"Error checking live exchange orders for rebuild: {e}")

        # Construct Fresh Native Deque
        self.grid_levels = deque()
        self._order_to_level.clear()
        self._known_order_ids.clear()

        # BUY levels (lowest to highest)
        for i in reversed(range(half_levels)):
            price = round(self.current_price - ((i + 1) * self.grid_spacing), self.tick_size)
            level = GridLevel(price=price, side=GridSide.BUY)
            self.grid_levels.append(level)

        # SELL levels (lowest to highest)
        for i in range(half_levels):
            price = round(self.current_price + ((i + 1) * self.grid_spacing), self.tick_size)
            level = GridLevel(price=price, side=GridSide.SELL)
            self.grid_levels.append(level)

        self._reconcile_boundaries()

        # Place initial orders
        self._place_initial_orders()
        self.is_running = True
        self._save_state()

    def _rebuild_from_exchange_orders(self, orders: list):
        """Reconstruct native Deque grid state from active exchange orders on Binance."""
        self.grid_levels.clear()
        self._order_to_level.clear()
        self._known_order_ids.clear()

        parsed_levels = []
        for o in orders:
            price = float(o.get("price", 0.0))
            side_str = str(o.get("side", "")).lower()
            order_id = str(o.get("id", ""))
            side = GridSide.BUY if side_str == "buy" else GridSide.SELL

            level = GridLevel(
                price=price,
                side=side,
                status=GridOrderStatus.ACTIVE,
                order_id=order_id,
                is_replacement=False
            )
            parsed_levels.append(level)
            self._order_to_level[order_id] = level
            self._known_order_ids.add(order_id)

        parsed_levels.sort(key=lambda l: l.price)
        self.grid_levels = deque(parsed_levels)
        self._reconcile_boundaries()
        self.logger.grid(f"✅ Rebuilt Deque with {len(self.grid_levels)} active exchange orders (Lowest Buy: ${self.lowest_buy_price:,.2f}, Highest Sell: ${self.highest_sell_price:,.2f})")

    def _insert_level_sorted(self, level: GridLevel):
        """Insert level into Deque preserving strict price-sorted order (O(1) at bounds, bisect in middle)."""
        if not self.grid_levels:
            self.grid_levels.append(level)
        elif level.price < self.grid_levels[0].price:
            self.grid_levels.appendleft(level)
        elif level.price > self.grid_levels[-1].price:
            self.grid_levels.append(level)
        else:
            prices = [l.price for l in self.grid_levels]
            idx = bisect.bisect_left(prices, level.price)
            self.grid_levels.insert(idx, level)

        self._reconcile_boundaries()

    def _reconcile_boundaries(self):
        """Periodic self-healing sanity check for lowest_buy_price and highest_sell_price."""
        active_buys = [l.price for l in self.grid_levels if l.side == GridSide.BUY and l.status == GridOrderStatus.ACTIVE]
        active_sells = [l.price for l in self.grid_levels if l.side == GridSide.SELL and l.status == GridOrderStatus.ACTIVE]

        if active_buys:
            self.lowest_buy_price = min(active_buys)
        elif self.current_price > 0:
            self.lowest_buy_price = self.current_price

        if active_sells:
            self.highest_sell_price = max(active_sells)
        elif self.current_price > 0:
            self.highest_sell_price = self.current_price

    def _place_initial_orders(self):
        """Place all initial grid orders."""
        self.logger.grid("Placing initial grid orders...")
        placed = 0

        for level in self.grid_levels:
            if not self.risk_manager.can_place_order(level.side.value, self.quantity, level.price):
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
                time.sleep(0.08)
            else:
                level.status = GridOrderStatus.CANCELLED
                self.logger.warn(f"Failed to place {level.side.value} @ ${level.price:,.2f}")

        self.logger.grid(f"Placed {placed}/{len(self.grid_levels)} grid orders")

    def check_and_process_fills(self):
        """Poll open orders to detect fills in O(1) set operations."""
        if not self.is_running:
            return

        try:
            open_orders = self.client.get_open_orders()
            current_order_ids = {order["id"] for order in open_orders}
            filled_order_ids = self._known_order_ids - current_order_ids

            for order_id in filled_order_ids:
                level = self._order_to_level.get(order_id)
                if level and level.status == GridOrderStatus.ACTIVE:
                    self._handle_fill(level)

            # Perform boundary self-healing check periodically
            self._reconcile_boundaries()

        except Exception as e:
            self.logger.error(f"Error checking fills: {e}")

    def process_order_fill_id(self, order_id: str):
        """Process an order fill by order_id."""
        level = self._order_to_level.get(str(order_id))
        if level and level.status == GridOrderStatus.ACTIVE:
            self._handle_fill(level)

    def handle_ws_fill(self, fill_data: dict):
        """Instant fill handler triggered directly by Binance WebSocket stream (<50ms)."""
        if not self.is_running:
            return

        order_id = str(fill_data.get("order_id", ""))
        fill_price = float(fill_data.get("price", 0.0))
        fill_side = str(fill_data.get("side", "")).lower()

        level = self._order_to_level.get(order_id)
        if level and level.status == GridOrderStatus.ACTIVE:
            self.logger.grid(f"⚡ INSTANT WS FILL DETECTED: Order #{order_id} ({fill_side.upper()} @ ${fill_price:,.2f})")
            self._handle_fill(level)

    def _handle_fill(self, filled_level: GridLevel):
        """Process an order fill and place opposite replacement order to complete cycle."""
        filled_level.status = GridOrderStatus.FILLED
        filled_level.filled_at = time.time()
        self._known_order_ids.discard(filled_level.order_id)

        self.logger.trade(filled_level.side.value.upper(), filled_level.price, self.quantity)

        # Fee tracking
        fill_notional = filled_level.price * self.quantity
        if hasattr(self.risk_manager, 'perf_tracker') and self.risk_manager.perf_tracker:
            self.risk_manager.perf_tracker.record_fill(fill_notional)

        # Calculate replacement side and price
        if filled_level.side == GridSide.BUY:
            new_side = GridSide.SELL
            new_price = round(filled_level.price + self.grid_spacing, self.tick_size)
        else:
            new_side = GridSide.BUY
            new_price = round(filled_level.price - self.grid_spacing, self.tick_size)

        if filled_level.is_replacement:
            self.completed_cycles += 1
            cycle_pnl = self.grid_spacing * self.quantity

            self.risk_manager.add_realized_pnl(cycle_pnl)
            total_pnl = self.risk_manager.get_realized_pnl()

            self.logger.grid(
                f"Grid cycle #{self.completed_cycles} completed! PnL: "
                f"${cycle_pnl:+.4f} | Total: ${total_pnl:+.4f}"
            )

            current_balance = 0.0
            try:
                current_balance = float(self.client.get_balance() or self.client.get_wallet_balance() or 0.0)
            except Exception:
                pass
            if hasattr(self.risk_manager, 'perf_tracker') and self.risk_manager.perf_tracker:
                self.risk_manager.perf_tracker.record_cycle_complete(
                    self.completed_cycles, cycle_pnl, total_pnl, current_balance
                )

            # Auto-Compounding Check
            if self.config.get("auto_compound", True) and self.completed_cycles % 5 == 0:
                old_qty = self.quantity
                self.quantity = self.risk_manager.get_compounded_quantity(
                    self.quantity, self.config.get("grid_spacing_percent", 0.5)
                )
                if self.quantity != old_qty:
                    self.logger.system(f"💰 Auto-Compounded order size: {old_qty} → {self.quantity}")

            # Save state on cycle completion
            self._save_state()
        else:
            self.logger.grid(
                f"Initial {filled_level.side.value.upper()} filled at ${filled_level.price:,.4f} — "
                f"waiting for opposite fill to complete cycle..."
            )

        # Place opposite replacement order & maintain Deque synchronization
        if self.risk_manager.can_place_order(new_side.value, self.quantity, new_price):
            order = self.client.place_limit_order(
                side=new_side.value,
                quantity=self.quantity,
                price=new_price,
            )

            if order:
                new_level = GridLevel(
                    price=new_price,
                    side=new_side,
                    status=GridOrderStatus.ACTIVE,
                    order_id=order["id"],
                    is_replacement=True,
                )
                self._order_to_level[order["id"]] = new_level
                self._known_order_ids.add(order["id"])

                # Deque Synchronization: Insert replacement level preserving strict price order
                self._insert_level_sorted(new_level)
        else:
            self.logger.warn(f"Risk manager blocked replacement order at ${new_price:,.2f}")

    def _check_auto_trailing_recenter(self):
        """
        Pure Native O(1) Deque Sliding Window Expansion & Trend Recovery State Machine.
        """
        if not self.is_running or self.current_price <= 0:
            return

        if self.lowest_buy_price <= 0 or self.highest_sell_price <= 0:
            self._reconcile_boundaries()
            if self.lowest_buy_price <= 0 or self.highest_sell_price <= 0:
                return

        # 1. Calculate Inventory Bias & Update State Machine
        inventory_notional = 0.0
        max_inventory_bias = 500.0
        try:
            pos = self.client.get_position()
            pos_amount = float(pos.get("amount", 0) or 0)
            pos_side = str(pos.get("side", "none")).lower()
            if pos_side == "short":
                pos_amount = -abs(pos_amount)
            inventory_notional = pos_amount * self.current_price
            max_inventory_bias = self.config.get("max_position_usdt", 500.0) * self.inventory_bias_limit_ratio
        except Exception as e:
            self.logger.error(f"Error checking inventory bias: {e}")

        recovery_threshold = max_inventory_bias * 0.75

        # State Machine Transition Logic
        if abs(inventory_notional) >= max_inventory_bias:
            if self.inventory_state != InventoryState.BIAS_LIMIT:
                self.inventory_state = InventoryState.BIAS_LIMIT
                self.logger.risk(f"🛡️ Inventory State -> BIAS_LIMIT (Notional: ${inventory_notional:,.2f})")
                self._save_state()
        elif abs(inventory_notional) <= recovery_threshold:
            if self.inventory_state == InventoryState.BIAS_LIMIT:
                self.inventory_state = InventoryState.RECOVERY
                self.logger.risk(f"🛡️ Inventory State -> RECOVERY (Notional: ${inventory_notional:,.2f})")
                self._save_state()
            elif self.inventory_state == InventoryState.RECOVERY:
                self.inventory_state = InventoryState.NORMAL
                self.logger.risk(f"🛡️ Inventory State -> NORMAL (Notional: ${inventory_notional:,.2f})")
                self._save_state()

        active_count = sum(1 for l in self._order_to_level.values() if l.status == GridOrderStatus.ACTIVE)

        # Deque Lower Expansion: Require price to drop past lowest buy by 1 full spacing step
        if self.current_price <= (self.lowest_buy_price - 1.0 * self.grid_spacing):
            if self.inventory_state == InventoryState.BIAS_LIMIT and inventory_notional >= max_inventory_bias:
                self.logger.risk(f"🛡️ Inventory Shield Active [BIAS_LIMIT]: Long inventory (${inventory_notional:,.2f}) at limit! Pausing BUY expansion.")
                return

            new_price = round(self.lowest_buy_price - self.grid_spacing, self.tick_size)
            if new_price > 0:
                if self.risk_manager.can_place_order("BUY", self.quantity, new_price):
                    # Pure O(1) Deque Eviction: Evict top unfilled SELL from right via pop()
                    if active_count >= self.grid_levels_count and self.grid_levels:
                        top_sell = self.grid_levels[-1]
                        if top_sell.side == GridSide.SELL and not top_sell.is_replacement and top_sell.status == GridOrderStatus.ACTIVE:
                            try:
                                self.client.cancel_order(top_sell.order_id)
                                top_sell.status = GridOrderStatus.CANCELLED
                                self._order_to_level.pop(top_sell.order_id, None)
                                self._known_order_ids.discard(top_sell.order_id)
                                self.grid_levels.pop()  # Pure O(1) Right Eviction!
                            except Exception as e:
                                self.logger.error(f"Failed to evict top SELL order #{top_sell.order_id}: {e}")

                    self.logger.grid(f"⚡ Pure Deque O(1) Expansion: Appending BUY level @ ${new_price:,.2f}")
                    order = self.client.place_limit_order("BUY", self.quantity, new_price)
                    if order and "id" in order:
                        new_level = GridLevel(
                            price=new_price,
                            side=GridSide.BUY,
                            status=GridOrderStatus.ACTIVE,
                            order_id=order["id"]
                        )
                        self._insert_level_sorted(new_level)
                        self._order_to_level[order["id"]] = new_level
                        self._known_order_ids.add(order["id"])

        # Deque Upper Expansion: Require price to rise past highest sell by 1 full spacing step
        elif self.current_price >= (self.highest_sell_price + 1.0 * self.grid_spacing):
            if self.inventory_state == InventoryState.BIAS_LIMIT and inventory_notional <= -max_inventory_bias:
                self.logger.risk(f"🛡️ Inventory Shield Active [BIAS_LIMIT]: Short inventory (${inventory_notional:,.2f}) at limit! Pausing SELL expansion.")
                return

            new_price = round(self.highest_sell_price + self.grid_spacing, self.tick_size)
            if self.risk_manager.can_place_order("SELL", self.quantity, new_price):
                # Pure O(1) Deque Eviction: Evict bottom unfilled BUY from left via popleft()
                if active_count >= self.grid_levels_count and self.grid_levels:
                    bottom_buy = self.grid_levels[0]
                    if bottom_buy.side == GridSide.BUY and not bottom_buy.is_replacement and bottom_buy.status == GridOrderStatus.ACTIVE:
                        try:
                            self.client.cancel_order(bottom_buy.order_id)
                            bottom_buy.status = GridOrderStatus.CANCELLED
                            self._order_to_level.pop(bottom_buy.order_id, None)
                            self._known_order_ids.discard(bottom_buy.order_id)
                            self.grid_levels.popleft()  # Pure O(1) Left Eviction!
                        except Exception as e:
                            self.logger.error(f"Failed to evict bottom BUY order #{bottom_buy.order_id}: {e}")

                self.logger.grid(f"⚡ Pure Deque O(1) Expansion: Appending SELL level @ ${new_price:,.2f}")
                order = self.client.place_limit_order("SELL", self.quantity, new_price)
                if order and "id" in order:
                    new_level = GridLevel(
                        price=new_price,
                        side=GridSide.SELL,
                        status=GridOrderStatus.ACTIVE,
                        order_id=order["id"]
                    )
                    self._insert_level_sorted(new_level)
                    self._order_to_level[order["id"]] = new_level
                    self._known_order_ids.add(order["id"])

    def update_price(self, price: float):
        """Update the current market price (from WebSocket or polling)."""
        self.current_price = price

    def cancel_all(self):
        """Cancel all active grid orders. Used during shutdown."""
        self.is_running = False
        self.logger.grid("Cancelling all grid orders...")
        try:
            self.client.cancel_all_orders()
        except Exception as e:
            self.logger.error(f"Failed to cancel all orders during shutdown: {e}")

    def get_stats(self) -> dict:
        """Get current grid statistics for dashboard display."""
        active_buys = sum(
            1 for l in self._order_to_level.values()
            if l.status == GridOrderStatus.ACTIVE and l.side == GridSide.BUY
        )
        active_sells = sum(
            1 for l in self._order_to_level.values()
            if l.status == GridOrderStatus.ACTIVE and l.side == GridSide.SELL
        )

        return {
            "price": self.current_price,
            "pnl": self.risk_manager.get_realized_pnl(),
            "cycles": self.completed_cycles,
            "open_buys": active_buys,
            "open_sells": active_sells,
            "grid_low": self.grid_low,
            "grid_high": self.grid_high,
            "inventory_state": self.inventory_state.value,
        }

    def get_display_levels(self) -> list:
        """Get list of current grid levels for UI display."""
        levels_map = {}
        for l in self.grid_levels:
            levels_map[l.price] = l
        for l in self._order_to_level.values():
            levels_map[l.price] = l
        return list(levels_map.values())

    def print_grid(self):
        """Print the current grid state."""
        self.logger.grid("Current grid state:")
        for level in self.grid_levels:
            status_icon = {
                GridOrderStatus.ACTIVE: "🟢",
                GridOrderStatus.FILLED: "✅",
                GridOrderStatus.PENDING: "⏳",
                GridOrderStatus.CANCELLED: "❌",
            }.get(level.status, "❓")
            self.logger.grid(
                f"  {status_icon} {level.side.value.upper()} @ ${level.price:,.4f} "
                f"[{level.status.value}]"
            )
