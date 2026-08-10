"""
Trend Guard — 4-Stage Anti-Trend & Exposure Control Engine.

Monitors real-time market conditions and enforces a 4-Stage Risk State Machine:
  1. NORMAL: Ranging market. Grid engine operates with standard spacing.
  2. TREND_WARNING: ADX > 35 or ATR surge. Dynamic spacing widens.
  3. GRID_PAUSED: ADX > 40, RSI extremes (< 25 or > 75), or Real-Time Price Displacement > Threshold.
     Cancels opening limit orders, blocks replacement placement, PRESERVES protective exit/TP orders.
  4. EMERGENCY: Extreme displacement (> 1.5x threshold) while holding position.
     Triggers automatic 50% Position Trim to eliminate liquidation risk.
"""

import time
from enum import Enum
from typing import Optional
from quant_engine import calculate_rsi, calculate_adx, calculate_atr


class GuardState(str, Enum):
    NORMAL = "normal"
    TREND_WARNING = "trend_warning"
    GRID_PAUSED = "grid_paused"
    EMERGENCY = "emergency"


# Trend Guard Thresholds (Anti-Trend Protection Active)
ADX_PAUSE_THRESHOLD = 40.0     # Auto-pause grid when ADX > 40 (strong trending market)
ADX_RESUME_THRESHOLD = 30.0     # Resume grid when ADX drops below 30
RSI_OVERBOUGHT = 75.0          # Auto-pause grid when RSI > 75 (extreme overbought pump)
RSI_OVERSOLD = 25.0            # Auto-pause grid when RSI < 25 (extreme oversold crash)
RSI_SAFE_HIGH = 70.0           # Resume if RSI drops below 70
RSI_SAFE_LOW = 30.0            # Resume if RSI rises above 30

# Dynamic Spacing Thresholds
ATR_NORMAL_LOW = 1.0           # Normal ATR % range lower bound
ATR_NORMAL_HIGH = 4.0          # Normal ATR % range upper bound
SPACING_WIDEN_FACTOR = 1.5     # Widen spacing by 50% during high volatility
SPACING_TIGHTEN_FACTOR = 0.8   # Tighten spacing by 20% during low volatility

# Minimum check interval (seconds) — don't spam API
TREND_CHECK_INTERVAL = 60      # Check trend every 60 seconds


