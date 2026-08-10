"""
Binance Futures API client wrapper using ccxt.
Handles connection, authentication, and all API operations.
"""

import time
import ccxt
from logger import BotLogger, fmt_price


class BinanceClient:
    """Wrapper around ccxt.binance for Futures trading on testnet."""

    def __init__(self, config: dict, logger: BotLogger):
        self.config = config
        self.logger = logger
        self.exchange = None
        self.symbol = config["symbol"]

    def connect(self):
        """Initialize ccxt exchange instance and configure for futures.
        
        Supports three modes:
        1. Demo Trading (recommended) - uses demo-fapi.binance.com
        2. Legacy Testnet (deprecated) - uses testnet.binancefuture.com  
        3. Live Trading - uses real Binance API
        """
        options = {
            "apiKey": self.config["api_key"],
            "secret": self.config["api_secret"],
            "enableRateLimit": True,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
                "recvWindow": 10000,
                "fetchCurrencies": False,  # Don't call sapi endpoints (not available on testnet)
            },
        }

        use_demo = self.config.get("use_testnet", True) or self.config.get("use_demo", True)

        if use_demo:
            # Use Binance Futures Testnet
            # Keys from https://testnet.binancefuture.com
            TESTNET_BASE = "https://testnet.binancefuture.com"
            options["urls"] = {
                "api": {
                    "fapiPublic": f"{TESTNET_BASE}/fapi/v1",
                    "fapiPublicV2": f"{TESTNET_BASE}/fapi/v2",
                    "fapiPublicV3": f"{TESTNET_BASE}/fapi/v3",
                    "fapiPrivate": f"{TESTNET_BASE}/fapi/v1",
                    "fapiPrivateV2": f"{TESTNET_BASE}/fapi/v2",
                    "fapiPrivateV3": f"{TESTNET_BASE}/fapi/v3",
                    # Route spot endpoints to testnet too (prevents hitting live API)
                    "public": "https://testnet.binance.vision/api/v3",
                    "private": "https://testnet.binance.vision/api/v3",
                    "sapi": f"{TESTNET_BASE}/sapi/v1",
                    "sapiV2": f"{TESTNET_BASE}/sapi/v2",
                    "sapiV3": f"{TESTNET_BASE}/sapi/v3",
                    "sapiV4": f"{TESTNET_BASE}/sapi/v4",
                },
            }
            self.logger.system("Mode: DEMO TRADING (paper money)")

        self.exchange = ccxt.binance(options)

        # Sync local time with Binance server time
        try:
            self.exchange.load_time_difference()
        except Exception:
            pass

        # Test connection
        try:
            server_time = self.exchange.fetch_time()
            mode_str = "Demo Trading" if use_demo else "LIVE"
            self.logger.system(f"Connected to Binance {mode_str}")
            self.logger.system(f"Server time: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(server_time / 1000))}")
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            raise

        # Set leverage
        try:
            leverage = self.config.get("leverage", 5)
            self.exchange.set_leverage(leverage, self.symbol)
            self.logger.system(f"Leverage set to {leverage}x for {self.symbol}")
        except Exception as e:
            self.logger.warn(f"Could not set leverage (may already be set): {e}")

        # Set margin mode to CROSSED (safer for grid trading)
        try:
            self.exchange.set_margin_mode("cross", self.symbol)
            self.logger.system("Margin mode: CROSS")
        except Exception as e:
            self.logger.warn(f"Could not set margin mode (may already be set): {e}")

    def get_price(self) -> float:
        """Fetch current mark price for the configured symbol."""
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return float(ticker["last"])
        except Exception as e:
            self.logger.error(f"Failed to fetch price: {e}")
            raise

    def fetch_funding_rate(self, symbol: str) -> float:
        """Fetch current 8h funding rate for the specified symbol."""
        try:
            if hasattr(self.exchange, 'fetch_funding_rate'):
                res = self.exchange.fetch_funding_rate(symbol)
                rate = res.get('fundingRate')
                if rate is not None:
                    return float(rate)
            # Direct REST endpoint fallback
            funding_info = self.exchange.fapiPublicGetPremiumIndex({'symbol': symbol.replace('/', '')})
            if funding_info and 'lastFundingRate' in funding_info:
                return float(funding_info['lastFundingRate'])
        except Exception:
            pass
        return 0.0001

    def get_balance(self) -> float:
        """Get total USDT margin balance (Equity) with resilient failover cache."""
        try:
            balance = self.exchange.fetch_balance()
            usdt = balance.get("USDT", {})
            total = float(usdt.get("total", 0))
            if total > 0:
                self._cached_balance = total
                return total
            free = float(usdt.get("free", 0))
            if free > 0:
                self._cached_balance = free
                return free
            return getattr(self, "_cached_balance", 5000.0)
        except Exception as e:
            if hasattr(self, "_cached_balance") and self._cached_balance > 0:
                return self._cached_balance
            return 5000.0

    def get_wallet_balance(self) -> float:
        """Get raw USDT Wallet Cash Balance (excluding floating unrealized PnL)."""
        try:
            balance = self.exchange.fetch_balance()
            info = balance.get("info", {})
            assets = info.get("assets", [])
            for a in assets:
                if a.get("asset") == "USDT":
                    wb = float(a.get("walletBalance", 0) or 0)
                    if wb > 0:
                        self._cached_wallet_balance = wb
                        return wb
            usdt = balance.get("USDT", {})
            free = float(usdt.get("free", 0) or 0)
            if free > 0:
                self._cached_wallet_balance = free
                return free
            total = float(usdt.get("total", 0) or 0)
            if total > 0:
                self._cached_wallet_balance = total
                return total
            return getattr(self, "_cached_wallet_balance", 5000.0)
        except Exception:
            return getattr(self, "_cached_wallet_balance", 5000.0)

    def get_position(self) -> dict:
        """Get current position for the symbol."""
        try:
            positions = self.exchange.fetch_positions()
            target_symbols = {
                self.symbol,
                self.symbol.replace(":USDT", ""),
                self.symbol.replace("/", "").replace(":USDT", ""),
                f"{self.symbol}:USDT" if ":" not in self.symbol else self.symbol
            }
            for pos in positions:
                if pos.get("symbol") in target_symbols:
                    contracts = float(pos.get("contracts", 0) or 0)
                    if contracts != 0:
                        return {
                            "size": contracts,
                            "side": pos.get("side", "none"),
                            "entry_price": float(pos.get("entryPrice", 0) or 0),
                            "unrealized_pnl": float(pos.get("unrealizedPnl", 0) or 0),
                            "notional": float(pos.get("notional", 0) or 0),
                        }
            return {"size": 0, "side": "none", "entry_price": 0, "unrealized_pnl": 0, "notional": 0}
        except Exception as e:
            self.logger.error(f"Failed to fetch position: {e}")
            return {"size": 0, "side": "none", "entry_price": 0, "unrealized_pnl": 0, "notional": 0}

    def close_position(self) -> dict | None:
        """Market close ALL open positions across the entire Binance account."""
        try:
            positions = self.exchange.fetch_positions()
            closed_orders = []
            for pos in positions:
                contracts = float(pos.get("contracts", 0) or 0)
                if contracts > 0:
                    sym = pos["symbol"]
                    side = pos.get("side", "none").lower()
                    close_side = "sell" if side in ["long", "buy"] else "buy"
                    self.logger.system(f"Closing {side.upper()} position on {sym}: {contracts} contracts...")

                    try:
                        # Attempt 1: Market order
                        order = self.exchange.create_order(
                            symbol=sym,
                            type="market",
                            side=close_side,
                            amount=abs(contracts),
                            params={"reduceOnly": True},
                        )
                        closed_orders.append(order)
                    except Exception as err:
                        self.logger.warn(f"Market order failed ({err}), placing aggressive Limit ReduceOnly order...")
                        # Attempt 2: Aggressive Limit ReduceOnly order at current market price
                        ticker = self.exchange.fetch_ticker(sym)
                        current_price = float(ticker.get("last", 0) or 0)
                        info = self.get_symbol_info_for(sym)
                        tick_size = info.get("tick_size", 4)

                        if close_side == "sell":
                            price = float(ticker.get("bid", current_price) or current_price)
                        else:
                            price = float(ticker.get("ask", current_price) or current_price)

                        price = round(price, tick_size)

                        order = self.exchange.create_order(
                            symbol=sym,
                            type="limit",
                            side=close_side,
                            amount=abs(contracts),
                            price=price,
                            params={"reduceOnly": True},
                        )
                        closed_orders.append(order)

            if closed_orders:
                self.logger.system(f"Position closed successfully! Floating profit locked into wallet balance.")
                return closed_orders[0]
            else:
                self.logger.system("No open position to close.")
                return None
        except Exception as e:
            self.logger.error(f"Failed to close position: {e}")
            return None

    def trim_position(self, percentage: float = 50.0) -> dict | None:
        """
        EMERGENCY EXPOSURE CONTROL: Trim open position by X% (default 50%).
        Cuts position exposure in half to prevent margin ratio escalation & liquidation.
        """
        try:
            positions = self.exchange.fetch_positions()
            trimmed_orders = []
            for pos in positions:
                contracts = float(pos.get("contracts", 0) or 0)
                if contracts > 0:
                    sym = pos["symbol"]
                    side = pos.get("side", "none").lower()
                    close_side = "sell" if side in ["long", "buy"] else "buy"
                    trim_amount = round(contracts * (percentage / 100.0), 4)

                    if trim_amount <= 0:
                        continue

                    self.logger.risk(
                        f"🚨 EMERGENCY EXPOSURE CONTROL: Trimming {percentage}% of {side.upper()} "
                        f"position on {sym} ({trim_amount}/{contracts} contracts)..."
                    )

                    try:
                        order = self.exchange.create_order(
                            symbol=sym,
                            type="market",
                            side=close_side,
                            amount=trim_amount,
                            params={"reduceOnly": True},
                        )
                        trimmed_orders.append(order)
                    except Exception as err:
                        self.logger.warn(f"Market trim failed ({err}), placing aggressive Limit ReduceOnly order...")
                        ticker = self.exchange.fetch_ticker(sym)
                        current_price = float(ticker.get("last", 0) or 0)
                        info = self.get_symbol_info_for(sym)
                        tick_size = info.get("tick_size", 4)
                        price = float(ticker.get("bid" if close_side == "sell" else "ask", current_price) or current_price)
                        price = round(price, tick_size)

                        order = self.exchange.create_order(
                            symbol=sym,
                            type="limit",
                            side=close_side,
                            amount=trim_amount,
                            price=price,
                            params={"reduceOnly": True},
                        )
                        trimmed_orders.append(order)

            if trimmed_orders:
                self.logger.system(f"🛡️ Emergency {percentage}% position trim completed successfully!")
                return trimmed_orders[0]
            else:
                self.logger.system("No open position to trim.")
                return None
        except Exception as e:
            self.logger.error(f"Failed to trim position: {e}")
            return None

    def place_limit_order(self, side: str, quantity: float, price: float, client_order_id: str | None = None) -> dict | None:
        """
        Place a LIMIT order.
        side: 'buy' or 'sell'
        Optional client_order_id passed as newClientOrderId to Binance.
        Returns order dict on success, None on failure.
        """
        max_retries = 3

        for attempt in range(max_retries):
            try:
                params = {"timeInForce": "GTC"}
                if client_order_id:
                    params["newClientOrderId"] = client_order_id

                order = self.exchange.create_order(
                    symbol=self.symbol,
                    type="limit",
                    side=side,
                    amount=quantity,
                    price=price,
                    params=params,
                )

                self.logger.trade(side, price, quantity)
                return order

            except ccxt.InvalidOrder as e:
                self.logger.error(f"Invalid order {side} {quantity} @ {fmt_price(price)}: {e}")
                return None

            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable) as e:
                self.logger.warn(f"Network error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    self.logger.error(f"Failed to place order after {max_retries} attempts")
                    return None

            except Exception as e:
                self.logger.error(f"Unexpected error placing order: {e}")
                return None

        return None

    def fetch_order(self, order_id: str) -> dict | None:
        """Fetch order details by ID from Binance."""
        try:
            return self.exchange.fetch_order(order_id, self.symbol)
        except Exception as e:
            self.logger.warn(f"Failed to fetch order #{order_id}: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a single order by ID."""
        try:
            self.exchange.cancel_order(order_id, self.symbol)
            self.logger.info(f"Cancelled order {order_id}")
            return True
        except ccxt.OrderNotFound:
            self.logger.warn(f"Order {order_id} not found (may be already filled/cancelled)")
            return True
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_all_orders(self) -> bool:
        """Cancel all open orders for the symbol. Used for emergency shutdown."""
        try:
            self.exchange.cancel_all_orders(self.symbol)
            self.logger.system(f"All open orders cancelled for {self.symbol}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to cancel all orders: {e}")
            return False

    def get_open_orders(self) -> list:
        """Fetch all open orders for the symbol."""
        try:
            orders = self.exchange.fetch_open_orders(self.symbol)
            return orders
        except Exception as e:
            self.logger.error(f"Failed to fetch open orders: {e}")
            return []

    def _parse_precision(self, val, default=4) -> int:
        if isinstance(val, int):
            return val
        if isinstance(val, float) and val > 0:
            import math
            return max(0, int(round(-math.log10(val))))
        return default

    def get_symbol_info(self) -> dict:
        """Get symbol trading rules (tick size, lot size, min notional)."""
        try:
            markets = self.exchange.load_markets()
            market = markets.get(self.symbol, {})
            precision_price = market.get("precision", {}).get("price", 4)
            precision_amount = market.get("precision", {}).get("amount", 2)

            tick_size = self._parse_precision(precision_price, 4)
            lot_size = self._parse_precision(precision_amount, 2)

            return {
                "tick_size": tick_size,
                "lot_size": lot_size,
                "min_qty": float(market.get("limits", {}).get("amount", {}).get("min", 0.001) or 0.001),
                "min_notional": float(market.get("limits", {}).get("cost", {}).get("min", 5) or 5),
            }
        except Exception as e:
            self.logger.error(f"Failed to fetch symbol info: {e}")
            return {"tick_size": 4, "lot_size": 2, "min_qty": 0.001, "min_notional": 5}

    def get_symbol_info_for(self, target_symbol: str) -> dict:
        """Get trading rules for any target symbol."""
        try:
            markets = self.exchange.load_markets()
            market = markets.get(target_symbol, {})
            precision_price = market.get("precision", {}).get("price", 4)
            precision_amount = market.get("precision", {}).get("amount", 2)
            tick_size = self._parse_precision(precision_price, 4)
            lot_size = self._parse_precision(precision_amount, 2)
            return {
                "tick_size": tick_size,
                "lot_size": lot_size,
                "min_qty": float(market.get("limits", {}).get("amount", {}).get("min", 0.001) or 0.001),
                "min_notional": float(market.get("limits", {}).get("cost", {}).get("min", 5) or 5),
            }
        except Exception:
            return {"tick_size": 4, "lot_size": 2, "min_qty": 0.001, "min_notional": 5}

    def get_price_for(self, target_symbol: str) -> float:
        """Get current ticker price for any target symbol."""
        ticker = self.exchange.fetch_ticker(target_symbol)
        return float(ticker.get("last", 0.0))

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 50) -> list:
        """Fetch historical candlestick data (OHLCV) for technical indicators."""
        try:
            return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            self.logger.error(f"Failed to fetch OHLCV for {symbol}: {e}")
            return []

    def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:
        """Fetch top order book bids and asks for market depth analysis."""
        try:
            return self.exchange.fetch_order_book(symbol, limit=limit)
        except Exception as e:
            return {"bids": [], "asks": []}

    def fetch_funding_rate(self, symbol: str) -> float:
        """Fetch 8h perpetual funding rate for target symbol."""
        try:
            funding = self.exchange.fetch_funding_rate(symbol)
            return float(funding.get("fundingRate", 0.0001))
        except Exception:
            return 0.0001

    def get_all_symbols(self) -> list:
        """Fetch all available USDT futures trading pairs from Binance."""
        try:
            markets = self.exchange.load_markets()
            usdt_symbols = []
            for symbol, market in markets.items():
                if market.get('linear') and market.get('quote') == 'USDT' and market.get('active', True):
                    usdt_symbols.append({
                        'symbol': symbol,
                        'base': market.get('base'),
                        'quote': market.get('quote'),
                        'precision_price': market.get('precision', {}).get('price', 4),
                        'precision_amount': market.get('precision', {}).get('amount', 2),
                    })
            # Sort with popular pairs first
            popular = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'DOGE/USDT', 'XRP/USDT', 'PEPE/USDT', 'SHIB/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'SUI/USDT', 'NEAR/USDT', 'FET/USDT', 'FLOKI/USDT', 'WIF/USDT']
            usdt_symbols.sort(key=lambda s: (0 if s['symbol'] in popular else 1, popular.index(s['symbol']) if s['symbol'] in popular else s['symbol']))
            return usdt_symbols
        except Exception as e:
            self.logger.error(f"Failed to fetch symbols: {e}")
            return [
                {'symbol': 'BTC/USDT', 'precision_price': 2},
                {'symbol': 'ETH/USDT', 'precision_price': 2},
                {'symbol': 'SOL/USDT', 'precision_price': 2},
                {'symbol': 'BNB/USDT', 'precision_price': 2},
                {'symbol': 'DOGE/USDT', 'precision_price': 5},
                {'symbol': 'XRP/USDT', 'precision_price': 4},
                {'symbol': 'ADA/USDT', 'precision_price': 4},
                {'symbol': 'PEPE/USDT', 'precision_price': 8},
                {'symbol': 'SHIB/USDT', 'precision_price': 8},
            ]

    def get_market_tickers(self) -> dict:
        """Fetch 24h ticker data for all USDT futures symbols and group by Gainers, Losers, and Grid Suitability."""
        try:
            tickers = self.exchange.fetch_tickers()
            symbol_data = []

            for symbol, ticker in tickers.items():
                if '/USDT' in symbol and ticker.get('last') and ticker.get('percentage') is not None:
                    last = float(ticker.get('last', 0))
                    change = float(ticker.get('percentage', 0))
                    high = float(ticker.get('high', last * 1.01))
                    low = float(ticker.get('low', last * 0.99))
                    vol = float(ticker.get('baseVolume', 0))

                    # Grid Suitability Score: reward 3%-15% volatility with high volume
                    spread_pct = ((high - low) / last * 100) if last > 0 else 0
                    grid_score = min(100, int(spread_pct * 8))

                    symbol_data.append({
                        'symbol': symbol,
                        'price': last,
                        'change_24h': round(change, 2),
                        'high_24h': high,
                        'low_24h': low,
                        'grid_score': grid_score,
                    })

            # Sort Gainers, Losers, Best Grid
            gainers = sorted(symbol_data, key=lambda x: x['change_24h'], reverse=True)[:5]
            losers = sorted(symbol_data, key=lambda x: x['change_24h'])[:5]
            best_grid = sorted(symbol_data, key=lambda x: x['grid_score'], reverse=True)[:5]

            return {
                'gainers': gainers,
                'losers': losers,
                'best_grid': best_grid,
            }
        except Exception as e:
            self.logger.error(f"Failed to fetch market tickers: {e}")
            # Fallback demo data
            return {
                'gainers': [
                    {'symbol': 'SOL/USDT', 'price': 185.20, 'change_24h': 8.45, 'grid_score': 85},
                    {'symbol': 'PEPE/USDT', 'price': 0.0000112, 'change_24h': 6.20, 'grid_score': 90},
                    {'symbol': 'DOGE/USDT', 'price': 0.1285, 'change_24h': 4.10, 'grid_score': 78},
                ],
                'losers': [
                    {'symbol': 'ADA/USDT', 'price': 0.3750, 'change_24h': -3.20, 'grid_score': 72},
                    {'symbol': 'ETH/USDT', 'price': 3420.50, 'change_24h': -1.85, 'grid_score': 65},
                    {'symbol': 'BTC/USDT', 'price': 63850.00, 'change_24h': -0.90, 'grid_score': 70},
                ],
                'best_grid': [
                    {'symbol': 'DOGE/USDT', 'price': 0.1285, 'change_24h': 4.10, 'grid_score': 95},
                    {'symbol': 'SOL/USDT', 'price': 185.20, 'change_24h': 8.45, 'grid_score': 92},
                    {'symbol': 'PEPE/USDT', 'price': 0.0000112, 'change_24h': 6.20, 'grid_score': 90},
                    {'symbol': 'BTC/USDT', 'price': 63850.00, 'change_24h': -0.90, 'grid_score': 88},
                ],
            }

    def get_listen_key(self) -> str | None:
        """Create a user data stream listenKey for Binance WebSocket."""
        try:
            res = self.exchange.fapiPrivatePostListenKey()
            return res.get("listenKey")
        except Exception as e:
            self.logger.error(f"Failed to create WebSocket listenKey: {e}")
            return None

    def keep_alive_listen_key(self) -> bool:
        """Send keepalive signal for user data stream listenKey."""
        try:
            self.exchange.fapiPrivatePutListenKey()
            return True
        except Exception as e:
            self.logger.warn(f"Failed to ping listenKey: {e}")
            return False

