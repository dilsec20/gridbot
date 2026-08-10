"""
Trend Guard — Anti-Trend Protection & Dynamic Grid Spacing.

Monitors real-time market conditions and protects the grid from trending markets.

Features:
  1. Anti-Trend Protection: Auto-pauses grid when ADX > 40 or RSI extremes (< 25 or > 75)
     to prevent accumulating one-sided losing positions during crashes/pumps.
  2. Dynamic Grid Spacing: Auto-widens spacing when volatility spikes (ATR surge)
     and auto-tightens when volatility drops, maximizing cycle capture.
  3. Auto-Resume: Resumes grid automatically when market conditions normalize.
"""

import time
from typing import Optional
from quant_engine import calculate_rsi, calculate_adx, calculate_atr


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
    Real-time market regime monitor that protects the grid from trending markets.
    
    When a strong trend is detected:
    1. Logs a warning with the detected regime
    2. Signals the bot to pause new grid orders (existing orders remain)
    3. Monitors continuously until conditions normalize
    4. Auto-resumes the grid when market returns to ranging
    """

    def __init__(self, client, logger, socketio=None):
        self.client = client
        self.logger = logger
        self.socketio = socketio

        # State
        self.is_paused = False
        self.pause_reason = ""
        self.last_check_time = 0.0
        self.last_adx = 0.0
        self.last_rsi = 50.0
        self.last_atr_percent = 2.0
        self.current_spacing_multiplier = 1.0

        # History for dynamic spacing
        self.atr_history = []

    def check_market_conditions(self, symbol: str) -> dict:
        """
        Fetch latest OHLCV and calculate ADX/RSI/ATR to determine market regime.
        
        Returns dict with:
          - should_pause: bool
          - should_resume: bool  
          - adx: float
          - rsi: float
          - atr_percent: float
          - regime: str
          - spacing_multiplier: float
        """
        now = time.time()
        if now - self.last_check_time < TREND_CHECK_INTERVAL:
            return {
                'should_pause': False,
                'should_resume': False,
                'adx': self.last_adx,
                'rsi': self.last_rsi,
                'atr_percent': self.last_atr_percent,
                'regime': 'Cached',
                'spacing_multiplier': self.current_spacing_multiplier,
            }

        try:
            ohlcv = self.client.fetch_ohlcv(symbol, timeframe='15m', limit=50)
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

            # Track ATR history for dynamic spacing
            self.atr_history.append(atr_percent)
            if len(self.atr_history) > 30:
                self.atr_history = self.atr_history[-30:]

            # Determine regime
            should_pause = False
            should_resume = False
            regime = "Ranging (Safe)"

            # --- Anti-Trend Protection ---
            if adx > ADX_PAUSE_THRESHOLD:
                should_pause = True
                regime = f"⚠️ STRONG TREND (ADX: {adx:.1f})"
            elif rsi > RSI_OVERBOUGHT:
                should_pause = True
                regime = f"⚠️ OVERBOUGHT PUMP (RSI: {rsi:.1f})"
            elif rsi < RSI_OVERSOLD:
                should_pause = True
                regime = f"⚠️ OVERSOLD CRASH (RSI: {rsi:.1f})"

            # Check for resume conditions
            if self.is_paused:
                if adx < ADX_RESUME_THRESHOLD and RSI_SAFE_LOW < rsi < RSI_SAFE_HIGH:
                    should_resume = True
                    regime = "✅ Market Normalized — Resuming"

            # --- Dynamic Grid Spacing ---
            spacing_mult = 1.0
            if atr_percent > ATR_NORMAL_HIGH:
                # High volatility → widen spacing to avoid whipsaws
                spacing_mult = min(2.0, SPACING_WIDEN_FACTOR * (atr_percent / ATR_NORMAL_HIGH))
            elif atr_percent < ATR_NORMAL_LOW:
                # Low volatility → tighten spacing to catch more cycles
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

    def process(self, symbol: str) -> str:
        """
        Main processing method — called every loop iteration.
        Returns the current regime string.
        
        Side effects:
          - Sets self.is_paused = True/False
          - Emits trend_guard_update to dashboard
          - Logs warnings
        """
        result = self.check_market_conditions(symbol)

        if result['should_pause'] and not self.is_paused:
            self.is_paused = True
            self.pause_reason = result['regime']
            self.logger.risk(
                f"🛡️ TREND GUARD ACTIVATED: {result['regime']} — "
                f"Grid PAUSED to protect from losses! "
                f"(ADX: {result['adx']:.1f}, RSI: {result['rsi']:.1f})"
            )
            if self.socketio:
                self.socketio.emit('trend_guard_update', {
                    'paused': True,
                    'reason': result['regime'],
                    'adx': result['adx'],
                    'rsi': result['rsi'],
                    'atr_percent': result['atr_percent'],
                })

        elif result['should_resume'] and self.is_paused:
            self.is_paused = False
            self.pause_reason = ""
            self.logger.system(
                f"🛡️ TREND GUARD CLEARED: Market conditions normalized! "
                f"Grid RESUMED. (ADX: {result['adx']:.1f}, RSI: {result['rsi']:.1f})"
            )
            if self.socketio:
                self.socketio.emit('trend_guard_update', {
                    'paused': False,
                    'reason': 'Market normalized',
                    'adx': result['adx'],
                    'rsi': result['rsi'],
                    'atr_percent': result['atr_percent'],
                })

        return result['regime']

    def get_adjusted_spacing(self, base_spacing: float) -> float:
        """
        Return dynamically adjusted grid spacing based on current volatility.
        
        During high volatility: wider spacing (fewer but safer cycles)
        During low volatility: tighter spacing (more frequent cycles)
        """
        return round(base_spacing * self.current_spacing_multiplier, 8)

    def get_status(self) -> dict:
        """Get current trend guard status for dashboard."""
        return {
            'paused': self.is_paused,
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
