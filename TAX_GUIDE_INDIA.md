# 🇮🇳 Indian Tax Filing Guide for Crypto Futures Grid Trading (FY 2025–26 & FY 2026–27)

> **Document Purpose:** Complete guide on how to file taxes for your **Google Cloud 24/7 Grid Trading Bot**, including tax slab rules, deadlines (July 31st), ITR forms, and instructions for your Chartered Accountant (CA).

---

## 📅 1. Important Tax Filing Deadlines

| Financial Year (FY) | Assessment Year (AY) | Period Covered | ITR Filing Deadline (Non-Audit) |
| :--- | :--- | :--- | :--- |
| **FY 2025–26** | **AY 2026–27** | 1 April 2025 – 31 March 2026 | **31st July 2026** |
| **FY 2026–27** | **AY 2027–28** | 1 April 2026 – 31 March 2027 | **31st July 2027** |

> 📌 **Key Date:** Mark **July 31st** in your calendar every year as the deadline for filing your annual Income Tax Return (ITR).

---

## ⚖️ 2. Tax Classification: Crypto Futures vs. Spot Crypto

Under Indian Income Tax Law:

### A. Crypto Spot (Buying/Holding actual coins like BTC, SOL):
* Taxed under **Section 115BBH** at a flat **30% + 4% Cess = 31.2%**.
* ❌ NO income slab benefit, NO expense deductions, NO loss set-off.

### B. Crypto Futures / Derivatives (Binance USDT-M Perpetual Contracts):
* Taxed under **Section 28 as F&O / Derivatives Business Income**!
* ✅ **Taxed under Normal Income Tax Slabs** (0%, 5%, 10%, 15%, 20%, 30%).
* ✅ **Rebate under New Tax Regime (Section 87A):** **₹0 TAX up to ₹7,00,000 INR annual income!**
* ✅ **Allowed Expense Deductions:** You can deduct Binance trading fees, Google Cloud VPS hosting costs, software subscriptions, and internet bills.
* ✅ **Loss Set-off:** Business losses can be set off against other business income or carried forward for up to 8 years.

---

## 📊 3. Step-by-Step Filing Process for Your CA

### Step 1: Download Tax Report from Dashboard
1. Open your GridBot Dashboard (`http://<YOUR_VPS_IP>:5000`).
2. Click the purple button in the top right header: **`📄 Export Tax Report`**.
3. It downloads **`tax_report_2026.csv`**, containing:
   * Trade-by-trade timestamped breakdown
   * Buy / Sell prices & Quantities
   * Trading fees in USDT & INR (₹)
   * Net PnL in USDT & INR (₹)
   * **CA / Tax Summary Totals Section at the bottom**

### Step 2: Provide Documents to Your CA
Hand the following files to your Chartered Accountant:
1. `tax_report_2026.csv` (Downloaded from dashboard)
2. Google Cloud VPS Billing Receipts (For expense deduction)
3. Internet / Broadband Bills (For expense deduction)

### Step 3: Tell Your CA to File Under ITR-3
* **Form to Use:** **ITR-3** (Income from Business or Profession).
* **Schedule:** **Schedule BP** (Business & Profession — F&O / Derivatives Trading).
* **Turnover Calculation:** Sum of absolute profits and losses as listed in your Tax Report.

---

## 🧮 4. Sample Tax Calculation (Example)

| Metric | Amount in USDT | Amount in INR (₹88.50 Rate) |
| :--- | :---: | :---: |
| **Total Realized Profit** | $1,200.00 USDT | ₹1,06,200 INR |
| **Deduct: Binance Trading Fees** | -$48.00 USDT | -₹4,248 INR |
| **Deduct: Google Cloud VPS Hosting** | -$20.00 USDT | -₹1,770 INR |
| **NET TAXABLE BUSINESS INCOME** | **$1,132.00 USDT** | **`₹1,00,182 INR`** |

* If your total annual income is under **₹7,00,000 INR** (New Tax Regime), your total tax payable is **`₹0 (ZERO TAX)`** due to Section 87A rebate!

---

## 🛡️ Summary Checklist for Every Financial Year
- [ ] Keep bot running 24/7 on Google Cloud.
- [ ] On **March 31st**, let the current financial year close.
- [ ] Between **April 1st and July 31st**, open Dashboard ➔ click **`📄 Export Tax Report`**.
- [ ] Email `tax_report_2026.csv` + VPS invoices to your CA.
- [ ] File **ITR-3** before **July 31st**.

---
*Created automatically by Antigravity GridBot Engine.*
