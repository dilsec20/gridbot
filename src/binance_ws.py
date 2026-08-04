"""
Binance Futures WebSocket Real-Time Client.
Provides ultra-low latency (<50ms) order fill updates and market price streaming.
"""

import time
import json
import asyncio
import threading
import websockets
from typing import Callable, Optional


class BinanceWSClient:
    """
    Manages WebSocket streams for Binance Futures:
    1. User Data Stream — Instant ORDER_TRADE_UPDATE notifications (<50ms)
    2. Market Ticker Stream — Real-time price updates (~100ms)
    """

    def __init__(self, config: dict, client, logger, perf_tracker=None):
        self.config = config
        self.client = client
        self.logger = logger
        self.perf_tracker = perf_tracker

        self.symbol = config.get("symbol", "BTC/USDT")
        self.formatted_symbol = self.symbol.replace("/", "").lower()

        use_demo = config.get("use_testnet", True) or config.get("use_demo", True)
        if use_demo:
            self.ws_base_url = "wss://stream.binancefuture.com/ws"
        else:
            self.ws_base_url = "wss://fstream.binance.com/ws"

        self.is_running = False
        self.listen_key: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Callbacks
        self.on_price_update: Optional[Callable[[float], None]] = None
        self.on_order_fill: Optional[Callable[[str], None]] = None

    def start(self, on_price_update=None, on_order_fill=None):
        """Start the WebSocket listener in a background daemon thread."""
        self.on_price_update = on_price_update
        self.on_order_fill = on_order_fill

        self.is_running = True
        self._thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._thread.start()
        self.logger.system("⚡ Ultra-Low Latency WebSocket Client initialized (<50ms real-time stream)")

    def stop(self):
        """Stop the WebSocket listener background thread."""
        self.is_running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.logger.system("WebSocket client stopped.")

    def _run_async_loop(self):
        """Run the asyncio event loop inside the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main_ws_task())
        except Exception as e:
            self.logger.warn(f"WebSocket loop stopped: {e}")

    async def _main_ws_task(self):
        """Run both Market Price Stream and User Data Stream concurrently."""
        tasks = [
            asyncio.create_task(self._market_ticker_stream()),
            asyncio.create_task(self._user_data_stream()),
            asyncio.create_task(self._keepalive_listen_key_loop()),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _market_ticker_stream(self):
        """Stream live mark/last price updates every ~100ms."""
        ticker_url = f"{self.ws_base_url}/{self.formatted_symbol}@ticker"

        while self.is_running:
            try:
                self.logger.system(f"Connecting to Market WebSocket: {ticker_url}")
                async with websockets.connect(ticker_url, ping_interval=20, ping_timeout=10) as ws:
                    self.logger.system(f"⚡ Connected to Binance Market Ticker Stream for {self.symbol}")
                    while self.is_running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        price_str = data.get("c") or data.get("p")
                        if price_str and self.on_price_update:
                            price = float(price_str)
                            self.on_price_update(price)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.is_running:
                    if self.perf_tracker:
                        self.perf_tracker.record_ws_reconnect()
                    self.logger.warn(f"Market WebSocket disconnected ({e}). Reconnecting in 2s...")
                    await asyncio.sleep(2)

    async def _user_data_stream(self):
        """Stream instant order fill notifications (<50ms) using Binance listenKey."""
        while self.is_running:
            try:
                # Get fresh listenKey from REST API
                self.listen_key = self.client.get_listen_key()
                if not self.listen_key:
                    self.logger.warn("Could not retrieve listenKey. Retrying in 5s...")
                    await asyncio.sleep(5)
                    continue

                user_ws_url = f"{self.ws_base_url}/{self.listen_key}"
                self.logger.system(f"Connecting to User Data WebSocket for real-time fills...")

                async with websockets.connect(user_ws_url, ping_interval=20, ping_timeout=10) as ws:
                    self.logger.system("⚡ Real-Time User Data Stream Active! Listening for instant fills...")

                    while self.is_running:
                        msg = await ws.recv()
                        payload = json.loads(msg)
                        event_type = payload.get("e")

                        if event_type == "ORDER_TRADE_UPDATE":
                            order_info = payload.get("o", {})
                            execution_type = order_info.get("x")  # TRADE, NEW, CANCELED, etc.
                            order_status = order_info.get("X")    # FILLED, PARTIALLY_FILLED, etc.
                            order_id = str(order_info.get("i"))

                            if order_status in ["FILLED", "PARTIALLY_FILLED"] and execution_type == "TRADE":
                                if self.on_order_fill:
                                    self.on_order_fill(order_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.is_running:
                    if self.perf_tracker:
                        self.perf_tracker.record_ws_reconnect()
                    self.logger.warn(f"User Data WebSocket connection reset ({e}). Reconnecting in 3s...")
                    await asyncio.sleep(3)

    async def _keepalive_listen_key_loop(self):
        """Ping Binance listenKey every 30 minutes to keep connection alive indefinitely."""
        while self.is_running:
            await asyncio.sleep(1800)  # 30 minutes
            if self.listen_key and self.is_running:
                try:
                    self.client.keep_alive_listen_key()
                    self.logger.system("Renewed Binance WebSocket listenKey keep-alive.")
                except Exception as e:
                    self.logger.warn(f"Failed to renew listenKey: {e}")
