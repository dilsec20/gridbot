"""
Auto Portfolio Manager — Fully Autonomous Coin Selection & Grid Management.

Every 30 minutes, rescores all supported coins using the 7-factor AI Quant Engine.
If a significantly better coin is found (+10 score) and no open position exists,
automatically switches to the optimal coin with zero-risk transitions.

Safety Rules:
  1. Only switches when current position size == 0 (no open trades)
  2. Minimum 1-hour hold time before considering a switch
  3. Smart Max Position auto-calculated from wallet balance × leverage × 0.35
  4. Never trades coins scoring below 65 (Good threshold)
"""

import time
import threading
from typing import Optional, Callable

from quant_engine import QuantEngine
from logger import BotLogger


# Coins the Auto Manager evaluates
AUTO_TARGET_COINS = [
    'ETH/USDT', 'SOL/USDT', 'HOME/USDT', 'STAR/USDT', 'DOGE/USDT',
    'ADA/USDT', '1000PEPE/USDT', 'NEAR/USDT', 'BTC/USDT', 'BNB/USDT', 'AVAX/USDT'
]

# Minimum score gap to trigger a switch (prevents unnecessary churn)
MIN_SCORE_GAP_TO_SWITCH = 10

# Minimum hold time in seconds before considering a switch (1 hour)
MIN_HOLD_TIME_SECONDS = 3600

# Rescore interval in seconds (30 minutes)
RESCORE_INTERVAL_SECONDS = 1800

# Minimum score to trade a coin (below this = "Avoid / Risky")
MIN_TRADEABLE_SCORE = 65


def get_smart_max_position(balance: float, leverage: int) -> float:
    """
    Calculate safe max position value based on wallet balance and leverage.
    
    Formula: balance × leverage × 0.35 (capped at 1000.0 USDT for risk safety)
    """
    raw = balance * leverage * 0.35
    return round(min(1000.0, max(50.0, raw)), 2)


