# ⚡ Quant AI Grid Trading Bot & Risk Engine

An institutional-grade, real-time (<50ms) quantitative grid trading system and risk manager for **Binance Futures**, featuring an AI Parameter Generator, Auto-Trailing Recenter Engine, Trailing High-Water Mark Risk Shields, and a Live Interactive Web Dashboard.

---

## 📚 Table of Contents
1. [🎓 Crypto & Trading Dictionary for Beginners](#-crypto--trading-dictionary-for-beginners)
2. [🟡 Binance & Crypto Trading Guide (How to Buy & Trade)](#-binance--crypto-trading-guide-how-to-buy--trade)
3. [🤖 How Grid Trading Works](#-how-grid-trading-works)
4. [📊 Understanding Every Item on the Dashboard](#-understanding-every-item-on-the-dashboard)
5. [🛡️ Built-in Risk Management & Protection Shields](#️-built-in-risk-management--protection-shields)
6. [🏗️ Project Architecture & File Directory](#️-project-architecture--file-directory)
7. [🚀 Quickstart & Installation Guide](#-quickstart--installation-guide)
8. [📥 30-Day Quant Performance Tracking & CSV Export](#-30-day-quant-performance-tracking--csv-export)

---

## 🎓 Crypto & Trading Dictionary for Beginners

If you are new to crypto trading, here is a breakdown of every concept used in this system:

### 1. USDT (Tether)
- **What it is**: A "stablecoin" pegged 1:1 to the US Dollar ($1.00 USDT = $1.00 USD).
- **In this bot**: All profits, balances, margins, and grid levels are denominated in USDT.

### 2. Binance Futures (Perpetual Contracts)
- **What it is**: A derivative trading market where you can trade price movements of coins (BTC, ETH, SOL) without owning the physical underlying cryptocurrency.
- **Perpetual**: Unlike standard futures contracts, perpetual contracts never expire and can be held indefinitely.

### 3. Leverage (e.g., 10x)
- **What it is**: Borrowing capital from the exchange to trade larger position sizes.
- **Example**: With $100 USDT margin at **10x leverage**, your effective purchasing power is **$1,000 USDT**.
- **Rule of Thumb**: Higher leverage increases profit potential, but reduces your safety buffer during market drops.

### 4. Realized PnL (Profit & Loss)
- **What it is**: **Real cash profits** locked in from completed buy-and-sell cycles.
- **Where it goes**: Added directly to your cash wallet balance.

### 5. Unrealized PnL (Floating Paper Profit/Loss)
- **What it is**: The temporary paper profit or loss of active open positions that have not yet been closed.
- **Example**: If you bought ETH at $1,830 and the current price is $1,835, your Unrealized PnL is positive. Once the SELL order fills at $1,835, it becomes **Realized PnL**.

### 6. Wallet Balance (Pure Cash Equity)
- **What it is**: Your total cash equity stored on Binance, excluding floating paper PnL. This is your real, spendable cash.

### 7. Margin
- **What it is**: The amount of cash collateral deducted from your wallet to open and maintain a leveraged position.

### 8. Liquidation Safety %
- **What it is**: The percentage price drop required before the exchange would forcefully close your position to prevent negative wallet balances.
- **In this bot**: The system automatically calculates liquidation distance and keeps you in the **"Safe Zone"** (>9% drop buffer).

---

## 🟡 Binance & Crypto Trading Guide (How to Buy & Trade)

### 1. How Binance Wallets Work (Spot vs. Futures)
Binance has two primary trading wallets:
- **Spot Wallet**: Where you buy and hold actual coins (e.g., buying 1 ETH and storing it in your account).
- **USDT-M Futures Wallet**: **(Where this bot trades!)** Uses USDT as collateral to trade leveraged perpetual contracts.

### 2. How to Buy USDT & Fund Your Bot
To start trading with real money on Binance:
1. **Buy USDT**: Go to Binance $\rightarrow$ **P2P Express** or **Buy Crypto with Credit/Debit Card** to convert your local currency (USD, EUR, INR) into **USDT**.
2. **Transfer to Futures**: Go to **Wallets** $\rightarrow$ **Transfer** $\rightarrow$ Transfer USDT from **Spot Wallet** to **USDT-M Futures Wallet**.

### 3. Key Binance Futures Features

#### A. Margin Modes (Cross vs. Isolated)
- **Cross Margin (Default for Grid Bot)**: All available USDT in your Futures wallet acts as shared collateral. This prevents premature liquidation during short wiggles.
- **Isolated Margin**: Allocates a fixed dollar amount to a single trade.

#### B. Order Types (Maker vs. Taker)
- **Limit Orders (Maker Fee ~0.02%)**: Orders placed on the order book waiting for price to touch them. Grid bots use limit orders because Maker fees are super cheap (~0.02%).
- **Market Orders (Taker Fee ~0.05%)**: Orders executed instantly at current market price. Used by your Risk Manager for emergency shutdowns.
- **Reduce-Only Orders**: Orders that can ONLY reduce or close an existing open position, preventing accidental opposite trades.

#### C. Funding Rates (Paid Every 8 Hours)
- Every 8 hours, traders on Binance Futures pay or receive a small funding fee.
- If funding is positive (**+0.01%**), Long traders pay Short traders. If negative (**-0.01%**), Short traders pay Long traders.
- Your bot's **Quant Engine** monitors funding rates live on the dashboard radar!

### 4. Golden Security Rules for API Keys
When creating your Binance API key:
- ✅ Check **`Enable Futures`**.
- ❌ **NEVER check `Enable Withdrawals`**! (A trading bot should NEVER have permission to withdraw funds).
- 🔒 Keep your `api_secret` completely private and never upload it to public GitHub repositories.

---

## 🤖 How Grid Trading Works

Grid trading is an automated trading strategy that profits from price volatility by building a "ladder" of BUY and SELL orders around current market prices.

```text
 ─── SELL Level 4   $1,849.00  (Target Take-Profit)
 ─── SELL Level 3   $1,846.00  (Target Take-Profit)
 ─── SELL Level 2   $1,843.00  (Target Take-Profit)
 ─── SELL Level 1   $1,840.00  (Target Take-Profit)
 ───────── CURRENT PRICE: $1,837.00 ─────────
 ─── BUY Level 1    $1,834.00  (Buy the Dip)
 ─── BUY Level 2    $1,831.00  (Buy the Dip)
 ─── BUY Level 3    $1,828.00  (Buy the Dip)
 ─── BUY Level 4    $1,825.00  (Buy the Dip)
```

### The Perpetual Cycle:
1. When price drops to **$1,834.00**, the **BUY** order fills.
2. The bot instantly places a corresponding **SELL** order at **$1,837.00** ($3.00 higher).
3. When price bounces back to **$1,837.00**, the **SELL** order fills, locking in **+$1.60+ CASH PROFIT**!
4. The bot immediately places a new **BUY** order back at **$1,834.00**, repeating 24/7!

---

## 📊 Understanding Every Item on the Dashboard

When you open **`http://localhost:5000`**, here is what every section means:

| Dashboard Element | Meaning / Explanation |
| :--- | :--- |
| **Current Price** | Real-time mark price streamed live from Binance via WebSockets (<50ms latency). |
| **Realized PnL** | Total closed cash profits earned during the current run across all completed cycles. |
| **Completed Cycles** | Total number of successful Buy $\rightarrow$ Sell grid trade pairs executed. |
| **Unrealized PnL** | Current floating paper value of active positions. |
| **Balance (USDT)** | Live total wallet cash equity. |
| **ATR Volatility** | Average True Range indicator measuring market volatility over the last 14 candles. |
| **RSI (14)** | Relative Strength Index (0–100). Below 30 = Oversold (Bullish buy zone); Above 70 = Overbought (Bearish sell zone). |
| **Order Book Imbalance** | Ratio of active buyers vs. sellers in the top 20 levels of the exchange order book. |
| **8h Funding / APR** | Interest rate paid between Long and Short traders every 8 hours on futures. |
| **Est. Profit / Cycle** | Expected net cash profit earned every time 1 grid pair completes. |
| **Activity Log** | Real-time stream showing order executions, cycle completions, auto-compounds, and system alerts. |

---

## 🛡️ Built-in Risk Management & Protection Shields

This bot includes institutional-grade safety mechanisms to protect your capital:

1. **Hard Max Loss Shield (`max_loss_usdt`)**:
   - If total account loss ever touches your pre-set limit (e.g. $50.00), the Risk Manager executes an emergency shutdown, cancels all open grid orders, and closes positions via market orders.

2. **High-Water Mark Trailing Profit Protection (`peak_pnl`)**:
   - Protects earned profits. If your session profit peaks at +$100.00 and market pulls back by $50.00, the bot stops and locks in the remaining +$50.00 net cash profit!

3. **Auto-Trailing Recenter Engine**:
   - If price trends out of the grid bounds, the bot automatically cancels old distant orders and re-centers grid bounds around current market price.

4. **Auto-Compound Engine**:
   - Automatically reinvests earned cash profits to incrementally scale order lot sizes over time.

5. **Self-Healing Order Reconciliation Audit**:
   - Audits local order memory against Binance's live order book every 5 seconds. If network latency creates "Ghost" or "Un-tracked" orders, it auto-reconciles them in <50ms and prints an **Order Reconciliation Report**.

---

## 🏗️ Project Architecture & File Directory

```text
d:/tradingbot/
├── config.json               # API Credentials, Trading Pair, and Risk Settings
├── requirements.txt          # Python Dependency Manifest (ccxt, flask, websockets)
├── README.md                 # System Guide, Crypto Dictionary & Binance Manual
├── scratch/
│   └── verify_all.py         # Automated 6-Test Unit & Integration Verification Suite
├── logs/
│   └── performance_30d.csv   # 30-Day Quantitative Performance & Snapshot Log
├── src/
│   ├── main.py               # Command Line Interface (CLI) Runner
│   ├── web_server.py         # Flask + Socket.IO Real-Time Web Server
│   ├── binance_client.py     # CCXT Exchange Client (REST API Operations)
│   ├── binance_ws.py         # Low-Latency (<50ms) Asyncio WebSocket Streaming Engine
│   ├── grid_engine.py        # Grid Order State Machine & Cycle Recycling Engine
│   ├── risk_manager.py       # Dual-Shield Risk Manager & Trailing Stop Controller
│   ├── quant_engine.py       # Technical Indicators (ATR, RSI, BB, Order Book Math)
│   ├── performance_tracker.py# 30-Day Quantitative Analytics Logger & Self-Healing Auditor
│   └── logger.py             # Color-Coded Console & File Logger
└── static/
    ├── index.html            # Web Dashboard Frontend Interface
    ├── style.css             # Premium Modern Dark-Mode CSS Design System
    └── app.js                # Real-time WebSocket Client & HTML5 Canvas Price Chart
```

---

## 🚀 Quickstart & Installation Guide

### Step 1: Install Dependencies
Open PowerShell or Terminal in the project directory:
```bash
pip install -r requirements.txt
```

### Step 2: Configure API Keys
Edit `config.json`:
```json
{
  "api_key": "YOUR_BINANCE_TESTNET_API_KEY",
  "api_secret": "YOUR_BINANCE_TESTNET_API_SECRET",
  "use_testnet": true,
  "symbol": "ETH/USDT",
  "grid_levels": 8,
  "grid_spacing_usdt": 3.0,
  "quantity_per_grid": 0.5,
  "leverage": 10,
  "max_loss_usdt": 50.0,
  "max_position_usdt": 1600.0
}
```

### Step 3: Run the Live Dashboard
```bash
python src/web_server.py
```

### Step 4: Open Dashboard
Open your browser and navigate to:
**`http://localhost:5000`**

---

## 📥 30-Day Quant Performance Tracking & CSV Export

The bot continuously records 5-second quantitative performance snapshots to **`logs/performance_30d.csv`**.

### How to Download Data:
1. Click the cyan **`📥 Export 30D CSV`** button in the dashboard topbar.
2. Or navigate directly to `http://localhost:5000/api/download_csv`.

### Captured Metrics in CSV:
- **Timestamp & DateTime**
- **Wallet Cash Balance ($)**
- **Realized PnL ($)**
- **Unrealized PnL ($)**
- **Net Equity ($)**
- **High-Water Mark Peak Equity ($)**
- **Maximum Drawdown (MDD $ and MDD %)**
- **Completed Cycle Count**
- **Estimated Binance Fees Paid ($)**
- **Net PnL After Fees ($)**
- **WebSocket Reconnect Count**
- **Uptime Hours**
- **Order Desync Status**

---

## 🌐 24/7 VPS Deployment Guide (Oracle Cloud / Ubuntu Linux)

To run your bot 24/7 without keeping your local PC on, you can host it on a **Cloud VPS** (Oracle Cloud Always Free Tier, DigitalOcean, Hetzner, AWS, etc.). This also provides a permanent **Static Public IP** to whitelist on Binance for maximum security.

---

### Step 1: Connect to your Ubuntu VPS via SSH
```bash
ssh ubuntu@YOUR_VPS_PUBLIC_IP
```

### Step 2: Install System Dependencies & Python Libraries
```bash
# Update package list and install Python 3, pip, git, and venv
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git ufw tmux
```

### Step 3: Clone Repository & Set Up Virtual Environment
```bash
# Clone the repository
git clone https://github.com/your-username/tradingbot.git
cd tradingbot

# Create and activate Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Install required Python packages
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure `config.json`
```bash
# Create config file from example
cp config.json.example config.json

# Edit config with your API keys & settings
nano config.json
```
*(Fill in your `api_key`, `api_secret`, `use_testnet: false` for Live trading, and optional Telegram tokens. Press `Ctrl + O` to save, `Ctrl + X` to exit).*

### Step 5: Open Firewall Ports 22 & 5000 (Prevents SSH Lockout)
```bash
# IMPORTANT: Always allow SSH port 22 BEFORE enabling UFW!
sudo ufw allow 22/tcp
sudo ufw allow 5000/tcp
sudo ufw enable
```
*(If using **Oracle Cloud**, also add an Ingress Rule for Port 5000 in your Oracle Cloud Console -> Virtual Cloud Network -> Security Lists -> Add Ingress Rule: CIDR `0.0.0.0/0`, TCP Port `5000`).*

---

### Step 6: Keep Bot Running 24/7 (Choose Option A or B)

#### 🔹 Option A: Systemd Background Service (RECOMMENDED)
Creates an automatic Linux service that runs 24/7 and auto-restarts if the VPS reboots.

1. Create a systemd service file:
```bash
sudo nano /etc/systemd/system/gridbot.service
```

2. Paste the following configuration (replace `/home/ubuntu/tradingbot` with your actual path):
```ini
[Unit]
Description=24/7 Binance Futures Quant Grid Trading Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/tradingbot
ExecStart=/home/ubuntu/tradingbot/venv/bin/python src/web_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gridbot
sudo systemctl start gridbot
```

4. Check bot service status:
```bash
sudo systemctl status gridbot
```

---

#### 🔹 Option B: Tmux Session (Quick Alternative)
```bash
# Start a new tmux session
tmux new -s gridbot

# Activate venv and start bot
source venv/bin/activate
python src/web_server.py

# Detach from session (bot stays running in background!): Press Ctrl+B then D
# Re-attach anytime: tmux a -t gridbot
```

---

### Step 7: Access Dashboard & Whitelist IP on Binance

1. Open your browser and navigate to:  
   **`http://YOUR_VPS_PUBLIC_IP:5000`**
2. Copy your VPS Public IP and add it to your **Binance API Management -> Restrict access to trusted IPs only** for maximum security!

---

### ⚠️ Disclaimer
*This trading bot is provided for educational and quantitative research purposes. Cryptocurrency futures trading involves significant financial risk. Always test thoroughly on Binance Demo/Testnet before deploying real capital.*

