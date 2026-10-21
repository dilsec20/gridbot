"""
Verification Test for Dynamic Trailing Take-Profit (Profit Rider) Engine.
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.logger import BotLogger
from src.binance_client import BinanceClient
from src.risk_manager import RiskManager
from src.grid_engine import GridEngine, GridSide, GridOrderStatus

def test_trailing_tp():
    print("Testing Dynamic Trailing Take-Profit Engine...")
    logger = BotLogger("scratch_logs/test_tp.log")

    class MockClient(BinanceClient):
        def __init__(self):
            self.symbol = "BTC/USDT"
            self.orders_placed = []
            self.order_counter = 1000
            self.logger = logger

        def get_price(self):
            return 100.0

        def get_symbol_info(self):
            return {"tick_size": 2, "lot_size": 2, "min_qty": 0.001, "min_notional": 0.0}

        def place_limit_order(self, side, quantity, price, client_order_id=None):
            self.order_counter += 1
            order = {
                "id": str(self.order_counter),
                "symbol": "BTC/USDT",
                "side": side,
                "amount": quantity,
                "price": price,
            }
            self.orders_placed.append(order)
            return order

        def place_market_order(self, side, quantity, reduce_only=False):
            self.order_counter += 1
            order = {
                "id": str(self.order_counter),
                "side": side,
                "amount": quantity,
                "filled": quantity,
                "average": 109.40,
            }
            self.orders_placed.append(order)
            return order

        def cancel_order(self, order_id):
            return True

        def get_open_orders(self):
            return []

        def get_balance(self):
            return 5000.0

        def get_wallet_balance(self):
            return 5000.0

        def get_position(self):
            return {"size": 0, "side": "none", "entry_price": 0, "unrealized_pnl": 0}

    config = {
        "symbol": "BTC/USDT",
        "grid_levels": 4,
        "spacing_mode": "usdt",
        "grid_spacing_usdt": 1.0,
        "quantity_per_grid": 1.0,
        "leverage": 5,
        "trailing_tp_enabled": True,
        "trailing_tp_callback_percent": 0.5,
    }

    client = MockClient()
    risk_manager = RiskManager(config, client, logger)
    risk_manager.initialize()

    grid_engine = GridEngine(config, client, risk_manager, logger)
    grid_engine.initialize()

    # Find a SELL level
    sell_level = [l for l in grid_engine.grid_levels if l.side == GridSide.SELL][0]
    sell_price = sell_level.price # $101.00
    print(f"Target SELL level price: ${sell_price}")

    # 1. Price reaches SELL target -> activates TRAILING_TP
    grid_engine.update_price(101.00)
    assert sell_level.status == GridOrderStatus.TRAILING_TP, "Status should change to TRAILING_TP!"
    assert sell_level.peak_price == 101.00, "Peak price should be set to 101.00!"
    print("✅ Step 1 Passed: Trailing TP activated on price target hit!")

    # 2. Price pumps to $110.00 -> peak_price rises
    grid_engine.update_price(110.00)
    assert sell_level.peak_price == 110.00, "Peak price should rise to 110.00!"
    expected_stop = round(110.00 * (1.0 - 0.005), 2) # $109.45
    assert sell_level.trailing_stop == expected_stop, f"Trailing stop mismatch: {sell_level.trailing_stop} vs {expected_stop}"
    print(f"✅ Step 2 Passed: Trailing Peak rose to $110.00 (Trailing Stop: ${sell_level.trailing_stop})")

    # 3. Price drops to $109.40 (below trailing stop $109.45) -> Triggers SELL execution!
    grid_engine.update_price(109.40)
    assert sell_level.status == GridOrderStatus.FILLED, "Status should be FILLED after trailing TP trigger!"
    assert any(
        level.side == GridSide.BUY and level.price == 108.40
        for level in grid_engine.grid_levels
    ), "Replacement BUY must be spaced from the actual market fill price!"
    print(f"✅ Step 3 Passed: Trailing TP triggered on 0.5% pullback! Locked in peak profit @ $109.40!")

    print("==================================================")
    print("ALL TRAILING TAKE-PROFIT TESTS PASSED 100% PERFECTLY!")

if __name__ == "__main__":
    test_trailing_tp()
