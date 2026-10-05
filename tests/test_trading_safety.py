import os
import sys
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from binance_client import BinanceClient
from grid_engine import GridEngine, GridLevel, GridOrderStatus, GridSide
from quant_engine import QuantEngine
from risk_manager import RiskManager


class FakeLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class FakeClient:
    def __init__(self):
        self.config = {}
        self.balance = 5_000.0
        self.position = {
            "size": 0.0,
            "side": "none",
            "notional": 0.0,
            "unrealized_pnl": 0.0,
        }
        self.open_orders = []
        self.placed_orders = []
        self.order_counter = 0

    def get_position(self):
        return self.position

    def get_open_orders(self):
        return self.open_orders

    def get_balance(self):
        return self.balance

    def get_wallet_balance(self):
        return self.balance

    def get_price(self):
        return 100.0

    def get_symbol_info(self):
        return {"tick_size": 2, "lot_size": 3, "min_qty": 0.001, "min_notional": 5.0}

    def place_limit_order(self, side, quantity, price, client_order_id=None):
        self.order_counter += 1
        order = {
            "id": str(self.order_counter),
            "side": side,
            "amount": quantity,
            "price": price,
        }
        self.placed_orders.append(order)
        return order

    def cancel_all_orders(self):
        return True


class TradingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.logger = FakeLogger()

    def test_position_cap_includes_pending_and_proposed_one_sided_exposure(self):
        client = FakeClient()
        client.open_orders = [{"side": "buy", "amount": 1.0, "price": 80.0}]
        risk = RiskManager(
            {"max_position_usdt": 100.0, "max_loss_usdt": 100.0},
            client,
            self.logger,
        )

        self.assertFalse(risk.check_position_limit("buy", 1.0, 30.0))
        self.assertTrue(risk.check_position_limit("sell", 1.0, 90.0))

    def test_auto_compounding_cannot_exceed_position_cap(self):
        client = FakeClient()
        risk = RiskManager(
            {
                "max_position_usdt": 100.0,
                "max_loss_usdt": 100.0,
                "leverage": 5,
            },
            client,
            self.logger,
        )
        risk.initialize()

        quantity = risk.get_compounded_quantity(
            10.0, current_price=100.0, grid_levels_count=8
        )

        self.assertLessEqual(quantity, 0.4)

    def test_cycle_pnl_uses_actual_fill_prices_and_reanchors_next_order(self):
        client = FakeClient()
        risk = RiskManager(
            {"max_position_usdt": 500.0, "max_loss_usdt": 100.0},
            client,
            self.logger,
        )
        level = GridLevel(
            price=101.0,
            side=GridSide.SELL,
            quantity=2.0,
            status=GridOrderStatus.ACTIVE,
            order_id="filled-order",
            is_replacement=True,
            cycle_entry_price=100.0,
        )
        engine = GridEngine.__new__(GridEngine)
        engine.config = {"auto_compound": False}
        engine.symbol = "BTC/USDT"
        engine.quantity = 2.0
        engine.grid_spacing = 1.0
        engine.tick_size = 2
        engine.fee_rate = 0.0005
        engine.current_price = 100.0
        engine.completed_cycles = 0
        engine.is_running = True
        engine.risk_manager = risk
        engine.client = client
        engine.logger = self.logger
        engine.grid_levels = deque([level])
        engine._order_to_level = {"filled-order": level}
        engine._known_order_ids = {"filled-order"}
        engine._fill_lock = threading.Lock()
        engine._processed_fills = set()
        engine.MAX_PROCESSED_FILLS = 5000
        engine._processed_fills_history = deque(maxlen=5000)
        engine._recent_filled_levels = deque(maxlen=20)
        engine._save_state = lambda: None

        engine._handle_fill(
            level,
            fill_info={
                "average": 99.5,
                "filled": 2.0,
            },
        )

        expected_pnl = ((99.5 - 100.0) * 2.0) - ((100.0 + 99.5) * 2.0 * 0.0005)
        self.assertAlmostEqual(risk.get_realized_pnl(), expected_pnl)
        self.assertEqual(client.placed_orders[-1]["price"], 98.5)

    def test_ai_recommendation_respects_fees_and_configured_caps(self):
        class QuantClient:
            config = {
                "leverage": 3,
                "max_loss_usdt": 20.0,
                "max_position_usdt": 100.0,
                "exchange_fee_rate": 0.0005,
            }

            def get_balance(self):
                return 1_000.0

            def fetch_ohlcv(self, symbol, timeframe="1h", limit=50):
                return [
                    [1600000000 + i * 3600, 100.0, 101.0 + i % 3, 99.0 - i % 3, 100.0 + i % 2 * 0.2, 1000.0]
                    for i in range(50)
                ]

            def fetch_order_book(self, symbol, limit=20):
                return {"bids": [[100.0, 10.0]], "asks": [[100.1, 10.0]]}

            def fetch_funding_rate(self, symbol):
                return 0.0001

            def get_symbol_info_for(self, symbol):
                return {"min_qty": 0.001, "lot_size": 2, "tick_size": 4}

        recommendation = QuantEngine(QuantClient()).analyze_symbol("SOL/USDT")

        self.assertGreaterEqual(recommendation["grid_spacing_percent"], 0.2)
        self.assertLessEqual(recommendation["recommended_leverage"], 3)
        self.assertEqual(recommendation["max_loss_usdt"], 20.0)
        self.assertLessEqual(recommendation["max_position_usdt"], 100.0)
        self.assertLessEqual(
            recommendation["quantity"]
            * recommendation["price"]
            * (recommendation["grid_levels"] // 2),
            recommendation["max_position_usdt"] + 0.01,
        )

    def test_grid_spacing_floor_covers_configured_fee_buffer(self):
        client = FakeClient()
        config = {
            "symbol": "BTC/USDT",
            "grid_levels": 2,
            "spacing_mode": "percent",
            "grid_spacing_percent": 0.1,
            "quantity_per_grid": 1.0,
            "leverage": 5,
            "max_loss_usdt": 100.0,
            "max_position_usdt": 5_000.0,
            "exchange_fee_rate": 0.0005,
        }
        client.config = config
        risk = RiskManager(config, client, self.logger)
        risk.initialize()

        with tempfile.TemporaryDirectory(prefix="gridbot-grid-test-") as temp_dir:
            previous_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                engine = GridEngine(config, client, risk, self.logger)
                engine.initialize()
                self.assertEqual(engine.grid_spacing, 0.2)
            finally:
                os.chdir(previous_cwd)

    def test_balance_failures_do_not_return_fabricated_funds(self):
        client = BinanceClient({"symbol": "BTC/USDT"}, self.logger)

        class BalanceExchange:
            def fetch_balance(self):
                return {"USDT": {"free": 0.0, "total": 500.0}}

        client.exchange = BalanceExchange()
        self.assertEqual(client.get_balance(), 0.0)

        class FailedExchange:
            def fetch_balance(self):
                raise OSError("offline")

        client.exchange = FailedExchange()
        with self.assertRaises(RuntimeError):
            client.get_balance()

    def test_position_close_only_targets_bot_symbol(self):
        client = BinanceClient({"symbol": "SOL/USDT"}, self.logger)

        class PositionExchange:
            def __init__(self):
                self.orders = []

            def fetch_positions(self):
                return [
                    {"symbol": "SOL/USDT:USDT", "contracts": 2.0, "side": "long"},
                    {"symbol": "ETH/USDT:USDT", "contracts": 3.0, "side": "short"},
                ]

            def create_order(self, **kwargs):
                self.orders.append(kwargs)
                return {"id": str(len(self.orders))}

        client.exchange = PositionExchange()

        client.close_position()

        self.assertEqual(len(client.exchange.orders), 1)
        self.assertEqual(client.exchange.orders[0]["symbol"], "SOL/USDT:USDT")


if __name__ == "__main__":
    unittest.main()
