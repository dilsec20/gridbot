"""
Logger module for Grid Trading Bot.
Provides color-coded console output and file logging.
"""

import os
import sys
import logging
from datetime import datetime
from colorama import init, Fore, Style

# Initialize colorama for Windows support
init(autoreset=True)

# Fix Windows console encoding for Unicode
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def fmt_price(price: float) -> str:
    """Format price dynamically with high precision for micro coins."""
    try:
        p = float(price or 0)
        if p == 0:
            return "$0.00"
        elif abs(p) < 0.001:
            return f"${p:,.6f}"
        elif abs(p) < 1:
            return f"${p:,.5f}"
        elif abs(p) < 100:
            return f"${p:,.4f}"
        else:
            return f"${p:,.2f}"
    except Exception:
        return f"${price}"


class BotLogger:
    """Color-coded logger with console + file output and trade history."""

    # Color mappings for log levels
    COLORS = {
        "INFO": Fore.GREEN,
        "WARN": Fore.YELLOW,
        "ERROR": Fore.RED,
        "TRADE": Fore.CYAN,
        "GRID": Fore.MAGENTA,
        "RISK": Fore.YELLOW + Style.BRIGHT,
        "SYSTEM": Fore.WHITE + Style.BRIGHT,
    }

    ICONS = {
        "INFO": "[+]",
        "WARN": "[!]",
        "ERROR": "[X]",
        "TRADE": "[$]",
        "GRID": "[#]",
        "RISK": "[!]",
        "SYSTEM": "[*]",
    }

    def __init__(self, log_file: str = "trades.log"):
        self.log_file = log_file
        self.trade_count = 0
        self.start_time = datetime.now()

        # Setup file logger
        self._file_logger = logging.getLogger("grid_bot")
        self._file_logger.setLevel(logging.DEBUG)

        # Prevent duplicate handlers on re-init
        if not self._file_logger.handlers:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            file_handler.setFormatter(formatter)
            self._file_logger.addHandler(file_handler)

    def _log(self, level: str, message: str, to_file: bool = True):
        """Internal log method with color output."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = self.COLORS.get(level, Fore.WHITE)
        icon = self.ICONS.get(level, "  ")

        # Console output
        try:
            print(f"  {color}{icon} [{timestamp}] {level:<6}{Style.RESET_ALL} | {message}")
        except UnicodeEncodeError:
            print(f"  {icon} [{timestamp}] {level:<6} | {message}")

        # File output
        if to_file:
            self._file_logger.info(f"[{level}] {message}")

    def info(self, message: str):
        self._log("INFO", message)

    def warn(self, message: str):
        self._log("WARN", message)

    def error(self, message: str):
        self._log("ERROR", message)

    def trade(self, side: str, price: float, qty: float, pnl: float = None):
        """Log a trade execution."""
        self.trade_count += 1
        pnl_str = f" | PnL: ${pnl:+.4f}" if pnl is not None else ""
        price_str = fmt_price(price)
        msg = f"{side.upper()} {qty} @ {price_str}{pnl_str}"
        self._log("TRADE", msg)

    def grid(self, message: str):
        self._log("GRID", message)

    def risk(self, message: str):
        self._log("RISK", message)

    def system(self, message: str):
        self._log("SYSTEM", message)

    def banner(self):
        """Print startup banner."""
        print()
        print(f"  {Fore.CYAN + Style.BRIGHT}+====================================================+")
        print(f"  |                                                    |")
        print(f"  |    GRID TRADING BOT  -  Binance Futures            |")
        print(f"  |                                                    |")
        print(f"  |    Strategy : Grid Trading (Mean Reversion)        |")
        print(f"  |    Mode     : TESTNET (Paper Trading)              |")
        print(f"  |    Engine   : Python + ccxt                        |")
        print(f"  |                                                    |")
        print(f"  +====================================================+{Style.RESET_ALL}")
        print()

    def dashboard(self, symbol: str, price: float, pnl: float, cycles: int,
                  open_buys: int, open_sells: int, grid_low: float, grid_high: float):
        """Print live dashboard (clears and reprints)."""
        runtime = datetime.now() - self.start_time
        hours, remainder = divmod(int(runtime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
        pnl_sign = "+" if pnl >= 0 else ""

        print(f"\r  {Fore.CYAN}+----------------------------------------------+")
        print(f"  |  {Style.BRIGHT}{symbol:<12}{Style.RESET_ALL}{Fore.CYAN}             Runtime: {runtime_str}   |")
        print(f"  +----------------------------------------------+")
        print(f"  |  Price:  {Fore.WHITE + Style.BRIGHT}${price:>12,.2f}{Style.RESET_ALL}{Fore.CYAN}                       |")
        print(f"  |  PnL:   {pnl_color}{pnl_sign}${abs(pnl):>11,.2f}{Style.RESET_ALL}{Fore.CYAN}  ({cycles} cycles)          |")
        print(f"  |  Orders: {Fore.GREEN}{open_buys} buy{Style.RESET_ALL}{Fore.CYAN} / {Fore.RED}{open_sells} sell{Style.RESET_ALL}{Fore.CYAN}                    |")
        print(f"  |  Grid:   ${grid_low:,.0f} - ${grid_high:,.0f}{' ' * max(0, 18 - len(f'${grid_low:,.0f} - ${grid_high:,.0f}'))}|")
        print(f"  +----------------------------------------------+{Style.RESET_ALL}")

    def shutdown_summary(self, total_pnl: float, total_cycles: int):
        """Print final summary on shutdown."""
        runtime = datetime.now() - self.start_time
        hours, remainder = divmod(int(runtime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        pnl_color = Fore.GREEN if total_pnl >= 0 else Fore.RED
        pnl_sign = "+" if total_pnl >= 0 else ""

        print()
        print(f"  {Fore.YELLOW + Style.BRIGHT}+====================================================+")
        print(f"  |              SHUTDOWN SUMMARY                      |")
        print(f"  +====================================================+")
        print(f"  |  Runtime:       {hours:02d}h {minutes:02d}m {seconds:02d}s                        |")
        print(f"  |  Total Trades:  {self.trade_count:<10}                       |")
        print(f"  |  Grid Cycles:   {total_cycles:<10}                       |")
        print(f"  |  Total PnL:     {pnl_color}{pnl_sign}${abs(total_pnl):<10,.2f}{Style.RESET_ALL}{Fore.YELLOW + Style.BRIGHT}                    |")
        print(f"  +====================================================+{Style.RESET_ALL}")
        print()

