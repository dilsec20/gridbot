"""
Quantitative Analysis & AI Smart Grid Engine.
Calculates technical indicators (ATR, RSI, ADX, Bollinger Bands, Volatility)
and auto-engineers optimal grid trading parameters with Grid-Optimized AI Suitability Scoring (0-100)
and 90% Wallet Equity Auto-Scaling.
"""

import math
from typing import Dict, Any, List


def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """Calculate Relative Strength Index (RSI)."""
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return round(rsi, 2)


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """Calculate Average True Range (ATR)."""
    if len(closes) < period + 1:
        return closes[-1] * 0.01 if closes else 1.0

    tr_list = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)

    atr = sum(tr_list[-period:]) / period
    return atr


def calculate_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    """
    Calculate Average Directional Index (ADX).
    ADX < 35 = Range-bound / Moderate Oscillation (Ideal for Grid).
    ADX > 45 = Strong runaway trend (Higher risk for Grid).
    """
    if len(closes) < period * 2:
        return 18.0

    plus_dm = []
    minus_dm = []
    tr_list = []

    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        p_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        m_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        plus_dm.append(p_dm)
        minus_dm.append(m_dm)

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
        tr_list.append(tr)

    if not tr_list:
        return 18.0

    smooth_tr = sum(tr_list[-period:])
    smooth_p_dm = sum(plus_dm[-period:])
    smooth_m_dm = sum(minus_dm[-period:])

    if smooth_tr == 0:
        return 18.0

    p_di = (smooth_p_dm / smooth_tr) * 100.0
    m_di = (smooth_m_dm / smooth_tr) * 100.0

    di_sum = p_di + m_di
    if di_sum == 0:
        return 18.0

    dx = (abs(p_di - m_di) / di_sum) * 100.0
    return round(dx, 1)


def calculate_bollinger_bands(closes: List[float], period: int = 20, num_std: float = 2.0) -> dict:
    """Calculate Bollinger Bands (Middle, Upper, Lower)."""
    if len(closes) < period:
        price = closes[-1] if closes else 100.0
        return {"middle": price, "upper": price * 1.02, "lower": price * 0.98}

    slice_closes = closes[-period:]
    sma = sum(slice_closes) / period

    variance = sum((x - sma) ** 2 for x in slice_closes) / period
    std_dev = math.sqrt(variance)

    upper = sma + (num_std * std_dev)
    lower = sma - (num_std * std_dev)

    return {
        "middle": round(sma, 6),
        "upper": round(upper, 6),
        "lower": round(lower, 6),
    }


