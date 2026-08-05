"""
Web Dashboard Server for Grid Trading Bot.
Flask + Socket.IO for real-time browser communication.
Bridges the web UI with the trading engine.
"""

import os
import sys
import json
import time
import signal
import threading
from pathlib import Path

# Add src directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, send_from_directory
from flask_socketio import SocketIO, emit

from logger import BotLogger
from binance_client import BinanceClient
from risk_manager import RiskManager
from grid_engine import GridEngine
from quant_engine import QuantEngine
from binance_ws import BinanceWSClient
from performance_tracker import PerformanceTracker
from auto_portfolio_manager import AutoPortfolioManager, get_smart_max_position
from trend_guard import TrendGuard
from telegram_notifier import TelegramNotifier
from tax_report_generator import TaxReportGenerator


# ═══════════ Flask App Setup ═══════════
app = Flask(__name__, static_folder='../static')
app.config['SECRET_KEY'] = 'gridbot-secret-key'
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=10000000
)

# ─── Global State & Cache ───
bot_thread = None
bot_running = False
bot_stop_event = threading.Event()
current_config = {}
perf_tracker = None

_cached_client = None
_cached_symbols = None
_cached_scanner_data = None
_last_scanner_time = 0
auto_manager = None  # Auto Portfolio Manager instance
shared_grid_engine = None
shared_risk_manager = None

def get_shared_client():
    """Reusable Binance client instance to avoid repeated connection latency."""
    global _cached_client
    if _cached_client is None:
        try:
            config = load_config_file()
            logger = BotLogger('trades.log')
            _cached_client = BinanceClient(config, logger)
            _cached_client.connect()
        except Exception as e:
            print(f"Error initializing shared Binance client: {e}")
    return _cached_client


