
"""
Grid Trading Bot — Main Entry Point

Binance Futures Grid Trading Bot (Testnet)
Automatically places buy/sell limit orders at fixed price intervals
to profit from sideways market oscillations.

Usage:
    python src/main.py
    python src/main.py --config path/to/config.json

Press Ctrl+C to gracefully shutdown (cancels all orders).
"""

import os
import sys
import json
import time
import signal
import asyncio
import argparse
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logger import BotLogger
from binance_client import BinanceClient
from risk_manager import RiskManager
from grid_engine import GridEngine
from binance_ws import BinanceWSClient


class GridTradingBot:
    """Main bot controller — orchestrates all components."""

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.logger = BotLogger(self.config.get("log_file", "trades.log"))
        self.client = BinanceClient(self.config, self.logger)
        self.risk_manager = RiskManager(self.config, self.client, self.logger)
        self.grid_engine = GridEngine(
            self.config, self.client, self.risk_manager, self.logger
        )
        self.is_running = False
        self._shutdown_requested = False

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        path = Path(config_path)
        if not path.exists():
            print(f"\n  ❌ Config file not found: {config_path}")
            print(f"  💡 Copy config.json.example to config.json and fill in your API keys:")
            print(f"     cp config.json.example config.json")
            print()
            sys.exit(1)

        with open(path, "r") as f:
            config = json.load(f)

        # Validate required fields
        required = ["api_key", "api_secret", "symbol"]
        for field in required:
            if field not in config or config[field].startswith("YOUR_"):
                print(f"\n  ❌ Missing or placeholder value for '{field}' in config.json")
                print(f"  💡 Get your testnet API keys from: https://testnet.binancefuture.com")
                print()
                sys.exit(1)

        return config

    def _setup_signal_handlers(self):
        """Register Ctrl+C handler for graceful shutdown."""
        def signal_handler(signum, frame):
            if self._shutdown_requested:
                print("\n  ⚠️  Force quit!")
                sys.exit(1)

            self._shutdown_requested = True
            print()
            self.logger.system("Shutdown requested (Ctrl+C)... cancelling orders...")
            self.shutdown()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def start(self):
        """Start the grid trading bot."""
        self._setup_signal_handlers()
        self.logger.banner()

        # --- Step 1: Connect to Binance ---
        self.logger.system("Connecting to Binance Futures...")
        try:
            self.client.connect()
        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            sys.exit(1)

        # --- Step 2: Display account info ---
        balance = self.client.get_balance()
        self.logger.system(f"Account balance: ${balance:,.2f} USDT")

        if balance < 10:
            self.logger.error("Balance too low! Need at least $10 USDT on testnet.")
            self.logger.info("Deposit testnet funds at: https://testnet.binancefuture.com")
            sys.exit(1)

        # --- Step 3: Initialize risk manager ---
        self.risk_manager.initialize()

        # --- Step 4: Initialize and start grid ---
        self.logger.system("Setting up grid...")
        try:
            self.grid_engine.initialize()
        except Exception as e:
            self.logger.error(f"Failed to initialize grid: {e}")
            self.shutdown()
            sys.exit(1)

        # Print initial grid state
        self.grid_engine.print_grid()
        print()

        # --- Step 5: Start Real-Time WebSocket Client ---
        self.ws_client = BinanceWSClient(self.config, self.client, self.logger)
        self.ws_client.start(
            on_price_update=lambda price: self.grid_engine.update_price(price),
            on_order_fill=lambda order_id: self.grid_engine.process_order_fill_id(order_id),
        )

        # --- Step 6: Main event loop ---
        self.is_running = True
        self.logger.system("Bot is running! Real-time WebSockets active (<50ms delay). Press Ctrl+C to stop.")
        print()

        self._run_loop()

    def _run_loop(self):
        """Main event loop — poll for fills, update price, check risk."""
        poll_interval = 5        # Check fills every 5 seconds (failsafe backup)
        dashboard_interval = 5   # Refresh dashboard every 5 seconds
        risk_interval = 15       # Risk check every 15 seconds

        last_poll = time.time()
        last_dashboard = time.time()
        last_risk = time.time()

        while self.is_running and not self._shutdown_requested:
            try:
                now = time.time()

                # --- Failsafe Poll for order fills ---
                if now - last_poll >= poll_interval:
                    self.grid_engine.check_and_process_fills()
                    self.grid_engine._check_auto_trailing_recenter()
                    last_poll = now

                # --- Risk check ---
                if now - last_risk >= risk_interval:
                    if not self.risk_manager.perform_safety_check():
                        self.logger.risk("⛔ RISK LIMIT BREACHED — EMERGENCY SHUTDOWN")
                        self.shutdown()
                        return
                    last_risk = now

                # --- Dashboard ---
                if now - last_dashboard >= dashboard_interval:
                    stats = self.grid_engine.get_stats()
                    self.logger.dashboard(
                        symbol=self.config["symbol"],
                        price=stats["price"],
                        pnl=stats["pnl"],
                        cycles=stats["cycles"],
                        open_buys=stats["open_buys"],
                        open_sells=stats["open_sells"],
                        grid_low=stats["grid_low"],
                        grid_high=stats["grid_high"],
                    )
                    last_dashboard = now

                # Sleep briefly to avoid busy-waiting
                time.sleep(1)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                time.sleep(5)  # Wait before retrying

    def shutdown(self):
        """Graceful shutdown — cancel all orders and print summary."""
        self.is_running = False

        # Stop WebSocket client
        if hasattr(self, "ws_client") and self.ws_client:
            self.ws_client.stop()

        # Cancel all open orders
        self.grid_engine.cancel_all()

        # Print final summary
        stats = self.grid_engine.get_stats()
        self.logger.shutdown_summary(
            total_pnl=stats["pnl"],
            total_cycles=stats["cycles"],
        )


def main():
    """Parse arguments and start the bot."""
    parser = argparse.ArgumentParser(
        description="Grid Trading Bot for Binance Futures (Testnet)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py                          # Use default config.json
  python src/main.py --config my_config.json  # Use custom config

Setup:
  1. Copy config.json.example to config.json
  2. Get testnet API keys from https://testnet.binancefuture.com
  3. Fill in your API key and secret in config.json
  4. Run the bot!
        """,
    )

    parser.add_argument(
        "--config", "-c",
        default="config.json",
        help="Path to config file (default: config.json)",
    )

    args = parser.parse_args()

    # Resolve config path relative to project root
    config_path = args.config
    if not os.path.isabs(config_path):
        # Try relative to project root (parent of src/)
        project_root = Path(__file__).parent.parent
        config_path = str(project_root / config_path)

    bot = GridTradingBot(config_path)
    bot.start()


if __name__ == "__main__":
    main()
