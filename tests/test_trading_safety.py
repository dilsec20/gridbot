import os
import sys
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from binance_client import BinanceClient
from auto_portfolio_manager import get_smart_max_position
from grid_engine import GridEngine, GridLevel, GridOrderStatus, GridSide
from quant_engine import QuantEngine
from risk_manager import RiskManager
from trading_rules import effective_leverage, is_stablecoin_pair, trading_mode


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
        self.open_orders.append(order)
        return order

    def cancel_all_orders(self):
        return True


class FakeQuantClient:
    def __init__(self, config):
        self.config = config

    def get_balance(self):
        return 1_000.0

    def fetch_ohlcv(self, symbol, timeframe="1h", limit=50):
        return [
            [
                1600000000 + i * 3600,
                100.0,
                101.0 + i % 3,
                99.0 - i % 3,
                100.0 + i % 2 * 0.2,
                1000.0,
            ]
            for i in range(50)
        ]

    def fetch_order_book(self, symbol, limit=20):
        return {"bids": [[100.0, 10.0]], "asks": [[100.1, 10.0]]}

    def fetch_funding_rate(self, symbol):
        return 0.0001

    def get_symbol_info_for(self, symbol):
        return {"min_qty": 0.001, "lot_size": 2, "tick_size": 4, "min_notional": 5.0}


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

    def test_dynamic_position_cap_is_60_percent_of_wallet_notional(self):
        client = FakeClient()
        client.balance = 1_000.0
        risk = RiskManager(
            {
                "max_position_usdt": 0,
                "max_position_balance_percent": 60,
                "max_loss_usdt": 100,
            },
            client,
            self.logger,
        )

        self.assertTrue(risk.check_position_limit("buy", 6.0, 100.0))
        self.assertFalse(risk.check_position_limit("buy", 6.01, 100.0))

    def test_position_cap_uses_free_balance_not_wallet_balance(self):
        class MarginClient(FakeClient):
            def get_wallet_balance(self):
                return 5_000.0

        client = MarginClient()
        client.balance = 1_000.0
        risk = RiskManager(
            {
                "max_position_usdt": 0,
                "max_position_balance_percent": 60,
            },
            client,
            self.logger,
        )

        self.assertEqual(risk.get_max_position_limit(), 600.0)

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
        config = {
            "leverage": 3,
            "max_loss_usdt": 20.0,
            "max_position_usdt": 100.0,
            "exchange_fee_rate": 0.0005,
        }
        recommendation = QuantEngine(FakeQuantClient(config)).analyze_symbol("SOL/USDT")

        self.assertGreaterEqual(recommendation["grid_spacing_percent"], 0.2)
        self.assertLessEqual(recommendation["recommended_leverage"], 3)
        self.assertEqual(recommendation["max_loss_usdt"], 20.0)
        self.assertLessEqual(recommendation["max_position_usdt"], 100.0)
        worst_grid_price = recommendation["price"] * (
            1
            + (
                (recommendation["grid_levels"] + 1)
                // 2
                * recommendation["grid_spacing_percent"]
                / 100.0
            )
        )
        self.assertLessEqual(
            recommendation["quantity"]
            * worst_grid_price
            * (recommendation["grid_levels"] // 2),
            recommendation["max_position_usdt"] + 0.01,
        )

    def test_ai_sizing_uses_60_percent_notional_and_stable_pairs_get_10x(self):
        config = {
            "leverage": 5,
            "max_loss_usdt": 20.0,
            "max_position_usdt": 0,
            "exchange_fee_rate": 0.0005,
        }
        recommendation = QuantEngine(FakeQuantClient(config)).analyze_symbol(
            "USDC/USDT"
        )

        side_levels = (recommendation["grid_levels"] + 1) // 2
        worst_grid_price = recommendation["price"] * (
            1 + side_levels * recommendation["grid_spacing_percent"] / 100.0
        )
        side_notional = (
            recommendation["quantity"]
            * worst_grid_price
            * side_levels
        )
        self.assertEqual(recommendation["recommended_leverage"], 10)
        self.assertEqual(recommendation["max_position_usdt"], 600.0)
        self.assertLessEqual(side_notional, 600.0)
        self.assertGreater(side_notional, 550.0)
        self.assertEqual(recommendation["position_allocation_percent"], 60.0)

    def test_ai_does_not_emit_a_sized_fallback_without_market_data(self):
        class MissingMarketDataClient(FakeQuantClient):
            def fetch_ohlcv(self, symbol, timeframe="1h", limit=50):
                return []

        recommendation = QuantEngine(
            MissingMarketDataClient({"leverage": 5, "max_position_usdt": 0})
        ).analyze_symbol("SOL/USDT")

        self.assertIn("error", recommendation)
        self.assertEqual(recommendation["quantity"], 0.0)
        self.assertEqual(recommendation["max_position_usdt"], 0.0)

    def test_10x_rule_is_only_for_stablecoin_to_stablecoin_symbols(self):
        self.assertTrue(is_stablecoin_pair("USDC/USDT"))
        self.assertTrue(is_stablecoin_pair("USDT/USDC:USDC"))
        self.assertFalse(is_stablecoin_pair("SOL/USDT"))
        self.assertFalse(is_stablecoin_pair("BTC/USDT"))
        self.assertEqual(effective_leverage("USDC/USDT", 5), 10)
        self.assertEqual(effective_leverage("SOL/USDT", 5), 5)
        self.assertEqual(effective_leverage("SOL/USDT", 10), 5)
        self.assertEqual(get_smart_max_position(1_000.0), 600.0)
        self.assertEqual(
            BinanceClient({"symbol": "USDC/USDT", "leverage": 5}, self.logger).config[
                "leverage"
            ],
            10,
        )

    def test_trading_mode_prioritizes_demo_and_never_mislabels_safe_modes_as_live(self):
        self.assertEqual(
            trading_mode({"use_demo": False, "use_testnet": False}), "LIVE"
        )
        self.assertEqual(
            trading_mode({"use_demo": False, "use_testnet": True}), "TESTNET"
        )
        self.assertEqual(
            trading_mode({"use_demo": True, "use_testnet": False}), "DEMO"
        )
        self.assertEqual(
            trading_mode({"use_demo": True, "use_testnet": True}), "DEMO"
        )
        self.assertEqual(trading_mode({}), "TESTNET")

    def test_exchange_connection_enables_current_binance_demo_endpoints(self):
        class DemoExchange:
            def __init__(self):
                self.demo_enabled = False
                self.leverage_calls = []

            def enable_demo_trading(self, enabled):
                self.demo_enabled = enabled

            def load_time_difference(self):
                return None

            def fetch_time(self):
                return 1_700_000_000_000

            def set_leverage(self, leverage, symbol):
                self.leverage_calls.append((leverage, symbol))

            def set_margin_mode(self, mode, symbol):
                return None

        exchange = DemoExchange()
        client = BinanceClient(
            {
                "symbol": "ADA/USDT",
                "leverage": 5,
                "api_key": "test-key",
                "api_secret": "test-secret",
                "use_testnet": True,
                "use_demo": True,
            },
            self.logger,
        )

        with patch("binance_client.ccxt.binance", return_value=exchange):
            client.connect()

        self.assertTrue(exchange.demo_enabled)
        self.assertEqual(exchange.leverage_calls, [(5, "ADA/USDT")])

    def test_websocket_endpoint_matches_resolved_exchange_mode(self):
        from binance_ws import BinanceWSClient

        demo_ws = BinanceWSClient(
            {"symbol": "ADA/USDT", "use_demo": True, "use_testnet": True},
            None,
            self.logger,
        )
        testnet_ws = BinanceWSClient(
            {"symbol": "ADA/USDT", "use_demo": False, "use_testnet": True},
            None,
            self.logger,
        )

        self.assertEqual(demo_ws.ws_base_url, "wss://demo-fstream.binance.com/ws")
        self.assertEqual(testnet_ws.ws_base_url, "wss://stream.binancefuture.com/ws")

    def test_exchange_connection_applies_fixed_stablecoin_pair_leverage(self):
        class FakeExchange:
            def __init__(self):
                self.leverage_calls = []

            def load_time_difference(self):
                return None

            def fetch_time(self):
                return 1_700_000_000_000

            def set_leverage(self, leverage, symbol):
                self.leverage_calls.append((leverage, symbol))

            def set_margin_mode(self, mode, symbol):
                return None

        exchange = FakeExchange()
        config = {
            "symbol": "USDC/USDT",
            "leverage": 5,
            "api_key": "test-key",
            "api_secret": "test-secret",
            "use_testnet": False,
            "use_demo": False,
        }
        client = BinanceClient(config, self.logger)

        with patch("binance_client.ccxt.binance", return_value=exchange):
            client.connect()

        self.assertEqual(exchange.leverage_calls, [(10, "USDC/USDT")])

    def test_exchange_connection_aborts_if_leverage_setting_fails(self):
        class FailedLeverageExchange:
            def load_time_difference(self):
                return None

            def fetch_time(self):
                return 1_700_000_000_000

            def set_leverage(self, leverage, symbol):
                raise OSError("temporary exchange error")

        client = BinanceClient(
            {
                "symbol": "SOL/USDT",
                "leverage": 5,
                "api_key": "test-key",
                "api_secret": "test-secret",
                "use_testnet": False,
                "use_demo": False,
            },
            self.logger,
        )

        with patch(
            "binance_client.ccxt.binance",
            return_value=FailedLeverageExchange(),
        ):
            with self.assertRaisesRegex(RuntimeError, "startup/switch aborted"):
                client.connect()

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

    def test_grid_clamps_stale_quantity_to_full_side_notional_budget(self):
        client = FakeClient()
        client.balance = 1_000.0
        config = {
            "symbol": "BTC/USDT",
            "grid_levels": 10,
            "spacing_mode": "percent",
            "grid_spacing_percent": 0.5,
            "quantity_per_grid": 4_500.0,
            "leverage": 5,
            "max_loss_usdt": 100.0,
            "max_position_balance_percent": 60.0,
            "max_position_usdt": 0.0,
            "exchange_fee_rate": 0.0005,
        }
        risk = RiskManager(config, client, self.logger)
        risk.initialize()

        with tempfile.TemporaryDirectory(prefix="gridbot-grid-cap-") as temp_dir:
            previous_cwd = os.getcwd()
            try:
                os.chdir(temp_dir)
                engine = GridEngine(config, client, risk, self.logger)
                engine.initialize()
            finally:
                os.chdir(previous_cwd)

        self.assertLess(engine.quantity, 4_500.0)
        self.assertLessEqual(
            sum(o["amount"] * o["price"] for o in client.placed_orders if o["side"] == "sell"),
            600.0,
        )
        self.assertLessEqual(
            sum(o["amount"] * o["price"] for o in client.placed_orders if o["side"] == "buy"),
            600.0,
        )

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