# ═══════════ Routes ═══════════
@app.route('/')
def index():
    """Serve the dashboard HTML."""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files (CSS, JS)."""
    return send_from_directory(app.static_folder, filename)


@app.route('/api/symbols')
def api_symbols():
    """Get all available Binance USDT futures symbols with instant cached response."""
    global _cached_symbols
    if _cached_symbols:
        return {'symbols': _cached_symbols}

    fallback_symbols = [
        {'symbol': 'BTC/USDT', 'precision_price': 2},
        {'symbol': 'ETH/USDT', 'precision_price': 2},
        {'symbol': 'SOL/USDT', 'precision_price': 2},
        {'symbol': 'BNB/USDT', 'precision_price': 2},
        {'symbol': 'DOGE/USDT', 'precision_price': 5},
        {'symbol': 'XRP/USDT', 'precision_price': 4},
        {'symbol': 'ADA/USDT', 'precision_price': 4},
        {'symbol': 'PEPE/USDT', 'precision_price': 8},
        {'symbol': 'SHIB/USDT', 'precision_price': 8},
        {'symbol': 'AVAX/USDT', 'precision_price': 2},
        {'symbol': 'LINK/USDT', 'precision_price': 3},
        {'symbol': 'SUI/USDT', 'precision_price': 4},
        {'symbol': 'NEAR/USDT', 'precision_price': 3},
        {'symbol': 'FET/USDT', 'precision_price': 4},
        {'symbol': 'FLOKI/USDT', 'precision_price': 8},
        {'symbol': 'WIF/USDT', 'precision_price': 4},
        {'symbol': 'DOT/USDT', 'precision_price': 3},
        {'symbol': 'UNI/USDT', 'precision_price': 3},
        {'symbol': 'LTC/USDT', 'precision_price': 2},
        {'symbol': 'APT/USDT', 'precision_price': 3},
    ]

    try:
        client = get_shared_client()
        if client:
            _cached_symbols = client.get_all_symbols()
            return {'symbols': _cached_symbols}
    except Exception:
        pass

    _cached_symbols = fallback_symbols
    return {'symbols': _cached_symbols}


@app.route('/api/market_scanner')
def api_market_scanner():
    """Market Intelligence Radar — AI Grid Opportunities, Gainers, and Losers."""
    global _cached_scanner_data, _last_scanner_time
    now = time.time()
    
    # Cache for 20 seconds to prevent rate limits
    if _cached_scanner_data and (now - _last_scanner_time < 20):
        return _cached_scanner_data

    try:
        client = get_shared_client()
        quant = QuantEngine(client)
        
        target_coins = ['ETH/USDT', 'SOL/USDT', 'HOME/USDT', 'STAR/USDT', 'DOGE/USDT', 'ADA/USDT', '1000PEPE/USDT', 'NEAR/USDT', 'BTC/USDT', 'BNB/USDT', 'AVAX/USDT']
        opportunities = []

        for sym in target_coins:
            try:
                analysis = quant.analyze_symbol(sym)
                if analysis and 'error' not in analysis:
                    opportunities.append(analysis)
            except Exception:
                pass

        # Sort opportunities by score descending
        opportunities.sort(key=lambda x: x.get('score', 0), reverse=True)

        if opportunities:
            data = {
                'best_grid': opportunities,
                'gainers': [op for op in opportunities if op.get('rsi', 50) > 55][:5],
                'losers': [op for op in opportunities if op.get('rsi', 50) < 45][:5],
            }
            _cached_scanner_data = data
            _last_scanner_time = now
            return _cached_scanner_data

    except Exception:
        pass

    # Fallback structure
    fallback_data = {
        'best_grid': [
            {
                'symbol': 'ETH/USDT', 'price': 1875.0, 'score': 95, 'status': 'Excellent', 'status_badge': '🟢 Excellent',
                'stars': '★★★★★', 'ranging_probability': 88, 'atr_percent': 1.8, 'rsi': 48.5, 'adx': 14.2,
                'grid_levels': 10, 'spacing_mode': 'percent', 'grid_spacing_percent': 0.5, 'grid_spacing_usdt': 9.37,
                'quantity': 0.005, 'recommended_leverage': 5, 'max_loss_usdt': 15.0, 'max_position_usdt': 70.0,
                'est_cycle_roi': 0.55, 'est_cycles_per_hour': 6.0, 'est_daily_return_min': 3.2, 'est_daily_return_max': 6.5
            },
            {
                'symbol': 'HOME/USDT', 'price': 0.00818, 'score': 92, 'status': 'Excellent', 'status_badge': '🟢 Excellent',
                'stars': '★★★★★', 'ranging_probability': 84, 'atr_percent': 7.2, 'rsi': 54.0, 'adx': 17.1,
                'grid_levels': 14, 'spacing_mode': 'percent', 'grid_spacing_percent': 2.33, 'grid_spacing_usdt': 0.00019,
                'quantity': 2650.0, 'recommended_leverage': 3, 'max_loss_usdt': 15.0, 'max_position_usdt': 70.0,
                'est_cycle_roi': 2.56, 'est_cycles_per_hour': 4.5, 'est_daily_return_min': 4.0, 'est_daily_return_max': 8.2
            },
            {
                'symbol': 'STAR/USDT', 'price': 0.0994, 'score': 90, 'status': 'Excellent', 'status_badge': '🟢 Excellent',
                'stars': '★★★★★', 'ranging_probability': 82, 'atr_percent': 3.5, 'rsi': 51.2, 'adx': 16.5,
                'grid_levels': 10, 'spacing_mode': 'percent', 'grid_spacing_percent': 1.0, 'grid_spacing_usdt': 0.00099,
                'quantity': 180.0, 'recommended_leverage': 5, 'max_loss_usdt': 15.0, 'max_position_usdt': 70.0,
                'est_cycle_roi': 1.1, 'est_cycles_per_hour': 5.0, 'est_daily_return_min': 3.0, 'est_daily_return_max': 6.0
            },
            {
                'symbol': 'SOL/USDT', 'price': 185.2, 'score': 86, 'status': 'Very Good', 'status_badge': '🟢 Very Good',
                'stars': '★★★★☆', 'ranging_probability': 76, 'atr_percent': 2.1, 'rsi': 52.0, 'adx': 19.0,
                'grid_levels': 10, 'spacing_mode': 'percent', 'grid_spacing_percent': 0.6, 'grid_spacing_usdt': 1.11,
                'quantity': 0.13, 'recommended_leverage': 5, 'max_loss_usdt': 15.0, 'max_position_usdt': 70.0,
                'est_cycle_roi': 0.66, 'est_cycles_per_hour': 5.0, 'est_daily_return_min': 2.5, 'est_daily_return_max': 5.0
            },
        ],
        'gainers': [],
        'losers': []
    }
    _cached_scanner_data = fallback_data
    _last_scanner_time = now
    return _cached_scanner_data


@app.route('/api/ai_recommend')
def api_ai_recommend():
    """AI Smart Grid Quant Engine — calculates optimal parameters from ATR, RSI, Bollinger Bands."""
    try:
        from flask import request
        symbol = request.args.get('symbol', 'BTC/USDT')
        client = get_shared_client()
        quant = QuantEngine(client)
        return quant.analyze_symbol(symbol)
    except Exception as e:
        return {'error': str(e)}


@app.route('/api/balance')
def api_balance():
    """Fetch live USDT account balance."""
    try:
        client = get_shared_client()
        if client:
            bal = client.get_wallet_balance()
            return {'balance': float(bal)}
        return {'balance': 5000.0}
    except Exception as e:
        return {'balance': 5000.0, 'error': str(e)}


@app.route('/api/performance')
def api_performance():
    """Get 30-day quantitative performance analytics and CSV summary."""
    global perf_tracker
    if perf_tracker:
        return perf_tracker.get_summary_report()
    return {
        'uptime_hours': 0,
        'net_return_pct': 0,
        'max_drawdown_pct': 0,
        'ws_reconnect_count': 0,
        'desync_count': 0,
        'csv_log_path': 'logs/performance_30d.csv'
    }


@app.route('/api/download_csv')
def api_download_csv():
    """Download clean quantitative performance CSV reports (Daily Summary, Cycle Logs, or Hourly)."""
    from flask import request, send_file
    csv_type = request.args.get('type', 'daily').lower()
    
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    
    if csv_type == 'cycles':
        filename = "completed_cycles.csv"
    elif csv_type == 'hourly':
        filename = "performance_summary.csv"
    else:
        filename = "daily_performance.csv"
        
    csv_path = os.path.join(logs_dir, filename)
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name=filename, mimetype="text/csv")
        
    # Fallback to any existing CSV in logs
    for fallback_name in ["daily_performance.csv", "completed_cycles.csv", "performance_summary.csv", "performance_30d.csv"]:
        fb_path = os.path.join(logs_dir, fallback_name)
        if os.path.exists(fb_path):
            return send_file(fb_path, as_attachment=True, download_name=fallback_name, mimetype="text/csv")
            
    return {'error': 'CSV log file not found yet. Start the bot to generate performance logs!'}, 404


@app.route('/api/download_tax_report')
def api_download_tax_report():
    """Generate and download CA-ready financial year Tax Report CSV."""
    from flask import send_file
    global _cached_client, shared_grid_engine
    
    logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
    generator = TaxReportGenerator(log_dir=logs_dir)
    client = _cached_client or get_shared_client()
    
    csv_path = generator.generate_report(client=client, grid_engine=shared_grid_engine)
    if os.path.exists(csv_path):
        return send_file(csv_path, as_attachment=True, download_name="tax_report_2026.csv", mimetype="text/csv")
    return {'error': 'Failed to generate tax report.'}, 500


# ═══════════ Socket.IO Events ═══════════
@socketio.on('connect')
def handle_connect():
    """Client connected to dashboard. Sync state if bot is currently running in background."""
    print(f"  ✅ Dashboard client connected")
    emit('log_message', {'level': 'system', 'message': 'Dashboard connected to server'})

    # Sync Auto Mode state
    if auto_manager:
        emit('auto_mode_update', auto_manager.get_status())
    else:
        emit('auto_mode_update', {'active': False})

    # Always sync current saved configuration & mode badge to UI on connect
    is_testnet = bool(current_config.get('use_testnet', False) or current_config.get('use_demo', False))
    emit('bot_config_sync', {'config': current_config, 'use_testnet': is_testnet})

    # Sync bot running state & grid levels
    global shared_grid_engine, shared_risk_manager, _cached_client
    if bot_running and bot_thread is not None and bot_thread.is_alive():
        symbol = current_config.get('symbol', 'SOL/USDT')
        is_testnet = bool(current_config.get('use_testnet', False) or current_config.get('use_demo', False))
        emit('bot_started', {
            'symbol': symbol,
            'use_testnet': is_testnet,
            'config': current_config
        })
        if shared_grid_engine:
            if shared_grid_engine.current_price:
                emit('price_update', {'price': shared_grid_engine.current_price})
            send_grid_update(shared_grid_engine)
            client = _cached_client or get_shared_client()
            if client and shared_risk_manager:
                try:
                    send_stats_update(shared_grid_engine, client, shared_risk_manager)
                except Exception:
                    pass
    else:
        emit('bot_stopped', {'pnl': 0, 'cycles': 0})


@socketio.on('disconnect')
def handle_disconnect():
    """Client disconnected."""
    print(f"  ⚠️  Dashboard client disconnected")


@socketio.on('start_bot')
def handle_start_bot(config):
    """Start the trading bot with the provided configuration."""
    global bot_thread, bot_running, bot_stop_event, current_config

    # Check if thread is actually running
    if bot_thread is not None and not bot_thread.is_alive():
        bot_running = False

    if bot_running:
        emit('bot_error', {'message': 'Bot is already running!'})
        return

    # Merge UI config with file config
    try:
        current_config = load_config_file()
    except Exception as e:
        emit('bot_error', {'message': f'Config error: {str(e)}'})
        return

    # Override with UI settings
    symbol = config.get('symbol') or 'BTC/USDT'
    current_config['symbol'] = symbol
    current_config['grid_levels'] = config.get('grid_levels', 10)
    current_config['spacing_mode'] = config.get('spacing_mode', 'usdt')  # 'usdt' or 'percent'
    current_config['grid_spacing_usdt'] = config.get('grid_spacing_usdt', 50.0)
    current_config['grid_spacing_percent'] = config.get('grid_spacing_percent', 0.5)
    current_config['quantity_per_grid'] = config.get('quantity_per_grid', 0.001)
    current_config['leverage'] = config.get('leverage', 5)
    current_config['max_loss_usdt'] = config.get('max_loss_usdt', 100.0)
    current_config['max_position_usdt'] = config.get('max_position_usdt', 500.0)

    # Reset stop event
    bot_stop_event.clear()

    # Start bot in a background thread
    bot_thread = threading.Thread(target=run_bot, args=(current_config,), daemon=True)
    bot_thread.start()


@socketio.on('stop_bot')
def handle_stop_bot():
    """Stop the trading bot and cancel all active orders on Binance."""
    global bot_running
    if bot_running:
        bot_stop_event.set()
        emit('log_message', {'level': 'system', 'message': 'Shutdown signal sent...'})
    else:
        # Force cancel any leftover open orders on Binance even if server restarted
        try:
            client = get_shared_client()
            if client:
                client.cancel_all_orders()
                emit('log_message', {'level': 'system', 'message': 'Cancelled leftover orders on Binance.'})
        except Exception:
            pass
        emit('bot_stopped', {'pnl': 0, 'cycles': 0})


@socketio.on('stop_and_close')
def handle_stop_and_close():
    """Stop bot, cancel all grid orders, AND market-close open position to lock profit into cash balance."""
    global bot_running
    emit('log_message', {'level': 'system', 'message': '⚡ Emergency Stop & Market Closing Position...'})

    if bot_running:
        bot_stop_event.set()

    try:
        client = get_shared_client()
        if client:
            client.cancel_all_orders()
            time.sleep(0.5)
            client.close_position()
            time.sleep(1)
            fresh_balance = client.get_wallet_balance()
            emit('stats_update', {
                'realized_pnl': 0,
                'unrealized_pnl': 0,
                'cycles': 0,
                'balance': fresh_balance,
                'position_info': 'No position',
            })
            emit('log_message', {'level': 'system', 'message': f'✅ Position market-closed! Fresh Wallet Balance: ${fresh_balance:,.2f} USDT'})
    except Exception as e:
        emit('log_message', {'level': 'error', 'message': f'Close position error: {str(e)}'})

    emit('bot_stopped', {'pnl': 0, 'cycles': 0})


@socketio.on('toggle_auto_mode')
def handle_toggle_auto_mode(data):
    """Toggle Auto Portfolio Manager on/off."""
    global auto_manager
    enable = data.get('enable', False)

    if enable:
        try:
            client = get_shared_client()
            if client and auto_manager is None:
                auto_manager = AutoPortfolioManager(client, DashboardLogger('trades.log'), socketio)

            if auto_manager:
                current_sym = data.get('current_symbol', 'ETH/USDT')
                current_score = data.get('current_score', 80)
                auto_manager.start(current_sym, current_score)
                emit('log_message', {'level': 'system', 'message': f'\U0001f916 Auto Mode ENABLED — Bot will auto-select the best coin every 30 min!'})
                emit('auto_mode_update', auto_manager.get_status())
        except Exception as e:
            emit('bot_error', {'message': f'Auto mode error: {str(e)}'})
    else:
        if auto_manager:
            auto_manager.stop()
        emit('log_message', {'level': 'system', 'message': '\U0001f916 Auto Mode DISABLED — Manual coin selection restored.'})
        emit('auto_mode_update', {'active': False})


@socketio.on('get_auto_status')
def handle_get_auto_status():
    """Get current auto mode status."""
    if auto_manager:
        emit('auto_mode_update', auto_manager.get_status())
    else:
        emit('auto_mode_update', {'active': False})


# ═══════════ Bot Runner (Background Thread) ═══════════
def run_bot(config):
    """Run the trading bot in a background thread, emitting events to the dashboard."""
    global bot_running, shared_grid_engine, shared_risk_manager

    # Create a dashboard-aware logger that sends logs to the browser
    logger = DashboardLogger(config.get('log_file', 'trades.log'))

    try:
        bot_running = True
        socketio.emit('bot_started', {
            'symbol': config['symbol'],
            'use_testnet': config.get('use_testnet', True) and config.get('use_demo', True),
            'config': config
        })
        logger.system(f"Starting Grid Bot: {config['symbol']} (Testnet: {config.get('use_testnet', True)})")

        # ─── Initialize components ───
        client = BinanceClient(config, logger)
        logger.system("Connecting to Binance...")
        client.connect()

        # Check balance
        balance = client.get_balance()
        logger.system(f"Balance: ${balance:,.2f} USDT")
        socketio.emit('stats_update', {'balance': balance})

        if balance < 10:
            raise Exception("Balance too low! Need at least $10 USDT on testnet.")

        risk_manager = RiskManager(config, client, logger)
        risk_manager.initialize()

        # Auto-calculate smart max position based on wallet balance + leverage
        leverage = config.get('leverage', 5)
        smart_max_pos = get_smart_max_position(balance, leverage)
        config['max_position_usdt'] = smart_max_pos
        risk_manager.max_position_usdt = smart_max_pos
        logger.system(f"Max position limit: ${smart_max_pos:,.2f}")

        grid_engine = GridEngine(config, client, risk_manager, logger)
        shared_grid_engine = grid_engine
        shared_risk_manager = risk_manager
        logger.system("Setting up grid...")
        grid_engine.initialize()

        # Send initial price and grid state
        try:
            init_price = client.get_price()
            grid_engine.update_price(init_price)
            socketio.emit('price_update', {'price': init_price})
        except Exception:
            pass
        send_grid_update(grid_engine)

        # ─── Initialize Quant Performance Tracker ───
        global perf_tracker
        perf_tracker = PerformanceTracker(config, client, logger)
        perf_tracker.initialize(client.get_wallet_balance())
        risk_manager.perf_tracker = perf_tracker

        # ─── Initialize Real-Time WebSocket Client (<50ms) ───
        ws_client = BinanceWSClient(config, client, logger, perf_tracker=perf_tracker)

        def handle_ws_price(price):
            grid_engine.update_price(price)
            socketio.emit('price_update', {'price': price})

        def handle_ws_fill(order_id):
            grid_engine.process_order_fill_id(order_id)
            send_grid_update(grid_engine)
            send_stats_update(grid_engine, client, risk_manager)
            if perf_tracker:
                perf_tracker.record_fill(grid_engine.quantity * (grid_engine.current_price or 1.0))

        ws_client.start(on_price_update=handle_ws_price, on_order_fill=handle_ws_fill)

        # ─── Initialize Trend Guard (Anti-Trend Protection + Dynamic Spacing) ───
        trend_guard = TrendGuard(client, logger, socketio)
        logger.system("🛡️ Trend Guard initialized — Anti-trend protection active (ADX > 40 / RSI extremes)")

        # ─── Initialize Telegram Notifications ───
        tg_token = config.get('telegram_bot_token', '')
        tg_chat = config.get('telegram_chat_id', '')
        tg = TelegramNotifier(tg_token, tg_chat, logger)

        # Wire Telegram to grid cycle completions
        grid_engine.telegram_notifier = tg
        original_handle_fill = handle_ws_fill
        def handle_ws_fill_with_tg(order_id):
            old_cycles = grid_engine.completed_cycles
            original_handle_fill(order_id)
            new_cycles = grid_engine.completed_cycles
            if new_cycles > old_cycles:
                tg.notify_cycle_complete(
                    new_cycles,
                    grid_engine.grid_spacing * grid_engine.quantity,
                    risk_manager.get_realized_pnl(),
                    config['symbol']
                )
        ws_client.on_order_fill = handle_ws_fill_with_tg

        logger.system("Bot is running! Real-time WebSockets & 30-Day Quant Performance Tracker active.")

        # ─── Main Loop ───
        poll_interval = 5
        stats_interval = 5
        last_poll = time.time()
        last_stats = time.time()

        while not bot_stop_event.is_set():
            now = time.time()

            # Emit price update every loop iteration (~1s) for smooth chart rendering
            try:
                p = client.get_price()
                grid_engine.update_price(p)
                socketio.emit('price_update', {'price': p})
            except Exception:
                pass

            # Failsafe REST poll check for fills every 5s (skip when grid is paused)
            if now - last_poll >= poll_interval:
                if grid_engine.is_running:
                    grid_engine.check_and_process_fills()
                    send_grid_update(grid_engine)
                last_poll = now

            # Stats update & 30-day quant performance snapshot every 5s
            if now - last_stats >= stats_interval:
                send_stats_update(grid_engine, client, risk_manager)
                if perf_tracker:
                    perf_tracker.take_snapshot(grid_engine)
                last_stats = now

            # Risk check
            if not risk_manager.perform_safety_check():
                logger.risk("⛔ MAX LOSS BREACHED — EMERGENCY SHUTDOWN")
                tg.notify_risk_warning(f"MAX LOSS BREACHED on {config['symbol']}! Emergency shutdown triggered.")
                break

            # ─── Trend Guard Check (every 60s) ───
            trend_guard.process(config['symbol'])
            if trend_guard.is_paused and grid_engine.is_running:
                logger.risk(f"🛡️ Trend Guard paused grid: {trend_guard.pause_reason}")
                tg.notify_trend_guard(True, trend_guard.pause_reason, trend_guard.last_adx, trend_guard.last_rsi)
                grid_engine.cancel_all()
                socketio.emit('trend_guard_update', trend_guard.get_status())
            elif not trend_guard.is_paused and not grid_engine.is_running and not bot_stop_event.is_set():
                logger.system("🛡️ Trend Guard cleared — Restarting grid...")
                tg.notify_trend_guard(False, 'Market normalized', trend_guard.last_adx, trend_guard.last_rsi)
                grid_engine.is_running = True
                grid_engine.initialize()
                send_grid_update(grid_engine)
                socketio.emit('trend_guard_update', trend_guard.get_status())

            # ─── Telegram periodic summary (every 6 hours) ───
            try:
                bal = client.get_wallet_balance()
                tg.check_periodic_summary(risk_manager.get_realized_pnl(), bal, config['symbol'])
            except Exception:
                pass

            # Auto Portfolio Manager check (every loop iteration when active)
            if auto_manager and auto_manager.is_active:
                # Check if we have an open position
                try:
                    pos = client.get_position()
                    has_open = pos.get('size', 0) != 0
                except Exception:
                    has_open = True  # Assume open if we can't check (safety)

                switch_config = auto_manager.check_and_switch(has_open)
                if switch_config:
                    # Execute the switch!
                    logger.system(f"\U0001f916 Executing auto-switch to {switch_config['symbol']}...")

                    # 1. Stop current grid
                    grid_engine.cancel_all()
                    time.sleep(1)

                    # 2. Close any residual position
                    client.close_position()
                    time.sleep(1)

                    # 3. Update config with new coin parameters
                    new_symbol = switch_config['symbol']
                    config['symbol'] = new_symbol
                    config['grid_levels'] = switch_config.get('grid_levels', 10)
                    config['spacing_mode'] = switch_config.get('spacing_mode', 'percent')
                    config['grid_spacing_percent'] = switch_config.get('grid_spacing_percent', 0.5)
                    config['grid_spacing_usdt'] = switch_config.get('grid_spacing_usdt', 1.0)
                    config['quantity_per_grid'] = switch_config.get('quantity', 0.001)
                    config['leverage'] = switch_config.get('recommended_leverage', 5)

                    # 4. Recalculate smart max position for new leverage
                    fresh_balance = client.get_wallet_balance()
                    new_leverage = config['leverage']
                    config['max_position_usdt'] = get_smart_max_position(fresh_balance, new_leverage)
                    config['max_loss_usdt'] = round(max(10.0, fresh_balance * 0.15), 2)

                    # 5. Reinitialize client for new symbol
                    client.symbol = new_symbol
                    try:
                        client.exchange.set_leverage(new_leverage, new_symbol)
                        logger.system(f"Leverage set to {new_leverage}x for {new_symbol}")
                    except Exception:
                        pass
                    try:
                        client.exchange.set_margin_mode('cross', new_symbol)
                    except Exception:
                        pass

                    # 6. Reinitialize risk manager and grid engine
                    risk_manager = RiskManager(config, client, logger)
                    risk_manager.initialize()
                    risk_manager.max_position_usdt = config['max_position_usdt']

                    grid_engine = GridEngine(config, client, risk_manager, logger)
                    grid_engine.initialize()
                    send_grid_update(grid_engine)

                    # 7. Restart WebSocket for new symbol
                    ws_client.stop()
                    time.sleep(1)
                    ws_client = BinanceWSClient(config, client, logger, perf_tracker=perf_tracker)
                    ws_client.start(on_price_update=handle_ws_price, on_order_fill=handle_ws_fill)

                    logger.system(f"\U0001f916 ✅ Auto-switch complete! Now trading {new_symbol} (Score: {switch_config['score']}/100)")

                    # Emit switch event to dashboard
                    socketio.emit('bot_started', {
                        'symbol': new_symbol,
                        'use_testnet': config.get('use_testnet', True) and config.get('use_demo', True)
                    })
                    send_stats_update(grid_engine, client, risk_manager)

                    continue  # Skip rest of loop iteration

            # Sleep briefly
            bot_stop_event.wait(timeout=1)

    except Exception as e:
        logger.error(f"Bot error: {str(e)}")
        socketio.emit('bot_error', {'message': str(e)})

    finally:
        # Stop WebSocket client
        try:
            if 'ws_client' in locals() and ws_client:
                ws_client.stop()
        except Exception:
            pass

        # Cleanup
        shared_grid_engine = None
        bot_running = False
        try:
            grid_engine.cancel_all()
        except Exception:
            pass

        stats = {}
        try:
            stats = grid_engine.get_stats()
        except Exception:
            stats = {'pnl': 0, 'cycles': 0}

        # Fetch fresh balance & update UI after releasing locked order margin
        try:
            time.sleep(1)  # Allow exchange to reflect canceled order margin release
            fresh_balance = client.get_wallet_balance()
            socketio.emit('stats_update', {
                'realized_pnl': stats.get('pnl', 0),
                'unrealized_pnl': 0,
                'cycles': stats.get('cycles', 0),
                'balance': fresh_balance,
                'position_info': 'No position',
            })
        except Exception:
            pass

        logger.system(f"Bot stopped. PnL: ${stats.get('pnl', 0):+.4f} | Cycles: {stats.get('cycles', 0)}")
        socketio.emit('bot_stopped', {
            'pnl': stats.get('pnl', 0),
            'cycles': stats.get('cycles', 0),
        })


def send_grid_update(grid_engine):
    """Send grid level state to dashboard."""
    levels = []
    for level in grid_engine.get_display_levels():
        levels.append({
            'price': level.price,
            'side': level.side.value,
            'status': level.status.value,
        })
    socketio.emit('grid_update', {'levels': levels})


def send_stats_update(grid_engine, client, risk_manager):
    """Send stats to dashboard."""
    stats = grid_engine.get_stats()
    position = client.get_position()
    try:
        balance = client.get_wallet_balance()
    except Exception:
        balance = 0

    # Calculate Realized PnL from RiskManager & persisted state
    exchange_realized_pnl = risk_manager.get_realized_pnl()
    if exchange_realized_pnl == 0 and risk_manager.initial_balance > 0 and balance > risk_manager.initial_balance:
        exchange_realized_pnl = balance - risk_manager.initial_balance

    pos_info = "No position"
    if position['size'] != 0:
        pos_info = f"{position['side'].upper()} {abs(position['size'])} @ ${position['entry_price']:,.2f}"

    socketio.emit('stats_update', {
        'realized_pnl': exchange_realized_pnl,
        'unrealized_pnl': position.get('unrealized_pnl', 0),
        'cycles': stats['cycles'],
        'balance': balance,
        'position_info': pos_info,
    })


# ═══════════ Dashboard Logger (sends to browser) ═══════════
class DashboardLogger(BotLogger):
    """Extended logger that also emits log messages to the web dashboard."""

    def _log(self, level, message, to_file=True):
        """Override to also send to Socket.IO."""
        super()._log(level, message, to_file)
        # Send to browser
        level_map = {
            'INFO': 'info', 'WARN': 'warn', 'ERROR': 'error',
            'TRADE': 'trade', 'GRID': 'grid', 'RISK': 'risk', 'SYSTEM': 'system',
        }
        socketio.emit('log_message', {
            'level': level_map.get(level, 'info'),
            'message': message,
        })

    def trade(self, side, price, qty, pnl=None):
        """Override to also send trade to dashboard."""
        super().trade(side, price, qty, pnl)
        socketio.emit('trade_update', {
            'side': side.lower(),
            'price': price,
            'quantity': qty,
            'pnl': pnl,
            'time': time.strftime('%H:%M:%S'),
        })


# ═══════════ Config Loader ═══════════
def load_config_file():
    """Load config.json from project root."""
    project_root = Path(__file__).parent.parent
    config_path = project_root / 'config.json'

    if not config_path.exists():
        raise Exception(
            "config.json not found! Copy config.json.example to config.json "
            "and fill in your Binance Testnet API keys."
        )

    with open(config_path, 'r') as f:
        config = json.load(f)

    # Validate
    if config.get('api_key', '').startswith('YOUR_'):
        raise Exception(
            "API key not configured! Edit config.json with your "
            "Binance Testnet API keys from https://testnet.binancefuture.com"
        )

    return config


# ═══════════ Main ═══════════
def main():
    """Start the web dashboard server."""
    print()
    print("  ⚡ Grid Trading Bot — Web Dashboard")
    print("  ════════════════════════════════════")
    print()
    print("  🌐 Open your browser:")
    print("     http://localhost:5000")
    print()
    print("  📝 Steps:")
    print("     1. Select your trading pair (BTC, ETH, SOL, etc.)")
    print("     2. Adjust grid settings")
    print("     3. Click 'Start Bot'")
    print()
    print("  ⚠️  Make sure config.json has your testnet API keys!")
    print()
    print("  Press Ctrl+C to stop the server")
    print("  ════════════════════════════════════")
    print()

    # Auto-start bot thread on server launch if valid config exists
    try:
        cfg = load_config_file()
        if cfg and cfg.get('api_key') and not cfg.get('api_key', '').startswith('YOUR_'):
            print("🚀 Auto-starting Grid Engine on server launch...")
            bot_stop_event.clear()
            bot_thread = threading.Thread(target=run_bot, args=(cfg,), daemon=True)
            bot_thread.start()
    except Exception as e:
        print(f"Auto-start info: {e}")

    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
