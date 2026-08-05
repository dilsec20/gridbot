"""
Telegram Notification System for Grid Trading Bot.

Sends real-time alerts to your Telegram chat:
  - Grid cycle completions with PnL
  - Auto-switch events
  - Trend Guard pause/resume alerts
  - Risk warnings and emergency shutdowns
  - Daily PnL summaries (every 6 hours)

Setup:
  1. Message @BotFather on Telegram → /newbot → get your BOT TOKEN
  2. Message @userinfobot → get your CHAT ID
  3. Add to config.json:
     "telegram_bot_token": "YOUR_BOT_TOKEN",
     "telegram_chat_id": "YOUR_CHAT_ID"
"""

import time
import threading
import urllib.request
import urllib.parse
import json
from typing import Optional


class TelegramNotifier:
    """
    Sends trading alerts to Telegram via Bot API.
    
    All sends are non-blocking (fire-and-forget in a daemon thread)
    so they never slow down the trading engine.
    """

    def __init__(self, bot_token: str, chat_id: str, logger=None):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = logger
        self.enabled = bool(bot_token and chat_id and not bot_token.startswith('YOUR_'))

        # Rate limiter: max 20 messages per minute
        self._msg_timestamps = []
        self._rate_limit = 20

        # Daily summary tracking
        self.session_start = time.time()
        self.total_cycles = 0
        self.total_pnl = 0.0
        self.last_summary_time = time.time()
        self.summary_interval = 6 * 3600  # Every 6 hours

        if self.enabled:
            self._send_async("🤖 *GridBot Started!*\n\nTelegram notifications active.\nYou'll receive alerts for:\n✅ Cycle completions\n⚡ Auto-switches\n🛡️ Trend Guard alerts\n⛔ Risk warnings")
        elif logger:
            logger.system("Telegram notifications disabled (no token/chat_id in config)")

    def _send_async(self, message: str):
        """Send message in background thread (non-blocking)."""
        if not self.enabled:
            return

        # Rate limit check
        now = time.time()
        self._msg_timestamps = [t for t in self._msg_timestamps if now - t < 60]
        if len(self._msg_timestamps) >= self._rate_limit:
            return
        self._msg_timestamps.append(now)

        thread = threading.Thread(target=self._send, args=(message,), daemon=True)
        thread.start()

    def _send(self, message: str):
        """Actually send the message via Telegram Bot API with robust fallback."""
        try:
            bot_token = str(self.bot_token).strip()
            chat_id = str(self.chat_id).strip()
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            # Strip formatting characters for 100% reliable delivery
            clean_msg = message.replace('*', '').replace('`', '').replace('_', '')
            data = urllib.parse.urlencode({
                'chat_id': chat_id,
                'text': clean_msg,
                'disable_web_page_preview': 'true',
            }).encode('utf-8')

            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                pass  # Fire and forget

        except Exception as e:
            if self.logger:
                self.logger.warn(f"Telegram send failed: {e}")

    # ═══════════ Alert Methods ═══════════

    def notify_cycle_complete(self, cycle_num: int, pnl: float, total_pnl: float, symbol: str):
        """Alert when a grid cycle completes."""
        self.total_cycles += 1
        self.total_pnl += pnl

        self._send_async(
            f"✅ *Cycle #{cycle_num} Completed!*\n\n"
            f"Pair: `{symbol}`\n"
            f"Cycle PnL: `+${pnl:.4f}` USDT\n"
            f"Total PnL: `+${total_pnl:.4f}` USDT\n"
            f"Session: {self.total_cycles} cycles"
        )

    def notify_auto_switch(self, from_sym: str, to_sym: str, from_score: int, to_score: int):
        """Alert when Auto Portfolio Manager switches coins."""
        self._send_async(
            f"⚡ *Auto-Switch!*\n\n"
            f"`{from_sym}` → `{to_sym}`\n"
            f"Score: {from_score} → *{to_score}*\n"
            f"Reason: +{to_score - from_score} point advantage"
        )

    def notify_trend_guard(self, paused: bool, reason: str, adx: float, rsi: float):
        """Alert when Trend Guard activates or deactivates."""
        if paused:
            self._send_async(
                f"🛡️ *TREND GUARD — PAUSED!*\n\n"
                f"Reason: _{reason}_\n"
                f"ADX: `{adx:.1f}` | RSI: `{rsi:.1f}`\n\n"
                f"Grid orders paused to protect from losses.\n"
                f"Will auto-resume when market normalizes."
            )
        else:
            self._send_async(
                f"✅ *TREND GUARD — RESUMED!*\n\n"
                f"Market conditions normalized.\n"
                f"ADX: `{adx:.1f}` | RSI: `{rsi:.1f}`\n"
                f"Grid trading resumed!"
            )

    def notify_risk_warning(self, message: str):
        """Alert on risk events (max loss, position limit, etc)."""
        self._send_async(f"⛔ *RISK WARNING!*\n\n{message}")

    def notify_bot_stopped(self, total_pnl: float, cycles: int, balance: float):
        """Alert when bot stops."""
        self._send_async(
            f"🔴 *Bot Stopped*\n\n"
            f"Total PnL: `${total_pnl:+.4f}`\n"
            f"Cycles: {cycles}\n"
            f"Balance: `${balance:.2f}`"
        )

    def check_periodic_summary(self, current_pnl: float, balance: float, symbol: str):
        """Send periodic PnL summary every 6 hours."""
        now = time.time()
        if now - self.last_summary_time < self.summary_interval:
            return

        self.last_summary_time = now
        uptime_hours = (now - self.session_start) / 3600

        self._send_async(
            f"📊 *6-Hour Summary*\n\n"
            f"Pair: `{symbol}`\n"
            f"Uptime: `{uptime_hours:.1f}h`\n"
            f"Cycles: `{self.total_cycles}`\n"
            f"Session PnL: `${self.total_pnl:+.4f}`\n"
            f"Exchange PnL: `${current_pnl:+.4f}`\n"
            f"Balance: `${balance:.2f} USDT`"
        )