class AutoPortfolioManager:
    """
    Autonomous coin selection and grid management engine.
    
    When enabled, the manager:
    1. Rescores all coins every 30 minutes
    2. Compares the best coin with the currently trading coin
    3. If a better coin is found (score gap >= 10) AND no open position:
       → Triggers a safe switch to the better coin
    4. Auto-calculates max_position based on wallet balance + leverage
    """

    def __init__(self, client, logger: BotLogger, socketio=None):
        self.client = client
        self.logger = logger
        self.socketio = socketio
        self.quant = QuantEngine(client)

        # State
        self.is_active = False
        self.current_symbol: Optional[str] = None
        self.current_score: int = 0
        self.last_switch_time: float = 0.0
        self.last_rescore_time: float = 0.0
        self.next_rescore_in: int = RESCORE_INTERVAL_SECONDS

        # Latest rescore results (sorted by score descending)
        self.latest_scores: list = []

        # Callback to trigger grid restart with new config
        self.on_switch_requested: Optional[Callable] = None

        # Background thread
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, current_symbol: str, current_score: int = 80):
        """Start the auto portfolio manager background loop."""
        self.is_active = True
        self.current_symbol = current_symbol
        self.current_score = current_score
        self.last_switch_time = time.time()
        self.last_rescore_time = time.time()
        self._stop_event.clear()

        self.logger.system(f"🤖 Auto Portfolio Manager ACTIVE — Currently trading: {current_symbol} (Score: {current_score})")
        self.logger.system(f"🤖 Auto Mode: Will rescore all coins every 30 min. Min hold: 1 hour. Switch gap: +{MIN_SCORE_GAP_TO_SWITCH} points.")

        if self.socketio:
            self.socketio.emit('auto_mode_update', {
                'active': True,
                'current_symbol': current_symbol,
                'current_score': current_score,
                'next_rescore_in': RESCORE_INTERVAL_SECONDS,
                'message': f'Auto Mode active — trading {current_symbol}'
            })

    def stop(self):
        """Stop the auto portfolio manager."""
        self.is_active = False
        self._stop_event.set()
        self.logger.system("🤖 Auto Portfolio Manager STOPPED — Manual mode restored.")

        if self.socketio:
            self.socketio.emit('auto_mode_update', {
                'active': False,
                'current_symbol': self.current_symbol,
                'current_score': self.current_score,
                'message': 'Auto Mode stopped'
            })

    def update_current(self, symbol: str, score: int):
        """Update the currently trading symbol and score (called after grid starts)."""
        self.current_symbol = symbol
        self.current_score = score
        self.last_switch_time = time.time()

    def rescore_all(self) -> list:
        """
        Score all target coins using the 7-factor AI Quant Engine.
        Returns a list of coin analyses sorted by score descending.
        """
        results = []
        for sym in AUTO_TARGET_COINS:
            try:
                analysis = self.quant.analyze_symbol(sym)
                if analysis and 'error' not in analysis:
                    results.append(analysis)
            except Exception:
                pass

        # Sort by score descending
        results.sort(key=lambda x: x.get('score', 0), reverse=True)
        self.latest_scores = results
        self.last_rescore_time = time.time()

        if results:
            top = results[0]
            self.logger.system(
                f"🤖 Auto Rescore Complete — Top: {top['symbol']} ({top['score']}/100 {top['status']}), "
                f"Current: {self.current_symbol} ({self.current_score}/100)"
            )

        if self.socketio:
            top3 = [{'symbol': r['symbol'], 'score': r['score'], 'status': r['status']} for r in results[:3]]
            self.socketio.emit('auto_rescore', {
                'top3': top3,
                'current_symbol': self.current_symbol,
                'current_score': self.current_score,
                'next_rescore_in': RESCORE_INTERVAL_SECONDS,
            })

        return results

    def should_switch(self) -> Optional[dict]:
        """
        Determine if the bot should switch to a better coin.
        
        Returns the best coin's analysis dict if a switch is warranted, None otherwise.
        
        Safety conditions (ALL must be true):
          1. Auto mode is active
          2. We have rescore results
          3. Best coin score >= current score + MIN_SCORE_GAP_TO_SWITCH
          4. Best coin score >= MIN_TRADEABLE_SCORE
          5. Minimum hold time (1 hour) has elapsed since last switch
          6. No open position on exchange (checked by caller)
        """
        if not self.is_active or not self.latest_scores:
            return None

        best = self.latest_scores[0]
        best_score = best.get('score', 0)
        best_symbol = best.get('symbol', '')

        # Don't switch to the same coin
        if best_symbol == self.current_symbol:
            return None

        # Must meet minimum tradeable threshold
        if best_score < MIN_TRADEABLE_SCORE:
            return None

        # Must have significant score advantage
        if best_score < self.current_score + MIN_SCORE_GAP_TO_SWITCH:
            return None

        # Must have held current coin for at least 1 hour
        elapsed = time.time() - self.last_switch_time
        if elapsed < MIN_HOLD_TIME_SECONDS:
            remaining = int((MIN_HOLD_TIME_SECONDS - elapsed) / 60)
            self.logger.system(
                f"🤖 Better coin found: {best_symbol} ({best_score}) vs {self.current_symbol} ({self.current_score}), "
                f"but minimum hold time not met. {remaining} min remaining."
            )
            return None

        self.logger.system(
            f"🤖 ⚡ SWITCH RECOMMENDED: {best_symbol} ({best_score}/100) is +{best_score - self.current_score} points "
            f"better than {self.current_symbol} ({self.current_score}/100)!"
        )

        return best

    def check_and_switch(self, has_open_position: bool) -> Optional[dict]:
        """
        Main check method — called periodically from the bot main loop.
        
        1. If rescore interval has elapsed → run rescore
        2. If should_switch() says yes AND no open position → return switch config
        3. Otherwise return None
        
        Args:
            has_open_position: True if the bot currently has an open position on exchange
            
        Returns:
            New coin analysis dict if switch should happen, None otherwise
        """
        if not self.is_active:
            return None

        now = time.time()

        # Update countdown timer
        self.next_rescore_in = max(0, int(RESCORE_INTERVAL_SECONDS - (now - self.last_rescore_time)))

        # Time to rescore?
        if now - self.last_rescore_time >= RESCORE_INTERVAL_SECONDS:
            self.rescore_all()

        # Should we switch?
        best = self.should_switch()
        if best is None:
            return None

        # Final safety gate: NEVER switch with an open position
        if has_open_position:
            self.logger.system(
                f"🤖 Switch to {best['symbol']} pending — waiting for open position to close..."
            )
            if self.socketio:
                self.socketio.emit('auto_mode_update', {
                    'active': True,
                    'current_symbol': self.current_symbol,
                    'current_score': self.current_score,
                    'pending_switch': best['symbol'],
                    'pending_score': best['score'],
                    'message': f"Switch pending — waiting for position to close"
                })
            return None

        # All safety checks passed — execute switch!
        self.logger.system(
            f"🤖 ✅ EXECUTING AUTO-SWITCH: {self.current_symbol} → {best['symbol']} "
            f"(Score: {self.current_score} → {best['score']})"
        )

        if self.socketio:
            self.socketio.emit('auto_switch', {
                'from_symbol': self.current_symbol,
                'to_symbol': best['symbol'],
                'from_score': self.current_score,
                'to_score': best['score'],
                'message': f"Switching from {self.current_symbol} to {best['symbol']}!"
            })

        # Update state
        self.current_symbol = best['symbol']
        self.current_score = best['score']
        self.last_switch_time = time.time()

        return best

    def get_status(self) -> dict:
        """Get current auto mode status for dashboard display."""
        return {
            'active': self.is_active,
            'current_symbol': self.current_symbol,
            'current_score': self.current_score,
            'next_rescore_in': self.next_rescore_in,
            'last_switch_time': self.last_switch_time,
            'top_coins': [
                {'symbol': r['symbol'], 'score': r['score'], 'status': r['status']}
                for r in self.latest_scores[:5]
            ] if self.latest_scores else [],
        }