class TrendGuard:
    """
    Institutional 4-Stage Market Regime & Exposure Monitor.
    """

    def __init__(self, client, logger, socketio=None):
        self.client = client
        self.logger = logger
        self.socketio = socketio

        # 4-Stage State Machine
        self.state = GuardState.NORMAL
        self.pause_reason = ""
        self.last_check_time = 0.0
        self.last_adx = 0.0
        self.last_rsi = 50.0
        self.last_atr_percent = 2.0
        self.current_spacing_multiplier = 1.0

        # Real-Time Price Spike Shield & Emergency Execution Tracking
        self.grid_start_price = None      # Set when grid starts
        self.spike_paused = False         # Internal flag for spike pause
        self.emergency_triggered = False  # Internal flag for emergency state
        self.emergency_executed = False   # Guarantee 50% trim executes EXACTLY ONCE per event

        # History for dynamic spacing
        self.atr_history = []

    @property
    def is_paused(self) -> bool:
        """Helper property: True if grid is in GRID_PAUSED or EMERGENCY state."""
        return self.state in [GuardState.GRID_PAUSED, GuardState.EMERGENCY]

    @property
    def is_emergency(self) -> bool:
        """Helper property: True if grid is in EMERGENCY state."""
        return self.state == GuardState.EMERGENCY

    def set_grid_start_price(self, price: float):
        """Set the grid start price when grid initializes. Called by web_server."""
        self.grid_start_price = price
        self.spike_paused = False
        self.emergency_triggered = False
        self.emergency_executed = False
        self.state = GuardState.NORMAL
        self.logger.system(f"🛡️ 4-Stage Exposure Shield armed at start price: ${price:.6f}")

    def check_market_conditions(self, symbol: str) -> dict:
        """
        Fetch latest OHLCV and calculate ADX/RSI/ATR to determine market regime.
        """
        now = time.time()
        if now - self.last_check_time < TREND_CHECK_INTERVAL:
            return {
                'should_pause': self.is_paused,
                'should_resume': False,
                'adx': self.last_adx,
                'rsi': self.last_rsi,
                'atr_percent': self.last_atr_percent,
                'regime': 'Cached',
                'spacing_multiplier': self.current_spacing_multiplier,
            }

        try:
            ohlcv = self.client.fetch_ohlcv(symbol, timeframe='1h', limit=50)
            if not ohlcv or len(ohlcv) < 30:
                return self._safe_default()

            closes = [c[4] for c in ohlcv]
            highs = [c[2] for c in ohlcv]
            lows = [c[3] for c in ohlcv]

            adx = calculate_adx(highs, lows, closes, period=14)
            rsi = calculate_rsi(closes, period=14)
            atr = calculate_atr(highs, lows, closes, period=14)
            price = closes[-1]
            atr_percent = (atr / price) * 100.0 if price > 0 else 2.0

            self.last_adx = adx
            self.last_rsi = rsi
            self.last_atr_percent = atr_percent
            self.last_check_time = now

            self.atr_history.append(atr_percent)
            if len(self.atr_history) > 30:
                self.atr_history = self.atr_history[-30:]

            should_pause = False
            should_resume = False
            regime = "Ranging (Safe)"

            # Anti-Trend Protection Checks
            if adx > ADX_PAUSE_THRESHOLD:
                should_pause = True
                regime = f"⚠️ STRONG TREND (ADX: {adx:.1f})"
            elif rsi > RSI_OVERBOUGHT:
                should_pause = True
                regime = f"⚠️ OVERBOUGHT PUMP (RSI: {rsi:.1f})"
            elif rsi < RSI_OVERSOLD:
                should_pause = True
                regime = f"⚠️ OVERSOLD CRASH (RSI: {rsi:.1f})"
            elif adx > 35.0 or rsi > 70.0 or rsi < 30.0:
                regime = f"⚡ TREND WARNING (ADX: {adx:.1f}, RSI: {rsi:.1f})"

            # Multi-condition resume check
            if self.is_paused:
                if adx < ADX_RESUME_THRESHOLD and RSI_SAFE_LOW < rsi < RSI_SAFE_HIGH:
                    should_resume = True
                    regime = "✅ Market Normalized — Resuming"

            # Dynamic Spacing Multiplier
            spacing_mult = 1.0
            if atr_percent > ATR_NORMAL_HIGH:
                spacing_mult = min(2.0, SPACING_WIDEN_FACTOR * (atr_percent / ATR_NORMAL_HIGH))
            elif atr_percent < ATR_NORMAL_LOW:
                spacing_mult = max(0.6, SPACING_TIGHTEN_FACTOR)

            self.current_spacing_multiplier = round(spacing_mult, 2)

            return {
                'should_pause': should_pause,
                'should_resume': should_resume,
                'adx': adx,
                'rsi': rsi,
                'atr_percent': round(atr_percent, 2),
                'regime': regime,
                'spacing_multiplier': self.current_spacing_multiplier,
            }

        except Exception as e:
            self.logger.warn(f"TrendGuard check error: {e}")
            return self._safe_default()

    def check_price_spike(self, current_price: float) -> dict:
        """
        REAL-TIME Price Spike Shield — runs every cycle.
        Calculates ATR-Adaptive Displacement Threshold: max(3.0%, min(8.0%, 2.5 * ATR%)).
        
        Fixes sequential price progression bug (0% -> 8% -> 12%) and multi-condition resume requirement.
        """
        if self.grid_start_price is None or self.grid_start_price <= 0:
            return {
                'spike_detected': False,
                'emergency_detected': False,
                'spike_resumed': False,
                'deviation_pct': 0.0,
                'threshold_pct': 5.0,
                'emergency_threshold_pct': 7.5
            }

        deviation_pct = abs(current_price - self.grid_start_price) / self.grid_start_price * 100.0
        atr_mult = max(3.0, min(8.0, round(2.5 * self.last_atr_percent, 2)))
        emergency_threshold = round(atr_mult * 1.5, 2)

        spike_detected = False
        emergency_detected = False
        spike_resumed = False

        # FIX 2: Evaluate spike_detected AND emergency_detected independently as price progresses!
        if deviation_pct > atr_mult:
            if not self.spike_paused:
                spike_detected = True
                self.spike_paused = True

            if deviation_pct > emergency_threshold and not self.emergency_triggered:
                emergency_detected = True
                self.emergency_triggered = True

        # FIX 3: Safe resume requirement — Price MUST return within 60% of threshold AND ADX < 30 AND 30 < RSI < 70
        elif deviation_pct < (atr_mult * 0.6) and self.spike_paused:
            safe_trend = (self.last_adx < ADX_RESUME_THRESHOLD)
            safe_rsi = (RSI_SAFE_LOW < self.last_rsi < RSI_SAFE_HIGH)

            if safe_trend and safe_rsi:
                spike_resumed = True
                self.spike_paused = False
                self.emergency_triggered = False
                self.emergency_executed = False

        return {
            'spike_detected': spike_detected,
            'emergency_detected': emergency_detected,
            'spike_resumed': spike_resumed,
            'deviation_pct': round(deviation_pct, 2),
            'threshold_pct': atr_mult,
            'emergency_threshold_pct': emergency_threshold,
        }

    def process(self, symbol: str, current_price: float = 0.0) -> str:
        """
        Main processing method — updates 4-stage GuardState.
        """
        # ─── 1. REAL-TIME Price Spike & Emergency Check ───
        if current_price > 0:
            spike = self.check_price_spike(current_price)

            if spike['emergency_detected']:
                self.state = GuardState.EMERGENCY
                self.pause_reason = f"🚨 STAGE 4 EMERGENCY! {spike['deviation_pct']:.1f}% displacement (Threshold: {spike['emergency_threshold_pct']}%)"
                self.logger.risk(
                    f"🚨 STAGE 4 EMERGENCY EXPOSURE CONTROL ACTIVATED! Price displaced {spike['deviation_pct']:.1f}% "
                    f"from start price (${self.grid_start_price:.6f} → ${current_price:.6f}) — "
                    f"Signaling 50% Position Trim!"
                )
                if self.socketio:
                    self.socketio.emit('trend_guard_update', self.get_status())
                return self.pause_reason

            elif spike['spike_detected'] and self.state != GuardState.EMERGENCY:
                self.state = GuardState.GRID_PAUSED
                self.pause_reason = f"⚡ STAGE 3 GRID PAUSED: Price spike {spike['deviation_pct']:.1f}% (Threshold: {spike['threshold_pct']}%)"
                self.logger.risk(
                    f"🛡️ STAGE 3 PRICE SPIKE SHIELD ACTIVATED! Price moved {spike['deviation_pct']:.1f}% "
                    f"from grid start (${self.grid_start_price:.6f} → ${current_price:.6f}) — "
                    f"Grid PAUSED to prevent position escalation!"
                )
                if self.socketio:
                    self.socketio.emit('trend_guard_update', self.get_status())
                return self.pause_reason

            elif spike['spike_resumed'] and self.is_paused:
                self.state = GuardState.NORMAL
                self.pause_reason = ""
                self.logger.system(
                    f"🛡️ TREND GUARD CLEARED: Price returned to {spike['deviation_pct']:.1f}% "
                    f"and ADX/RSI normalized — Grid RESUMED."
                )
                if self.socketio:
                    self.socketio.emit('trend_guard_update', self.get_status())
                return "Trend Guard Cleared — Resumed"

        # ─── 2. Hourly ADX/RSI Regime Check ───
        result = self.check_market_conditions(symbol)

        if result['should_pause'] and self.state == GuardState.NORMAL:
            self.state = GuardState.GRID_PAUSED
            self.pause_reason = result['regime']
            self.logger.risk(
                f"🛡️ STAGE 3 TREND GUARD ACTIVATED: {result['regime']} — Grid PAUSED! "
                f"(ADX: {result['adx']:.1f}, RSI: {result['rsi']:.1f})"
            )
            if self.socketio:
                self.socketio.emit('trend_guard_update', self.get_status())

        elif result['should_resume'] and self.state == GuardState.GRID_PAUSED and not self.spike_paused:
            self.state = GuardState.NORMAL
            self.pause_reason = ""
            self.logger.system(
                f"🛡️ STAGE 1 NORMAL: Market conditions normalized! Grid RESUMED. "
                f"(ADX: {result['adx']:.1f}, RSI: {result['rsi']:.1f})"
            )
            if self.socketio:
                self.socketio.emit('trend_guard_update', self.get_status())

        elif self.state == GuardState.NORMAL and "TREND WARNING" in result['regime']:
            self.state = GuardState.TREND_WARNING

        return self.pause_reason or self.state.value

    def get_adjusted_spacing(self, base_spacing: float) -> float:
        """Return dynamically adjusted grid spacing based on current volatility."""
        return round(base_spacing * self.current_spacing_multiplier, 8)

    def get_status(self) -> dict:
        """Get current trend guard status for dashboard."""
        return {
            'state': self.state.value,
            'paused': self.is_paused,
            'emergency': self.is_emergency,
            'emergency_executed': self.emergency_executed,
            'reason': self.pause_reason,
            'adx': self.last_adx,
            'rsi': self.last_rsi,
            'atr_percent': self.last_atr_percent,
            'spacing_multiplier': self.current_spacing_multiplier,
        }

    def _safe_default(self):
        return {
            'should_pause': False,
            'should_resume': False,
            'adx': self.last_adx,
            'rsi': self.last_rsi,
            'atr_percent': self.last_atr_percent,
            'regime': 'Unknown',
            'spacing_multiplier': 1.0,
        }
