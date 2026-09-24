# ⚡ Stockera Master Quant Desk
**Institutional Autonomous Derivatives Engine & Multi-Agent Trading System**

## 🏛️ System Architecture
* **Ingestion Layer:** Dhan HQ v2 API (`/v2/optionchain`, `/v2/marketfeed/ltp`) + Yahoo Finance & BSE Live Fallbacks.
* **Microstructure Intelligence:** Real-time Max Pain, Put-Call Ratio (PCR), and Call/Put Writer Wall tracking.
* **Dual-Book Execution:**
  * **Hedged Income Book (3 Trades/Day):** Range-bound Delta-Neutral Iron Condors & Spreads.
  * **Naked Directional Book (3 Trades/Day):** Momentum Option Buying with 1:2.5+ Risk:Reward.
* **AURA Sentinel & Capital Defense:** 15:20 IST Expiry STT Trap Watchdog and automated square-off.
* **Master Cockpit:** Streamlit visual terminal with live multi-agent committee deliberation and CSV export.
* **Compliance & Lot Sizes:** 2026 Exchange Specifications (NIFTY: 65, BANKNIFTY: 30, SENSEX: 20, FINNIFTY: 60).

## 🔒 Security
API keys and environment secrets are excluded via `.gitignore`.
