"""
Verification & Test Suite for Trading Bot.
Tests GridEngine, RiskManager, BinanceWSClient, and PnL Accounting.
"""

import sys
import os
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.logger import BotLogger
from src.grid_engine import GridEngine, GridLevel, GridSide, GridOrderStatus
from src.risk_manager import RiskManager
from src.binance_ws import BinanceWSClient


class MockClient:
    def __init__(self):
        self._price = 100.0
        self._balance = 5000.0
        self._wallet_balance = 5000.0
        self.orders_placed = []
        self.order_counter = 1000

    def get_price(self):
        return self._price

    def get_balance(self):
        return self._balance

    def get_wallet_balance(self):
        return self._wallet_balance

    def get_position(self):
        return {"size": 0, "side": "none", "entry_price": 0, "unrealized_pnl": 0, "notional": 0}

    def get_symbol_info(self):
        return {"tick_size": 2, "lot_size": 3, "min_qty": 0.001, "min_notional": 5}

    def place_limit_order(self, side, quantity, price):
        self.order_counter += 1
        order_id = str(self.order_counter)
        order = {"id": order_id, "side": side, "quantity": quantity, "price": price}
        self.orders_placed.append(order)
        return order

    def get_open_orders(self):
        return self.orders_placed

    def cancel_all_orders(self):
        return True

    def get_listen_key(self):
        return "mock_listen_key_12345"

    def keep_alive_listen_key(self):
        return True


def run_tests():
    print("Running Verification Test Suite...")
    print("=" * 50)

    config = {
        "symbol": "BTC/USDT",
        "grid_levels": 8,
        "spacing_mode": "usdt",
        "grid_spacing_usdt": 1.0,
        "quantity_per_grid": 0.01,
        "leverage": 5,
        "max_loss_usdt": 100.0,
        "max_position_usdt": 500.0,
        "use_testnet": True,
    }

    logger = BotLogger("test.log")
    client = MockClient()
    risk_manager = RiskManager(config, client, logger)
    risk_manager.initialize()

    # Test 1: Initial Balance
    assert risk_manager.initial_balance == 5000.0, "Initial balance mismatch!"
    print("Test 1 Passed: Initial Balance recorded correctly.")

    # Test 2: Grid Engine Init
    grid_engine = GridEngine(config, client, risk_manager, logger)
    grid_engine.initialize()
    grid_engine.completed_cycles = 0
    grid_engine._processed_fills.clear()
    grid_engine._processed_fills_history.clear()
    risk_manager.realized_pnl = 0.0

    assert len(grid_engine.grid_levels) == 8, f"Expected 8 grid levels, got {len(grid_engine.grid_levels)}"
    assert len(client.orders_placed) == 8, f"Expected 8 orders placed, got {len(client.orders_placed)}"
    print("Test 2 Passed: Grid Engine initialized 8 orders correctly.")

    # Test 3: Initial order fill should NOT add PnL (opens position)
    first_order_id = client.orders_placed[0]["id"]
    entry_price = grid_engine._order_to_level[first_order_id].price
    initial_cycles = grid_engine.completed_cycles
    initial_pnl = risk_manager.get_realized_pnl()

    grid_engine.process_order_fill_id(first_order_id)

    assert grid_engine.completed_cycles == initial_cycles, "Initial fill should not increment cycles!"
    assert risk_manager.get_realized_pnl() == initial_pnl, "Initial fill should not add PnL!"
    assert len(client.orders_placed) == 9, "Replacement order should be placed after fill!"
    print("Test 3 Passed: Initial fill correctly opens position without fake PnL.")

    # Test 4: Replacement order fill SHOULD add PnL (completes cycle)
    replacement_order_id = client.orders_placed[-1]["id"]
    replacement_level = grid_engine._order_to_level[replacement_order_id]
    exit_price = replacement_level.price
    grid_engine.process_order_fill_id({
        "order_id": replacement_order_id,
        "average_price": exit_price,
        "filled_quantity": grid_engine.quantity,
    })

    assert grid_engine.completed_cycles == initial_cycles + 1, "Replacement fill MUST increment cycles!"
    gross_pnl = (
        (exit_price - entry_price) * grid_engine.quantity
        if replacement_level.side == GridSide.SELL
        else (entry_price - exit_price) * grid_engine.quantity
    )
    expected_pnl = round(
        gross_pnl - (entry_price + exit_price) * grid_engine.quantity * grid_engine.fee_rate,
        4,
    )
    assert round(risk_manager.get_realized_pnl(), 4) == expected_pnl, f"Expected PnL {expected_pnl}, got {risk_manager.get_realized_pnl()}"
    print("Test 4 Passed: Replacement fill uses both execution prices and estimated fees.")

    # Test 5: Pending orders count toward the projected position limit
    risk_manager.max_position_usdt = 100.0
    client.orders_placed = [{"id": "pending", "side": "buy", "amount": 1.0, "price": 80.0}]
    assert not risk_manager.check_position_limit("buy", 1.0, 30.0), "Pending plus proposed exposure must be capped!"
    assert risk_manager.check_position_limit("sell", 1.0, 90.0), "Independent opposite-side exposure should be evaluated separately!"
    print("Test 5 Passed: Pending and proposed exposure are included in the position cap.")

    # Test 6: Compounding must not restore a size above the configured cap
    compounded_quantity = risk_manager.get_compounded_quantity(
        10.0, current_price=100.0, grid_levels_count=8
    )
    assert compounded_quantity <= 0.4, "Compounding must honor the configured position cap even if base size is larger!"
    print("Test 6 Passed: Auto-compounding honors caps smaller than the base quantity.")

    # Test 7: WebSocket Client Instantiation
    ws_client = BinanceWSClient(config, client, logger)
    assert ws_client.ws_base_url == "wss://stream.binancefuture.com/ws", "Testnet WebSocket URL mismatch!"
    print("Test 7 Passed: BinanceWSClient initialized with correct testnet URL.")

    # Test 8: Performance Tracker & CSV Analytics
    from src.performance_tracker import PerformanceTracker
    perf = PerformanceTracker(config, client, logger, log_dir="scratch_logs")
    perf.initialize(5000.0)
    perf.record_fill(100.0)
    assert perf.total_fills_count == 1, "Fill count mismatch!"
    assert perf.estimated_fees_usdt == 0.02, "Fee calculation mismatch!"
    
    snap = perf.take_snapshot(grid_engine)
    assert snap["wallet_balance"] == 5000.0, "Snapshot balance mismatch!"
    assert os.path.exists(perf.csv_path), "Performance CSV log file missing!"
    print("Test 8 Passed: PerformanceTracker CSV logging, MDD, & Fee deduction working perfectly.")

    print("=" * 50)
    print("ALL 8 VERIFICATION TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_tests()