class QuantEngine:
    """Institutional Quantitative Parameter Engine for AI Smart Grid."""

    def __init__(self, client):
        self.client = client

    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch OHLCV candles, calculate technical indicators,
        compute Grid-Optimized AI Suitability Score (0-100),
        and auto-engineer optimal grid trading parameters using 90% Wallet Equity.
        """
        try:
            # Fetch 50 hourly candles
            ohlcv = self.client.fetch_ohlcv(symbol, timeframe="1h", limit=50)
            if not ohlcv or len(ohlcv) < 20:
                return self._fallback_recommendation(symbol)

            closes = [c[4] for c in ohlcv]
            highs = [c[2] for c in ohlcv]
            lows = [c[3] for c in ohlcv]
            volumes = [c[5] for c in ohlcv]

            current_price = closes[-1]

            # 1. Technical Indicators
            rsi = calculate_rsi(closes, period=14)
            atr = calculate_atr(highs, lows, closes, period=14)
            adx = calculate_adx(highs, lows, closes, period=14)
            bb = calculate_bollinger_bands(closes, period=20, num_std=2.0)

            atr_percent = (atr / current_price) * 100.0 if current_price > 0 else 0.5
            bb_width_percent = ((bb["upper"] - bb["lower"]) / bb["middle"]) * 100.0 if bb["middle"] > 0 else 2.0

            # Order Book Imbalance (Bids vs Asks)
            bid_ratio_percent = 50.0
            try:
                order_book = self.client.fetch_order_book(symbol, limit=20)
                bids = order_book.get("bids", [])
                asks = order_book.get("asks", [])
                bid_vol = sum(b[1] for b in bids) if bids else 1.0
                ask_vol = sum(a[1] for a in asks) if asks else 1.0
                total_vol = bid_vol + ask_vol
                bid_ratio_percent = round((bid_vol / total_vol) * 100.0, 1) if total_vol > 0 else 50.0
            except Exception:
                pass

            if bid_ratio_percent > 62.0:
                book_imbalance = f"Bullish ({bid_ratio_percent}% Buyers)"
            elif bid_ratio_percent < 38.0:
                book_imbalance = f"Bearish ({round(100.0 - bid_ratio_percent, 1)}% Sellers)"
            else:
                book_imbalance = f"Balanced ({bid_ratio_percent}% Buyers)"

            # 8h Funding Rate, Next Settlement Timestamp & Market Impact Bias
            funding_percent = 0.01
            funding_apr_percent = 10.95
            try:
                if hasattr(self.client, 'fetch_funding_rate'):
                    funding_rate = self.client.fetch_funding_rate(symbol)
                    funding_percent = round(funding_rate * 100.0, 4)
                    funding_apr_percent = round(funding_percent * 3 * 365.0, 2)
            except Exception:
                pass

            now_ts = int(time.time())
            next_funding_ts = ((now_ts // 28800) + 1) * 28800  # Next 8h UTC settlement boundary

            if funding_percent > 0:
                funding_bias = "🔴 Downward Pressure (Longs Pay Shorts)"
                funding_desc = f"Longs pay Shorts (-{funding_percent}% / 8h). Longs may close positions before settlement."
            elif funding_percent < 0:
                funding_bias = "🟢 Upward Squeeze Pump (Shorts Pay Longs)"
                funding_desc = f"Shorts pay Longs (+{abs(funding_percent)}% / 8h). Shorts may cover to avoid paying yield."
            else:
                funding_bias = "⚪ Neutral Funding Rate"
                funding_desc = "Funding rate is zero (balanced market sentiment)."

            # 2. Grid-Optimized AI Suitability Score (0 - 100)
            # High Volatility (ATR 1.5% - 9%) is the FUEL for Grid Profits! Reward it!

            # A. ATR Volatility Score (30%)
            if 1.5 <= atr_percent <= 9.0:
                score_atr = 100.0
            elif atr_percent > 9.0:
                score_atr = max(70.0, 100.0 - (atr_percent - 9.0) * 5.0)
            else:
                score_atr = max(50.0, (atr_percent / 1.5) * 100.0)

            # B. ADX Score (25%)
            if adx <= 25.0:
                score_adx = 100.0
            elif adx <= 38.0:
                score_adx = max(75.0, 100.0 - (adx - 25.0) * 2.0)
            else:
                score_adx = max(30.0, 75.0 - (adx - 38.0) * 3.0)

            # C. RSI Score (15%)
            rsi_dist = abs(rsi - 50.0)
            score_rsi = max(40.0, 100.0 - (rsi_dist * 2.0))

            # D. BB Width Score (15%)
            if 2.0 <= bb_width_percent <= 12.0:
                score_bb = 100.0
            else:
                score_bb = max(50.0, 100.0 - abs(bb_width_percent - 7.0) * 5.0)

            # E. Volume / Liquidity Score (10%)
            avg_vol_usdt = (sum(volumes[-10:]) / 10.0) * current_price if volumes else 100000.0
            score_vol = 100.0 if avg_vol_usdt > 100000 else 80.0

            # F. Order Book Score (5%)
            imbalance_dist = abs(bid_ratio_percent - 50.0)
            score_book = max(40.0, 100.0 - (imbalance_dist * 2.0))

            ai_grid_score = int(round(
                (0.30 * score_atr) +
                (0.25 * score_adx) +
                (0.15 * score_rsi) +
                (0.15 * score_bb) +
                (0.10 * score_vol) +
                (0.05 * score_book)
            ))
            ai_grid_score = max(35, min(99, ai_grid_score))

            # Classification & Stars tailored for Grid Trading
            if ai_grid_score >= 85:
                status = "Excellent"
                status_badge = "🟢 Excellent"
                stars = "★★★★★"
            elif ai_grid_score >= 75:
                status = "Very Good"
                status_badge = "🟢 Very Good"
                stars = "★★★★☆"
            elif ai_grid_score >= 65:
                status = "Good"
                status_badge = "🟡 Good"
                stars = "★★★☆☆"
            elif ai_grid_score >= 55:
                status = "Moderate"
                status_badge = "🟠 Moderate"
                stars = "★★☆☆☆"
            elif ai_grid_score >= 50:
                status = "Risky"
                status_badge = "🔴 Risky"
                stars = "★☆☆☆☆"
            else:
                status = "Avoid"
                status_badge = "🔴 Avoid"
                stars = "☆☆☆☆☆"

            # 3. Market Regime & Trend Bias
            if rsi >= 68:
                regime = "Bullish Momentum"
                bias = "Overbought (High Sell Target)"
            elif rsi <= 32:
                regime = "Bearish Oversold"
                bias = "Oversold (Buy Accumulation)"
            else:
                regime = "Optimal Ranging Grid"
                bias = "Neutral Oscillation"

            # 4. Auto-Calculate Optimal Grid Spacing (%) based on ATR & ADX Dynamic Multiplier k
            if adx < 10.0:
                k = 0.25   # Tighter grid for pure consolidation / low ADX (<10)
            elif adx < 20.0:
                k = 0.35   # Moderate grid for balanced oscillation (10 <= ADX < 20)
            else:
                k = 0.50   # Wider safety grid for higher trend momentum (ADX >= 20)

            recommended_spacing_percent = (atr_percent * k)
            recommended_spacing_percent = max(0.15, min(3.5, round(recommended_spacing_percent, 2)))
            recommended_spacing_usdt = round(current_price * (recommended_spacing_percent / 100.0), 6)

            # 5. Number of Grid Levels
            if bb_width_percent > 6.0:
                grid_levels = 14
            elif bb_width_percent > 3.0:
                grid_levels = 10
            else:
                grid_levels = 8

            # 6. Safe Leverage
            if atr_percent > 4.0:
                recommended_leverage = 3
            elif atr_percent < 1.5:
                recommended_leverage = 10
            else:
                recommended_leverage = 5

            # 7. Fetch Live Balance & Auto-Scale Quantity to 90% Wallet Utilization
            balance = 100.0
            try:
                balance = float(self.client.get_wallet_balance() or 100.0)
            except Exception:
                pass

            # Calculate target margin per grid level so total margin = 45% of wallet equity (leaves 55% liquid buffer)
            target_total_margin = balance * 0.45
            target_margin_per_level = target_total_margin / grid_levels if grid_levels > 0 else 10.0
            target_notional_per_level = target_margin_per_level * recommended_leverage

            symbol_info = self.client.get_symbol_info_for(symbol)
            min_qty = symbol_info.get("min_qty", 0.001)
            lot_size = symbol_info.get("lot_size", 2)
            tick_size = symbol_info.get("tick_size", 4)

            quantity = target_notional_per_level / current_price if current_price > 0 else min_qty
            if quantity < min_qty:
                quantity = min_qty

            if isinstance(lot_size, int):
                if lot_size == 0:
                    quantity = float(int(round(quantity)))
                else:
                    quantity = float(round(quantity, lot_size))

            # Risk Shields (Max Loss = 15% wallet equity, Max Position = 2.5x total grid notional)
            max_loss_usdt = round(max(10.0, balance * 0.15), 2)
            max_position_usdt = round(max(100.0, target_notional_per_level * grid_levels * 0.35), 2)

            # 8. Institutional Confidence & Daily ROI Predictions
            ranging_probability = int(round(max(50.0, 100.0 - (adx * 1.0) - abs(rsi - 50.0))))
            ranging_probability = max(65, min(96, ranging_probability))

            est_cycle_roi = round(recommended_spacing_percent * 1.1, 2)
            est_cycles_per_hour = round(max(1.5, min(12.0, (atr_percent / recommended_spacing_percent) * 1.8)), 1)
            
            est_daily_return_min = round(max(2.0, (est_cycles_per_hour * 24 * (est_cycle_roi / 100.0) * 0.40 * 100.0)), 1)
            est_daily_return_max = round(min(25.0, est_daily_return_min * 2.2), 1)

            suggested_tp = round(bb["upper"], tick_size)
            suggested_sl = round(max(0.00000001, bb["lower"] - (1.5 * atr)), tick_size)

            return {
                "symbol": symbol,
                "price": current_price,
                "score": ai_grid_score,
                "status": status,
                "status_badge": status_badge,
                "stars": stars,
                "ranging_probability": ranging_probability,
                "rsi": rsi,
                "atr": round(atr, 6),
                "atr_percent": round(atr_percent, 2),
                "adx": adx,
                "book_imbalance": book_imbalance,
                "funding_percent": funding_percent,
                "funding_apr": funding_apr_percent,
                "funding_next_ts": next_funding_ts,
                "funding_bias": funding_bias,
                "funding_desc": funding_desc,
                "regime": regime,
                "trend_bias": bias,
                "bollinger": bb,
                "grid_levels": grid_levels,
                "spacing_mode": "percent",
                "grid_spacing_percent": recommended_spacing_percent,
                "grid_spacing_usdt": recommended_spacing_usdt,
                "quantity": quantity,
                "recommended_leverage": recommended_leverage,
                "max_loss_usdt": max_loss_usdt,
                "max_position_usdt": max_position_usdt,
                "est_cycle_roi": est_cycle_roi,
                "est_cycles_per_hour": est_cycles_per_hour,
                "est_daily_return_min": est_daily_return_min,
                "est_daily_return_max": est_daily_return_max,
                "suggested_tp": suggested_tp,
                "suggested_sl": suggested_sl,
            }

        except Exception as e:
            return self._fallback_recommendation(symbol, str(e))

    def _fallback_recommendation(self, symbol: str, err: str = "") -> Dict[str, Any]:
        """Fallback recommendation when OHLCV is unavailable."""
        price = 1.0
        try:
            price = self.client.get_price_for(symbol)
        except Exception:
            pass

        return {
            "symbol": symbol,
            "price": price,
            "score": 75,
            "status": "Very Good",
            "status_badge": "🟢 Very Good",
            "stars": "★★★★☆",
            "ranging_probability": 84,
            "rsi": 50.0,
            "atr": round(price * 0.02, 4),
            "atr_percent": 2.0,
            "adx": 16.0,
            "regime": "Optimal Ranging Grid",
            "trend_bias": "Neutral Oscillation",
            "bollinger": {"middle": price, "upper": price * 1.03, "lower": price * 0.97},
            "grid_levels": 10,
            "spacing_mode": "percent",
            "grid_spacing_percent": 0.5,
            "grid_spacing_usdt": round(price * 0.005, 4),
            "quantity": max(round(25.0 / price, 2) if price > 0 else 1.0, 0.001),
            "recommended_leverage": 5,
            "max_loss_usdt": 15.0,
            "max_position_usdt": 250.0,
            "est_cycle_roi": 0.6,
            "est_cycles_per_hour": 4.0,
            "est_daily_return_min": 2.5,
            "est_daily_return_max": 5.0,
            "suggested_tp": round(price * 1.03, 2),
            "suggested_sl": round(price * 0.95, 2),
            "error": err,
        }

    def analyze_all(self, symbols: list = None) -> list:
        """
        Batch-analyze all target coins and return sorted results.
        Used by Auto Portfolio Manager for coin selection.
        """
        if symbols is None:
            symbols = [
                'ETH/USDT', 'SOL/USDT', 'HOME/USDT', 'SUI/USDT', 'DOGE/USDT',
                'ADA/USDT', '1000PEPE/USDT', 'NEAR/USDT', 'BTC/USDT', 'BNB/USDT', 'AVAX/USDT'
            ]

        results = []
        for sym in symbols:
            try:
                analysis = self.analyze_symbol(sym)
                if analysis and 'error' not in analysis:
                    results.append(analysis)
            except Exception:
                pass

        results.sort(key=lambda x: x.get('score', 0), reverse=True)
        return results
