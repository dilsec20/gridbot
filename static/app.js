/* ═══════════════════════════════════════════════════
   Grid Trading Bot — Dashboard JavaScript
   Real-time WebSocket communication & UI updates
   ═══════════════════════════════════════════════════ */

// ─── State ───
let socket = null;
let botRunning = false;
let priceHistory = [];
let gridLevels = [];
let trades = [];
let radarData = null;
let activeRadarTab = 'best_grid';
const MAX_PRICE_POINTS = 120;

// ─── Initialize ───
document.addEventListener('DOMContentLoaded', () => {
    connectSocket();
    startClock();
    setupChart();
    loadSymbols();
    toggleSpacingMode();
    loadMarketRadar();
    fetchInitialBalance();
    setInterval(loadMarketRadar, 30000); // Refresh scanner every 30s
});

async function fetchInitialBalance() {
    try {
        const res = await fetch('/api/balance');
        const data = await res.json();
        if (data.balance) {
            document.getElementById('balance').textContent = `$${data.balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
        }
    } catch (e) {
        console.log('Failed to fetch initial balance:', e);
    }
}

// ═══════════ SOCKET CONNECTION ═══════════
function connectSocket() {
    socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionDelay: 500,
        reconnectionDelayMax: 2000,
        reconnectionAttempts: Infinity,
        timeout: 30000
    });

    socket.on('connect', () => {
        updateConnectionStatus(true);
        addLog('system', 'Connected to bot server');
    });

    socket.on('disconnect', () => {
        updateConnectionStatus(false);
        addLog('warn', 'Disconnected from bot server');
    });

    // ─── Event Handlers ───
    socket.on('price_update', handlePriceUpdate);
    socket.on('grid_update', handleGridUpdate);
    socket.on('trade_update', handleTradeUpdate);
    socket.on('stats_update', handleStatsUpdate);
    socket.on('log_message', handleLogMessage);
    socket.on('bot_started', handleBotStarted);
    socket.on('bot_stopped', handleBotStopped);
    socket.on('bot_error', handleBotError);
    socket.on('bot_config_sync', function(data) {
        if (data) {
            if (data.config) populateFormConfig(data.config);
            const modeLabel = document.getElementById('modeLabel');
            if (modeLabel && data.use_testnet !== undefined) {
                if (!data.use_testnet) {
                    modeLabel.textContent = 'REAL MONEY LIVE';
                    modeLabel.className = 'badge badge-live';
                } else {
                    modeLabel.textContent = 'TESTNET';
                    modeLabel.className = 'badge badge-testnet';
                }
            }
        }
    });
}

function populateFormConfig(c) {
    if (!c) return;
    if (c.symbol) {
        const select = document.getElementById('symbolSelect');
        if (select) {
            if (!Array.from(select.options).some(opt => opt.value === c.symbol)) {
                const opt = document.createElement('option');
                opt.value = c.symbol;
                opt.textContent = c.symbol;
                select.appendChild(opt);
            }
            select.value = c.symbol;
        }
    }
    if (c.grid_levels && document.getElementById('gridLevels')) document.getElementById('gridLevels').value = c.grid_levels;
    if (c.spacing_mode && document.getElementById('spacingMode')) document.getElementById('spacingMode').value = c.spacing_mode;
    if (c.grid_spacing_percent !== undefined && document.getElementById('gridSpacingPercent')) document.getElementById('gridSpacingPercent').value = c.grid_spacing_percent;
    if (c.grid_spacing_usdt !== undefined && document.getElementById('gridSpacing')) document.getElementById('gridSpacing').value = c.grid_spacing_usdt;
    if (c.quantity_per_grid !== undefined && document.getElementById('gridQuantity')) document.getElementById('gridQuantity').value = c.quantity_per_grid;
    if (c.leverage !== undefined && document.getElementById('leverage')) document.getElementById('leverage').value = c.leverage;
    
    const maxLossEl = document.getElementById('maxLoss') || document.getElementById('maxLossUsdt');
    if (maxLossEl && c.max_loss_usdt !== undefined) maxLossEl.value = c.max_loss_usdt;
    
    const maxPosEl = document.getElementById('maxPosition') || document.getElementById('maxPositionUsdt');
    if (maxPosEl && c.max_position_usdt !== undefined) maxPosEl.value = c.max_position_usdt;
    
    if (c.trailing_tp_enabled !== undefined && document.getElementById('tpModeSelect')) {
        document.getElementById('tpModeSelect').value = c.trailing_tp_enabled ? 'trailing' : 'fixed';
    }
    if (c.trailing_tp_callback_percent !== undefined && document.getElementById('trailingCallback')) {
        document.getElementById('trailingCallback').value = c.trailing_tp_callback_percent;
    }
    toggleTpMode();

    toggleSpacingMode();
    if (typeof updateCalculatedMetrics === 'function') {
        updateCalculatedMetrics();
    }
}

function toggleTpMode() {
    const select = document.getElementById('tpModeSelect');
    const group = document.getElementById('trailingCallbackGroup');
    if (select && group) {
        group.style.display = select.value === 'trailing' ? 'block' : 'none';
    }
}

function updateConnectionStatus(connected) {
    const el = document.getElementById('connectionStatus');
    if (!el) return;
    const dot = el.querySelector('.status-dot');
    const text = el.querySelector('span:last-child');

    if (dot) dot.className = `status-dot ${connected ? 'connected' : 'disconnected'}`;
    if (text) text.textContent = connected ? 'Connected' : 'Disconnected';
}

// ═══════════ SYMBOLS & SPACING MODES ═══════════
function toggleSpacingMode() {
    const mode = document.getElementById('spacingMode').value;
    const usdtGroup = document.getElementById('spacingUsdtGroup');
    const percentGroup = document.getElementById('spacingPercentGroup');

    if (mode === 'percent') {
        usdtGroup.style.display = 'none';
        percentGroup.style.display = 'flex';
    } else {
        usdtGroup.style.display = 'flex';
        percentGroup.style.display = 'none';
    }
}

let allSymbolsList = [];

function onSymbolChange() {
    const symbol = document.getElementById('symbolSelect').value;
    addLog('system', `Selected symbol: ${symbol}`);
}

function filterSymbols() {
    const query = document.getElementById('symbolSearch').value.toUpperCase().trim();
    const select = document.getElementById('symbolSelect');
    if (!allSymbolsList || allSymbolsList.length === 0) return;

    const filtered = allSymbolsList.filter(s => s.symbol.toUpperCase().includes(query));
    if (filtered.length > 0) {
        select.innerHTML = filtered.map(s => `<option value="${s.symbol}">${s.symbol}</option>`).join('');
    } else {
        select.innerHTML = `<option value="">No matching coins found</option>`;
    }
}

async function loadSymbols() {
    try {
        const res = await fetch('/api/symbols');
        const data = await res.json();
        if (data.symbols && data.symbols.length > 0) {
            allSymbolsList = data.symbols;
            const select = document.getElementById('symbolSelect');
            const current = select.value;
            select.innerHTML = allSymbolsList.map(s => `
                <option value="${s.symbol}">${s.symbol}</option>
            `).join('');
            if (current) select.value = current;
        }
    } catch (e) {
        console.log('Failed to fetch symbols:', e);
    }
}

async function applyAiGrid() {
    const symbol = document.getElementById('symbolSelect').value;
    if (!symbol) return;
    addLog('system', `Calculating AI Smart Grid parameters for ${symbol}...`);
    try {
        const res = await fetch(`/api/ai_recommend?symbol=${encodeURIComponent(symbol)}`);
        const data = await res.json();
        if (data.error) {
            addLog('error', `AI Rec error: ${data.error}`);
            return;
        }

        document.getElementById('spacingMode').value = 'percent';
        toggleSpacingMode();

        document.getElementById('gridLevels').value = data.grid_levels || 10;
        document.getElementById('gridSpacingPercent').value = data.grid_spacing_percent || 0.5;
        document.getElementById('gridQuantity').value = data.quantity || 0.001;
        document.getElementById('leverage').value = data.recommended_leverage || 5;

        const maxLossEl = document.getElementById('maxLossUsdt') || document.getElementById('maxLoss');
        if (maxLossEl && data.max_loss_usdt) maxLossEl.value = data.max_loss_usdt;

        const maxPosEl = document.getElementById('maxPositionUsdt') || document.getElementById('maxPosition');
        if (maxPosEl && data.max_position_usdt) maxPosEl.value = data.max_position_usdt;

        if (data.price) {
            lastKnownPrice = data.price;
            document.getElementById('currentPrice').textContent = formatPrice(data.price);
        }
        updateMarginCalculator();

        // Update Quant Intelligence Card
        const quantCard = document.getElementById('quantCard');
        if (quantCard) {
            quantCard.style.display = 'block';
            document.getElementById('quantRegime').textContent = data.regime || 'Optimal Grid';
            document.getElementById('quantAtr').textContent = data.atr ? `$${data.atr} (${data.atr_percent}%)` : '--';
            document.getElementById('quantRsi').textContent = data.rsi !== undefined ? `${data.rsi}` : '--';
            document.getElementById('quantLev').textContent = `${data.recommended_leverage || 5}x`;
            document.getElementById('quantTpSl').textContent = `${formatPrice(data.suggested_tp)} / ${formatPrice(data.suggested_sl)}`;
            if (document.getElementById('quantBook')) {
                document.getElementById('quantBook').textContent = data.book_imbalance || 'Balanced (50% Buyers)';
            }
            if (document.getElementById('quantFunding')) {
                document.getElementById('quantFunding').textContent = data.funding_percent !== undefined ? `+${data.funding_percent}% (+${data.funding_apr}% APR)` : '--';
            }
        }

        addLog('system', `🧠 AI Quant Engine analyzed ${symbol}: RSI: ${data.rsi}, ATR: ${data.atr_percent}%, Book: ${data.book_imbalance || 'Balanced'}, Rec. Leverage: ${data.recommended_leverage}x, Spacing: ${data.grid_spacing_percent}%, Qty: ${data.quantity}`);
    } catch (e) {
        addLog('error', `Failed to get AI Grid parameters: ${e}`);
    }
}

// ═══════════ MARKET RADAR ═══════════
async function loadMarketRadar() {
    try {
        const res = await fetch('/api/market_scanner');
        radarData = await res.json();
        renderMarketRadar();
    } catch (e) {
        console.log('Failed to load market radar:', e);
    }
}

function switchRadarTab(tabKey, evt) {
    activeRadarTab = tabKey;
    const tabs = document.querySelectorAll('.radar-tab');
    tabs.forEach(t => t.classList.remove('active'));
    if (evt && evt.target) {
        evt.target.classList.add('active');
    }
    renderMarketRadar();
}

function renderMarketRadar() {
    const container = document.getElementById('radarCards');
    if (!radarData || !radarData[activeRadarTab]) {
        container.innerHTML = '<div class="radar-loading">Scanning Binance markets...</div>';
        return;
    }

    const coins = radarData[activeRadarTab];
    if (coins.length === 0) {
        container.innerHTML = '<div class="radar-loading">No market data available</div>';
        return;
    }

    container.innerHTML = coins.map(coin => {
        const score = coin.score || coin.grid_score || 85;
        const statusBadge = coin.status_badge || (score >= 90 ? '🟢 Excellent' : score >= 80 ? '🟢 Very Good' : '🟡 Good');
        const stars = coin.stars || '★★★★★';
        const atr = coin.atr_percent ? `${coin.atr_percent}%` : '2.1%';
        const rsi = coin.rsi !== undefined ? coin.rsi : 50;
        const adx = coin.adx !== undefined ? coin.adx : 18;
        const spacing = coin.grid_spacing_percent ? `${coin.grid_spacing_percent}%` : '0.5%';
        const dailyRoi = coin.est_daily_return_min ? `${coin.est_daily_return_min}% - ${coin.est_daily_return_max}%` : '3.0% - 6.0%';

        const encodedCoin = encodeURIComponent(JSON.stringify(coin));

        return `
            <div class="radar-card" onclick="selectCoinFromRadar('${coin.symbol}', '${encodedCoin}')" title="Click 1-Click Auto-Fill ${coin.symbol} AI Grid">
                <div class="card-top">
                    <span class="card-symbol">${coin.symbol.replace('/USDT', '')} <span class="card-stars">${stars}</span></span>
                    <span class="card-status-badge">${statusBadge}</span>
                </div>
                <div class="card-metrics">
                    <span>Score: <strong>${score}/100</strong></span>
                    <span>ATR: <strong>${atr}</strong></span>
                    <span>RSI: <strong>${rsi}</strong></span>
                    <span>ADX: <strong>${adx}</strong></span>
                </div>
                <div class="card-bottom">
                    <span class="card-price">${formatPrice(coin.price)}</span>
                    <span class="card-autofill-btn">⚡ 1-Click Apply (${spacing} / ${dailyRoi})</span>
                </div>
            </div>
        `;
    }).join('');
}

let activeCoinQuantData = null;

function selectCoinFromRadar(symbol, encodedCoinData) {
    let coinData = null;
    try {
        if (encodedCoinData) {
            coinData = JSON.parse(decodeURIComponent(encodedCoinData));
            activeCoinQuantData = coinData;
        }
    } catch (e) {}

    const select = document.getElementById('symbolSelect');

    // Add option if not present
    let exists = false;
    for (let option of select.options) {
        if (option.value === symbol) {
            exists = true;
            break;
        }
    }
    if (!exists) {
        const opt = document.createElement('option');
        opt.value = symbol;
        opt.textContent = symbol;
        select.prepend(opt);
    }

    select.value = symbol;

    if (coinData) {
        // Auto-fill all inputs instantly from AI Grid Opportunity
        document.getElementById('spacingMode').value = coinData.spacing_mode || 'percent';
        toggleSpacingMode();

        document.getElementById('gridLevels').value = coinData.grid_levels || 10;
        document.getElementById('gridSpacingPercent').value = coinData.grid_spacing_percent || 0.5;
        if (coinData.grid_spacing_usdt) {
            document.getElementById('gridSpacing').value = coinData.grid_spacing_usdt;
        }
        document.getElementById('gridQuantity').value = coinData.quantity || 0.001;
        document.getElementById('leverage').value = coinData.recommended_leverage || 5;

        const maxLossEl = document.getElementById('maxLossUsdt') || document.getElementById('maxLoss');
        if (maxLossEl && coinData.max_loss_usdt) maxLossEl.value = coinData.max_loss_usdt;

        const maxPosEl = document.getElementById('maxPositionUsdt') || document.getElementById('maxPosition');
        if (maxPosEl && coinData.max_position_usdt) maxPosEl.value = coinData.max_position_usdt;

        if (coinData.price) {
            lastKnownPrice = coinData.price;
            document.getElementById('currentPrice').textContent = formatPrice(coinData.price);
        }

        updateMarginCalculator();

        // Update Quant Intelligence Card with Institutional Confidence Scores
        const quantCard = document.getElementById('quantCard');
        if (quantCard) {
            quantCard.style.display = 'block';
            document.getElementById('quantRegime').textContent = coinData.regime || 'Optimal Ranging Grid';
            document.getElementById('quantAtr').textContent = coinData.atr ? `$${coinData.atr} (${coinData.atr_percent}%)` : '--';
            document.getElementById('quantRsi').textContent = coinData.rsi !== undefined ? `${coinData.rsi} (ADX: ${coinData.adx || 18})` : '--';
            
            const targetEl = document.getElementById('quantTargets');
            if (targetEl) {
                targetEl.textContent = `Stars: ${coinData.stars || '★★★★★'} (${coinData.score || 90}/100) | Prob: ${coinData.ranging_probability || 85}% | Daily ROI: ${coinData.est_daily_return_min || 3.0}% - ${coinData.est_daily_return_max || 6.0}%`;
            }
        }

        addLog('system', `⚡ AI Grid Opportunity Applied: ${symbol} (Score: ${coinData.score}/100, ${coinData.stars}) — Auto-Filled Grid: ${coinData.grid_levels}, Spacing: ${coinData.grid_spacing_percent}%, Qty: ${coinData.quantity}`);
    } else {
        addLog('system', `Selected ${symbol} from Market Radar`);
        applyAiGrid();
    }
}

// ═══════════ BOT CONTROLS ═══════════
function startBot() {
    const mode = document.getElementById('spacingMode').value;
    let symbol = document.getElementById('symbolSelect').value;
    if (!symbol) symbol = 'BTC/USDT';

    const tpModeSelect = document.getElementById('tpModeSelect');
    const tpMode = tpModeSelect ? tpModeSelect.value : 'trailing';
    const trailingCallbackEl = document.getElementById('trailingCallback');
    const trailingCallback = trailingCallbackEl ? parseFloat(trailingCallbackEl.value) : 0.5;

    const config = {
        symbol: symbol,
        spacing_mode: mode,
        grid_levels: parseInt(document.getElementById('gridLevels').value),
        grid_spacing_usdt: parseFloat(document.getElementById('gridSpacing').value),
        grid_spacing_percent: parseFloat(document.getElementById('gridSpacingPercent').value),
        quantity_per_grid: parseFloat(document.getElementById('gridQuantity').value),
        leverage: parseInt(document.getElementById('leverage').value),
        max_loss_usdt: parseFloat(document.getElementById('maxLoss').value),
        max_position_usdt: parseFloat(document.getElementById('maxPosition').value),
        trailing_tp_enabled: tpMode === 'trailing',
        trailing_tp_callback_percent: trailingCallback,
    };

    const spacingDesc = mode === 'percent' ? `${config.grid_spacing_percent}%` : `$${config.grid_spacing_usdt}`;
    addLog('system', `Starting bot: ${config.symbol} | ${config.grid_levels} levels | ${spacingDesc} spacing`);
    
    // Immediately toggle button to prevent duplicate clicks
    document.getElementById('startBtn').classList.add('hidden');
    document.getElementById('stopBtn').classList.remove('hidden');
    setControlsEnabled(false);

    socket.emit('start_bot', config);
}

function stopBot() {
    addLog('system', 'Stopping bot...');
    socket.emit('stop_bot');
}

function stopAndClosePosition() {
    addLog('system', '⚡ Stopping bot & market-closing open position...');
    socket.emit('stop_and_close');
}

function handleBotStarted(data) {
    botRunning = true;
    document.getElementById('startBtn').classList.add('hidden');
    document.getElementById('stopBtn').classList.remove('hidden');
    setControlsEnabled(false);
    
    if (data.symbol) {
        addLog('info', `Bot started: ${data.symbol}`);
        const select = document.getElementById('symbolSelect');
        if (select) {
            // Add symbol if not present in dropdown list
            if (!Array.from(select.options).some(opt => opt.value === data.symbol)) {
                const opt = document.createElement('option');
                opt.value = data.symbol;
                opt.textContent = data.symbol;
                select.appendChild(opt);
            }
            select.value = data.symbol;
        }
    }
    
    const modeLabel = document.getElementById('modeLabel');
    if (modeLabel) {
        if (data.use_testnet === false) {
            modeLabel.textContent = 'REAL MONEY LIVE';
            modeLabel.className = 'badge badge-live';
        } else {
            modeLabel.textContent = 'TESTNET';
            modeLabel.className = 'badge badge-testnet';
        }
    }

    if (data.config) {
        populateFormConfig(data.config);
    }

    // Reset price history cleanly for current symbol to avoid chart spikes
    priceHistory = [];
    lastKnownPrice = null;
    drawChart();
}

function handleBotStopped(data) {
    botRunning = false;
    document.getElementById('startBtn').classList.remove('hidden');
    document.getElementById('stopBtn').classList.add('hidden');
    setControlsEnabled(true);
    addLog('system', `Bot stopped. Final PnL: $${(data.pnl || 0).toFixed(4)}`);

    // Reset grid levels & trades display for clean new session
    gridLevels = [];
    renderGridLevels();
    document.getElementById('orderCount').textContent = '0 orders';
    drawChart();
}

function handleBotError(data) {
    addLog('error', `Error: ${data.message || 'Unknown error'}`);
    botRunning = false;
    document.getElementById('startBtn').classList.remove('hidden');
    document.getElementById('stopBtn').classList.add('hidden');
    setControlsEnabled(true);
}

function setControlsEnabled(enabled) {
    const inputs = document.querySelectorAll('.sidebar input, .sidebar select');
    inputs.forEach(input => input.disabled = !enabled);
}

// ═══════════ EVENT HANDLERS ═══════════
function handlePriceUpdate(data) {
    const price = data.price;
    const prevPrice = priceHistory.length > 0 ? priceHistory[priceHistory.length - 1] : price;

    // Update price display
    const priceEl = document.getElementById('currentPrice');
    priceEl.textContent = formatPrice(price);
    priceEl.className = `stat-value ${price >= prevPrice ? 'pnl-positive' : 'pnl-negative'}`;

    // Update price change
    const changeEl = document.getElementById('priceChange');
    const change = price - prevPrice;
    if (Math.abs(change) > 0.001) {
        changeEl.textContent = `${change >= 0 ? '▲' : '▼'} $${Math.abs(change).toFixed(2)}`;
        changeEl.className = `stat-change ${change >= 0 ? 'positive' : 'negative'}`;
    }

    // Store price history
    lastKnownPrice = price;
    priceHistory.push(price);
    if (priceHistory.length > MAX_PRICE_POINTS) priceHistory.shift();

    // Redraw chart & update margin calculator
    drawChart();
    updateMarginCalculator();
}

function handleGridUpdate(data) {
    gridLevels = data.levels || [];
    renderGridLevels();
    drawChart();

    const activeCount = gridLevels.filter(l => l.status === 'active').length;
    document.getElementById('orderCount').textContent = `${activeCount} orders`;
}

function handleTradeUpdate(data) {
    trades.unshift(data);
    if (trades.length > 50) trades.pop();
    renderTrades();
    document.getElementById('tradeCount').textContent = `${trades.length} trades`;
}

function handleStatsUpdate(data) {
    // Realized PnL
    const pnlEl = document.getElementById('realizedPnl');
    const pnl = data.realized_pnl || 0;
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)}`;
    pnlEl.className = `stat-value ${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
    document.getElementById('pnlCycles').textContent = `${data.cycles || 0} cycles`;

    // Unrealized PnL
    const upnlEl = document.getElementById('unrealizedPnl');
    const upnl = data.unrealized_pnl || 0;
    upnlEl.textContent = `${upnl >= 0 ? '+' : ''}$${upnl.toFixed(4)}`;
    upnlEl.className = `stat-value ${upnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
    document.getElementById('positionInfo').textContent = data.position_info || 'No position';

    // Balance
    const balEl = document.getElementById('balance');
    balEl.textContent = `$${(data.balance || 0).toFixed(2)}`;
}

function handleLogMessage(data) {
    addLog(data.level || 'info', data.message || '');
}

// ═══════════ RENDERING ═══════════

// ─── Grid Levels ───
function renderGridLevels() {
    const container = document.getElementById('gridLevelsDisplay');

    if (gridLevels.length === 0) {
        container.innerHTML = '<div class="empty-state">Start the bot to see grid levels</div>';
        return;
    }

    // Sort by price descending (highest first)
    const sorted = [...gridLevels].sort((a, b) => b.price - a.price);

    container.innerHTML = sorted.map(level => {
        const isBuy = level.side === 'buy';
        const statusClass = level.status === 'active' ? 'active' : level.status === 'filled' ? 'filled' : '';

        return `
            <div class="grid-level ${isBuy ? 'buy' : 'sell'}">
                <span class="grid-side ${isBuy ? 'buy' : 'sell'}">${isBuy ? 'BUY' : 'SELL'}</span>
                <span class="grid-price">${formatPrice(level.price)}</span>
                <span class="grid-status ${statusClass}">${level.status.toUpperCase()}</span>
            </div>
        `;
    }).join('');
}

// ─── Trades ───
function renderTrades() {
    const container = document.getElementById('tradeHistory');

    if (trades.length === 0) {
        container.innerHTML = '<div class="empty-state">No trades yet</div>';
        return;
    }

    container.innerHTML = trades.map(trade => {
        const isBuy = trade.side === 'buy';
        return `
            <div class="trade-item">
                <span class="trade-side ${isBuy ? 'buy' : 'sell'}">${isBuy ? 'BUY' : 'SELL'}</span>
                <span class="trade-price">${formatPrice(trade.price)}</span>
                <span class="trade-qty">${trade.quantity}</span>
                <span class="trade-time">${trade.time || '--:--'}</span>
            </div>
        `;
    }).join('');
}

// ─── Activity Log ───
function addLog(level, message) {
    const container = document.getElementById('activityLog');
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });

    const entry = document.createElement('div');
    entry.className = `log-entry log-${level}`;
    entry.innerHTML = `
        <span class="log-time">${time}</span>
        <span class="log-msg">${escapeHtml(message)}</span>
    `;

    container.prepend(entry);

    // Keep max 200 entries
    while (container.children.length > 200) {
        container.removeChild(container.lastChild);
    }
}

function clearLog() {
    document.getElementById('activityLog').innerHTML = '';
    addLog('system', 'Log cleared');
}

// ═══════════ PRICE CHART (Canvas) & HOVER TOOLTIP ═══════════
let chartCtx = null;
let chartCanvas = null;
let hoverX = -1;
let hoverY = -1;
let lastKnownPrice = 63800.0;

function setupChart() {
    chartCanvas = document.getElementById('priceChart');
    chartCtx = chartCanvas.getContext('2d');
    resizeChart();

    chartCanvas.addEventListener('mousemove', (e) => {
        const rect = chartCanvas.getBoundingClientRect();
        hoverX = e.clientX - rect.left;
        hoverY = e.clientY - rect.top;
        drawChart();
    });

    chartCanvas.addEventListener('mouseleave', () => {
        hoverX = -1;
        hoverY = -1;
        drawChart();
    });

    window.addEventListener('resize', resizeChart);
    drawChart();
    updateMarginCalculator();
}

function resizeChart() {
    const container = chartCanvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    chartCanvas.width = container.clientWidth * dpr;
    chartCanvas.height = 280 * dpr;
    chartCanvas.style.width = container.clientWidth + 'px';
    chartCanvas.style.height = '280px';
    chartCtx.scale(dpr, dpr);
    drawChart();
}

function drawChart() {
    if (!chartCtx) return;

    const w = chartCanvas.clientWidth;
    const h = 280;
    const ctx = chartCtx;
    const dpr = window.devicePixelRatio || 1;

    // Reset transform and clear
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = '#0d1220';
    ctx.beginPath();
    ctx.roundRect(0, 0, w, h, 8);
    ctx.fill();

    if (priceHistory.length < 2 && gridLevels.length === 0) {
        ctx.fillStyle = '#64748b';
        ctx.font = '14px Inter';
        ctx.textAlign = 'center';
        ctx.fillText('Waiting for price data...', w / 2, h / 2);
        return;
    }

    // Calculate price range
    const allPrices = [...priceHistory];
    gridLevels.forEach(l => allPrices.push(l.price));

    const minPrice = Math.min(...allPrices) * 0.9999;
    const maxPrice = Math.max(...allPrices) * 1.0001;
    const priceRange = maxPrice - minPrice || 1;

    const padding = { top: 20, bottom: 30, left: 80, right: 20 };
    const chartW = w - padding.left - padding.right;
    const chartH = h - padding.top - padding.bottom;

    const toY = (price) => padding.top + chartH - ((price - minPrice) / priceRange) * chartH;
    const toX = (i) => padding.left + (i / Math.max(priceHistory.length - 1, 1)) * chartW;

    // ─── Grid lines ───
    const gridCount = 5;
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    ctx.font = '11px JetBrains Mono';
    ctx.fillStyle = '#4a5568';
    ctx.textAlign = 'right';

    for (let i = 0; i <= gridCount; i++) {
        const price = minPrice + (priceRange * i / gridCount);
        const y = toY(price);
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(w - padding.right, y);
        ctx.stroke();
        ctx.fillText(formatPrice(price), padding.left - 8, y + 4);
    }

    // ─── Grid level lines ───
    gridLevels.forEach(level => {
        const y = toY(level.price);
        const isBuy = level.side === 'buy';

        // Dashed line
        ctx.strokeStyle = isBuy ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(w - padding.right, y);
        ctx.stroke();
        ctx.setLineDash([]);

        // Label
        ctx.fillStyle = isBuy ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)';
        ctx.font = '10px JetBrains Mono';
        ctx.textAlign = 'left';
        ctx.fillText(`${isBuy ? 'BUY' : 'SELL'} ${formatPrice(level.price)}`, w - padding.right - 120, y - 4);
    });

    // Build effective price history array for rendering
    let pts = [...priceHistory];
    if (pts.length === 0 && lastKnownPrice) {
        pts = [lastKnownPrice, lastKnownPrice];
    } else if (pts.length === 1) {
        pts = [pts[0], pts[0]];
    }

    const effectiveToX = (i) => padding.left + (i / Math.max(pts.length - 1, 1)) * chartW;

    // ─── Price line & Gradient ───
    if (pts.length >= 2) {
        // Gradient fill under line
        const gradient = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
        gradient.addColorStop(0, 'rgba(34, 211, 238, 0.20)');
        gradient.addColorStop(1, 'rgba(34, 211, 238, 0.0)');

        ctx.beginPath();
        ctx.moveTo(effectiveToX(0), toY(pts[0]));
        for (let i = 1; i < pts.length; i++) {
            ctx.lineTo(effectiveToX(i), toY(pts[i]));
        }
        ctx.lineTo(effectiveToX(pts.length - 1), h - padding.bottom);
        ctx.lineTo(effectiveToX(0), h - padding.bottom);
        ctx.closePath();
        ctx.fillStyle = gradient;
        ctx.fill();

        // Price line
        ctx.beginPath();
        ctx.moveTo(effectiveToX(0), toY(pts[0]));
        for (let i = 1; i < pts.length; i++) {
            ctx.lineTo(effectiveToX(i), toY(pts[i]));
        }
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Current price dot
        const lastX = effectiveToX(pts.length - 1);
        const lastY = toY(pts[pts.length - 1]);

        ctx.beginPath();
        ctx.arc(lastX, lastY, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#22d3ee';
        ctx.fill();
        ctx.beginPath();
        ctx.arc(lastX, lastY, 9, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(34, 211, 238, 0.6)';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Horizontal dashed line for live price
        ctx.strokeStyle = 'rgba(34, 211, 238, 0.5)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(padding.left, lastY);
        ctx.lineTo(w - padding.right, lastY);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // ─── Crosshair & Tooltip Hover ───
    if (hoverX >= padding.left && hoverX <= w - padding.right && priceHistory.length > 0) {
        // Find nearest index
        const index = Math.min(
            priceHistory.length - 1,
            Math.max(0, Math.round(((hoverX - padding.left) / chartW) * (priceHistory.length - 1)))
        );

        const pointX = toX(index);
        const pointPrice = priceHistory[index];
        const pointY = toY(pointPrice);

        // Draw crosshair lines
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);

        // Vertical line
        ctx.beginPath();
        ctx.moveTo(pointX, padding.top);
        ctx.lineTo(pointX, h - padding.bottom);
        ctx.stroke();

        // Horizontal line
        ctx.beginPath();
        ctx.moveTo(padding.left, pointY);
        ctx.lineTo(w - padding.right, pointY);
        ctx.stroke();
        ctx.setLineDash([]);

        // Highlight circle on price line
        ctx.beginPath();
        ctx.arc(pointX, pointY, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();

        // Draw Tooltip Box
        const tooltipText = `Price: ${formatPrice(pointPrice)}`;
        ctx.font = '12px JetBrains Mono';
        const textWidth = ctx.measureText(tooltipText).width;
        const boxWidth = textWidth + 16;
        const boxHeight = 24;
        let boxX = pointX + 10;
        if (boxX + boxWidth > w - padding.right) boxX = pointX - boxWidth - 10;
        let boxY = pointY - 30;
        if (boxY < padding.top) boxY = pointY + 10;

        ctx.fillStyle = 'rgba(15, 23, 42, 0.9)';
        ctx.strokeStyle = '#22d3ee';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(boxX, boxY, boxWidth, boxHeight, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = '#22d3ee';
        ctx.textAlign = 'left';
        ctx.fillText(tooltipText, boxX + 8, boxY + 16);
    }
}

// ═══════════ MARGIN & POSITION VALUE CALCULATOR ═══════════
function updateMarginCalculator() {
    const price = lastKnownPrice || 63800.0;
    const levels = parseInt(document.getElementById('gridLevels').value) || 10;
    const qtyPerGrid = parseFloat(document.getElementById('gridQuantity').value) || 0.001;
    const leverage = parseInt(document.getElementById('leverage').value) || 5;

    // Total Notional = levels * qtyPerGrid * price
    const totalNotional = levels * qtyPerGrid * price;
    // Required Margin = totalNotional / leverage
    const requiredMargin = totalNotional / leverage;
    // Margin Per Grid Order = requiredMargin / levels
    const marginPerOrder = levels > 0 ? requiredMargin / levels : 0.0;
    // Calculate Est. Profit per Cycle ($ & %)
    const spacingMode = document.getElementById('spacingMode')?.value || 'percent';
    let spacingUsdt = 0;
    if (spacingMode === 'percent') {
        const percent = parseFloat(document.getElementById('gridSpacingPercent')?.value) || 0.5;
        spacingUsdt = price * (percent / 100.0);
    } else {
        spacingUsdt = parseFloat(document.getElementById('gridSpacing')?.value) || 50.0;
    }
    const profitPerCycle = spacingUsdt * qtyPerGrid;
    const orderNotional = price * qtyPerGrid;
    const orderMargin = leverage > 0 ? orderNotional / leverage : orderNotional;
    const cycleRoiPercent = orderMargin > 0 ? (profitPerCycle / orderMargin) * 100.0 : 0.0;

    // Calculate Liquidation Buffer (% drop to liquidation)
    const liqBufferPercent = leverage > 0 ? ((1 / leverage) * 90.0) : 100.0;

    const notionalEl = document.getElementById('calcTotalNotional');
    const marginEl = document.getElementById('calcRequiredMargin');
    const marginPerGridEl = document.getElementById('calcMarginPerGrid');
    const estProfitEl = document.getElementById('calcEstProfitPerCycle');
    const liqBufferEl = document.getElementById('calcLiqBuffer');

    if (notionalEl) notionalEl.textContent = formatPrice(totalNotional);
    if (marginEl) marginEl.textContent = `${requiredMargin >= 1 ? requiredMargin.toFixed(2) : requiredMargin.toFixed(4)} USDT`;
    if (marginPerGridEl) marginPerGridEl.textContent = `${marginPerOrder >= 1 ? marginPerOrder.toFixed(2) : marginPerOrder.toFixed(4)} USDT`;
    if (estProfitEl) estProfitEl.textContent = `+${formatPrice(profitPerCycle)} (+${cycleRoiPercent.toFixed(1)}%)`;
    if (liqBufferEl) liqBufferEl.textContent = `-${liqBufferPercent.toFixed(1)}% Drop (Safe)`;

    // Calculate Institutional 24h Performance Predictions
    const currentSymbol = document.getElementById('symbolSelect')?.value || 'HOME/USDT';
    const spacingPercent = spacingMode === 'percent'
        ? (parseFloat(document.getElementById('gridSpacingPercent')?.value) || 0.5)
        : (price > 0 ? (spacingUsdt / price) * 100.0 : 0.5);

    // Fetch coin suitability score and status
    const coinScore = (activeCoinQuantData && activeCoinQuantData.symbol === currentSymbol) ? (activeCoinQuantData.score || 85) : 80;
    const coinStatus = (activeCoinQuantData && activeCoinQuantData.symbol === currentSymbol) ? (activeCoinQuantData.status || 'Good') : 'Good';
    const confidence = (activeCoinQuantData && activeCoinQuantData.symbol === currentSymbol) ? (activeCoinQuantData.ranging_probability || 81) : Math.min(92, Math.max(50, Math.round(88 - (spacingPercent * 2))));

    // Ranging Suitability Multipliers
    let suitabilityMult = 1.0;
    if (coinStatus === 'Avoid' || coinScore < 60) suitabilityMult = 0.15;
    else if (coinStatus === 'Risky' || coinStatus === 'Moderate' || coinScore < 70) suitabilityMult = 0.40;
    else if (coinStatus === 'Good' || coinScore < 80) suitabilityMult = 0.70;
    else if (coinStatus === 'Very Good' || coinScore < 90) suitabilityMult = 0.88;
    else suitabilityMult = 1.0;

    let baseCyclesMin = Math.max(8, Math.round((2.2 / Math.max(0.1, spacingPercent)) * 14));
    let baseCyclesMax = Math.round(baseCyclesMin * 1.35);

    const scaledCyclesMin = Math.round(baseCyclesMin * suitabilityMult);
    const scaledCyclesMax = Math.round(baseCyclesMax * suitabilityMult);

    const estDailyPnlMin = profitPerCycle * scaledCyclesMin;
    const estDailyPnlMax = profitPerCycle * scaledCyclesMax;

    const predSymbolEl = document.getElementById('predSymbol');
    const predConfidenceEl = document.getElementById('predConfidence');
    const predCyclesEl = document.getElementById('predCycles24h');
    const predPnlCycleEl = document.getElementById('predPnlCycle');
    const predDailyPnlEl = document.getElementById('predDailyPnl');

    if (predSymbolEl) predSymbolEl.textContent = currentSymbol;

    if (predConfidenceEl) {
        predConfidenceEl.textContent = `Confidence: ${confidence}% (${coinStatus})`;
        if (coinStatus === 'Avoid' || coinScore < 60) {
            predConfidenceEl.style.background = 'rgba(239, 68, 68, 0.2)';
            predConfidenceEl.style.color = '#f87171';
            predConfidenceEl.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        } else if (coinStatus === 'Risky' || coinScore < 70) {
            predConfidenceEl.style.background = 'rgba(245, 158, 11, 0.2)';
            predConfidenceEl.style.color = '#fbbf24';
            predConfidenceEl.style.borderColor = 'rgba(245, 158, 11, 0.4)';
        } else {
            predConfidenceEl.style.background = 'rgba(74, 222, 128, 0.15)';
            predConfidenceEl.style.color = '#4ade80';
            predConfidenceEl.style.borderColor = 'rgba(74, 222, 128, 0.3)';
        }
    }

    if (predCyclesEl) {
        if (coinStatus === 'Avoid') {
            predCyclesEl.textContent = `0 – 5 cycles (High Trend Risk)`;
            predCyclesEl.style.color = '#f87171';
        } else {
            predCyclesEl.textContent = `${scaledCyclesMin} – ${scaledCyclesMax} cycles`;
            predCyclesEl.style.color = '#fbbf24';
        }
    }

    if (predPnlCycleEl) predPnlCycleEl.textContent = `+${formatPrice(profitPerCycle)}`;

    if (predDailyPnlEl) {
        if (coinStatus === 'Avoid') {
            predDailyPnlEl.textContent = `$0.00 – $1.50 (NOT Recommended for Grid)`;
            predDailyPnlEl.style.color = '#f87171';
        } else {
            predDailyPnlEl.textContent = `+${formatPrice(estDailyPnlMin)} – +${formatPrice(estDailyPnlMax)}`;
            predDailyPnlEl.style.color = '#34d399';
        }
    }
}

// ═══════════ UTILITIES ═══════════
function formatPrice(price) {
    if (price === undefined || price === null || isNaN(price)) return '$0.00';
    if (price >= 1000) return '$' + price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (price >= 10) return '$' + price.toFixed(3);
    if (price >= 1) return '$' + price.toFixed(4);
    if (price >= 0.01) return '$' + price.toFixed(5);
    return '$' + price.toFixed(8);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function startClock() {
    setInterval(() => {
        document.getElementById('clock').textContent =
            new Date().toLocaleTimeString('en-US', { hour12: false });
    }, 1000);
}

// ═══════════ AUTO MODE ═══════════
let autoModeActive = false;
let autoRescoreCountdown = 1800; // 30 min in seconds

function toggleAutoMode() {
    autoModeActive = !autoModeActive;
    const btn = document.getElementById('autoModeBtn');
    const statusPanel = document.getElementById('autoModeStatus');

    if (autoModeActive) {
        btn.textContent = '🤖 Auto Mode: ON';
        btn.classList.add('active');
        statusPanel.style.display = 'block';

        const currentSymbol = document.getElementById('symbolSelect')?.value || 'ETH/USDT';
        const currentScore = (activeCoinQuantData && activeCoinQuantData.symbol === currentSymbol)
            ? (activeCoinQuantData.score || 80) : 80;

        socket.emit('toggle_auto_mode', {
            enable: true,
            current_symbol: currentSymbol,
            current_score: currentScore
        });

        document.getElementById('autoCurrentCoin').textContent = currentSymbol;
        document.getElementById('autoCurrentScore').textContent = currentScore + '/100';
        autoRescoreCountdown = 1800;
    } else {
        btn.textContent = '🤖 Auto Mode: OFF';
        btn.classList.remove('active');
        statusPanel.style.display = 'none';

        socket.emit('toggle_auto_mode', { enable: false });
    }
}

// Auto Mode countdown timer
setInterval(() => {
    if (autoModeActive && autoRescoreCountdown > 0) {
        autoRescoreCountdown--;
        const mins = Math.floor(autoRescoreCountdown / 60);
        const secs = autoRescoreCountdown % 60;
        const el = document.getElementById('autoNextRescore');
        if (el) el.textContent = `${mins}m ${secs}s`;
    }
}, 1000);

// Socket.IO listeners for Auto Mode events
if (socket) {
    socket.on('auto_mode_update', function(data) {
        autoModeActive = data.active;
        const btn = document.getElementById('autoModeBtn');
        const statusPanel = document.getElementById('autoModeStatus');

        if (data.active) {
            btn.textContent = '🤖 Auto Mode: ON';
            btn.classList.add('active');
            statusPanel.style.display = 'block';
            if (data.current_symbol) {
                document.getElementById('autoCurrentCoin').textContent = data.current_symbol;
            }
            if (data.current_score) {
                document.getElementById('autoCurrentScore').textContent = data.current_score + '/100';
            }
            if (data.next_rescore_in !== undefined) {
                autoRescoreCountdown = data.next_rescore_in;
            }
            if (data.pending_switch) {
                document.getElementById('autoNextRescore').textContent = `⚡ Switch to ${data.pending_switch} pending...`;
                document.getElementById('autoNextRescore').style.color = '#fbbf24';
            }
        } else {
            btn.textContent = '🤖 Auto Mode: OFF';
            btn.classList.remove('active');
            statusPanel.style.display = 'none';
        }
    });

    socket.on('auto_rescore', function(data) {
        autoRescoreCountdown = data.next_rescore_in || 1800;
        if (data.current_symbol) {
            document.getElementById('autoCurrentCoin').textContent = data.current_symbol;
        }
        if (data.current_score) {
            document.getElementById('autoCurrentScore').textContent = data.current_score + '/100';
        }
    });

    socket.on('auto_switch', function(data) {
        // Update UI when auto-switch happens
        addLogMessage('system', `🤖 AUTO-SWITCH: ${data.from_symbol} → ${data.to_symbol} (Score: ${data.from_score} → ${data.to_score})`);
        document.getElementById('autoCurrentCoin').textContent = data.to_symbol;
        document.getElementById('autoCurrentScore').textContent = data.to_score + '/100';

        // Update symbol selector
        const select = document.getElementById('symbolSelect');
        if (select) {
            let exists = false;
            for (let opt of select.options) {
                if (opt.value === data.to_symbol) { exists = true; break; }
            }
            if (!exists) {
                const opt = document.createElement('option');
                opt.value = data.to_symbol;
                opt.textContent = data.to_symbol;
                select.prepend(opt);
            }
            select.value = data.to_symbol;
        }

        autoRescoreCountdown = 1800;
    });

    socket.on('trend_guard_update', function(data) {
        const btn = document.getElementById('autoModeBtn');
        if (data.paused) {
            addLogMessage('risk', `🛡️ TREND GUARD: Grid PAUSED — ${data.reason} (ADX: ${data.adx?.toFixed(1)}, RSI: ${data.rsi?.toFixed(1)})`);
            // Flash the auto mode button red
            if (btn) {
                btn.style.borderColor = 'rgba(239, 68, 68, 0.6)';
                btn.style.background = 'linear-gradient(135deg, rgba(239, 68, 68, 0.25), rgba(220, 38, 38, 0.15))';
                btn.style.color = '#f87171';
            }
        } else {
            addLogMessage('system', `🛡️ TREND GUARD: Grid RESUMED — Market normalized (ADX: ${data.adx?.toFixed(1)}, RSI: ${data.rsi?.toFixed(1)})`);
            // Restore auto mode button
            if (btn && btn.classList.contains('active')) {
                btn.style.borderColor = '';
                btn.style.background = '';
                btn.style.color = '';
            }
        }
    });
}
