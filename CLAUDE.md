\# 🏛️ STOCKERA QUANT DESK — MASTER SYSTEM ARCHITECTURE \& OPERATING SPECIFICATION

\*\*Version:\*\* 5.2 (Unified Autonomous Institutional Architecture)  

\*\*Repository:\*\* https://github.com/Rishabh-Satawat/stockera-quant-desk  

\*\*Primary Execution Environment:\*\* Windows `C:\\kite-agent` | Streamlit Port: `8501`  

\*\*Target Markets:\*\* NSE \& BSE Derivatives (F\&O) \& Liquid Equities  

\*\*Supported Underlyings:\*\* NIFTY 50 (`IDX\_I: 13`), BSE SENSEX (`IDX\_I: 51`), BANK NIFTY (`IDX\_I: 25`), FIN NIFTY (`IDX\_I: 27`), Stock Futures/Options



\---



\## 1. System Philosophy \& Vision

The Stockera Quant Desk operates as an autonomous, institutional-grade options trading firm. The system does not guess or trade randomly; it follows the exact operational cadence of a hedge fund:



1\. \*\*Pre-Market \& Opening 15-Minute Macro Context (09:15 – 09:30 AM IST)\*\*:

&#x20;  - Evaluates higher timeframe market structure (Monthly, Weekly, Daily, and Prior Session High/Low/VWAP).

&#x20;  - Ingests the opening 15-minute price discovery, initial volatility expansion, and early Open Interest (OI) positioning before taking directional risk.

2\. \*\*Autonomous Multi-Agent Alpha Hunting (09:30 – 15:15 IST)\*\*:

&#x20;  - Scans live market data every 60 seconds across indices and liquid underlyings.

&#x20;  - Requires composite multi-factor confluence score ($\\ge 80/100$) before dispatching trades.

&#x20;  - Enforces strict capital preservation: hard cap of \*\*3 Hedged trades\*\* and \*\*3 Naked trades\*\* per day.

3\. \*\*Sub-Second Runtime Threat \& Risk Guardian (AURA Sentinel)\*\*:

&#x20;  - Polls active positions every 1–3 seconds.

&#x20;  - Continuously evaluates live Option Chain shifts to detect \*\*intra-trade reversals\*\* (e.g., holding a Long call while aggressive Call Writing or Short Buildup suddenly spikes).

&#x20;  - Issues immediate mobile alerts on Telegram: Target 1 achieved, Stop-Loss triggered, or Threat Anomaly detected.

4\. \*\*15:20 IST Expiry Settlement \& STT Watchdog\*\*:

&#x20;  - Auto-squares off in-the-money 0DTE options before the 15:25 IST cutoff to eliminate physical delivery and heavy notional Securities Transaction Tax (STT).

5\. \*\*15:30 IST Executive EOD Performance Blotter\*\*:

&#x20;  - Reconciles daily P\&L down to the paisa, tracks win rate, and posts an institutional audit card.



\---



\## 2. End-to-End Operational Lifecycle



\### Diagram 1: Automated Daily Execution Loop

\[09:15 AM Market Opening \& 15m Profiling]

│

▼

\[09:30 AM Alpha Engine Engaged] ──> Evaluates Microstructure \& CVD

│

▼

\[🚀 HIGH-CONVICTION ENTRY TRIGGER]

├──> Pushed to Telegram (@PropdeskAgentbot)

├──> Logged as status='ACTIVE' in trades\_ledger.json

└──> Synced to Supabase Cloud (stockera\_trades)

│

▼

\[Live Polling \& Sentinel Loop (Every 1–3 Seconds)]

├──> If P\&L >= +Target 1 ──> \[🎯 TARGET HIT ALERT] ──> Trail SL / Book 50%

├──> If P\&L <= -StopLoss ──> \[🔴 STOP LOSS HIT]    ──> Instant Square-Off

├──> If Reversal Detected ─> \[⚠️ ANOMALY ALERT]     ──> Dynamic Adjustment

└──> At 15:20 IST ─────────> \[⏰ STT WATCHDOG]      ──> Mandatory 0DTE Liquidation

│

▼

\[15:30 IST EOD Audit Blotter] ────> Dispatches Net P\&L \& Win Rate to Telegram

### Diagram 2: Deterministic Risk Sensor \& Anomaly Copilot

\[Broker Telemetry: Dhan / Kite / Fyers] ──> Reads Open Positions

│

▼

\[Deterministic Risk Sensor] ──> Checks Quotes, Delta Drift \& PCR every 1–3s

│

├──> Normal Market? ──> Silently tracks Trailing SL \& P\&L

│

└──> Anomaly Detected! (Sudden 300 pt index reversal, or Delta Skew > 0.35)

│

▼

\[AI Expert Copilot (JARVIS)]

├── 1. Analyzes trade: "Short CE leg under pressure, Delta = -0.42"

├── 2. References Playbook: "Strategy: iron-fly-v5 / credit-spread"

└── 3. Synthesizes Actionable Adjustment Strategy

│

▼

\[Instant Telegram Action Alert Sent to Mobile]

### Diagram 3: Dual-Mode JARVIS Deliberator

┌──────────────────────────────────────────────┐

&#x20;                │          LIVE DHAN HQ v2 MARKET FEED         │

&#x20;                │   Spot LTP • Option Chain • OI • Tick Depth  │

&#x20;                └──────────────────────┬───────────────────────┘

&#x20;                                       │

&#x20;                  ┌────────────────────┴────────────────────┐

&#x20;                  ▼                                         ▼

&#x20;      \[MODE 1: ALPHA GENERATOR]                 \[MODE 2: LIVE TRADE DOCTOR]

&#x20;      (For Traders Seeking Setup)               (For Active Running Trades)

&#x20;                  │                                         │

&#x20;                  ├───────────────────┬─────────────────────┤

&#x20;                  ▼                   ▼                     ▼

&#x20;           ┌──────────────┐    ┌──────────────┐      ┌──────────────┐

&#x20;           │ TECH-REGIME  │    │ GREEKS \& PCR │      │  ORDER FLOW  │

&#x20;           │    AGENT     │    │  SPECIALIST  │      │  CVD AGENT   │

&#x20;           └──────┬───────┘    └──────┬───────┘      └──────┬───────┘

&#x20;                  │                   │                     │

&#x20;                  └───────────────────┼─────────────────────┘

&#x20;                                      ▼

&#x20;                          ┌───────────────────────┐

&#x20;                          │  CHIEF RISK OFFICER   │

&#x20;                          │  (6-Gate Consensus)   │

&#x20;                          └───────────┬───────────┘

&#x20;                                      │

&#x20;                ┌─────────────────────┴─────────────────────┐

&#x20;                ▼                                           ▼

&#x20;   \[PRE-TRADE RADAR ALERT]                     \[RUNNING TRADE HEALTH VERDICT]

"Enter 0DTE Condor at 74100"               "Hold \& Trail SL" / "Cut Position"

---



\## 3. The 4 Trader Personas \& Mathematical Parameters



| Parameter | 1. Ultra-Scalper | 2. Intraday Momentum | 3. 0DTE Weekly Expiry | 4. Positional / Swing |

| :--- | :--- | :--- | :--- | :--- |

| \*\*Primary Horizon\*\* | 2 – 15 Minutes | 30 Mins – 3 Hours | Intraday till 15:20 IST | 3 Days – 3 Weeks |

| \*\*Timeframe Candles\*\* | 1-min \& 3-min | 5-min \& 15-min | 15-min \& 30-min | 1-Hour \& Daily |

| \*\*Option Instrument\*\* | Deep ATM / 1-ITM ($\\Delta \\approx 0.55–0.70$) | ATM / 1-OTM Debit Spreads | Out-of-the-Money Spreads / Condors | Monthly Expiry Spreads / Diagonals |

| \*\*Dominant Greek\*\* | Gamma ($\\Gamma$) \& Delta ($\\Delta$) | Delta ($\\Delta$) \& Trend | Theta ($\\Theta$) Decay Velocity | Vega ($\\nu$) \& Volatility Skew |

| \*\*Stop-Loss Model\*\* | Tight Point Stop (e.g. ₹5–₹8 Nifty) | Technical Structure (15m Swing Low) | 1x Net Premium Received | Max Dollar Loss per Portfolio ($<2\\%$) |

| \*\*Target Model\*\* | 1:1 to 1:1.5 Quick Burst | 1:2 to 1:3 Trailing 20 EMA | 80% Premium Decay / 15:20 EOD | Reaching Key Daily S/R Levels |



\---



\## 4. File Layout \& Component Directory

C:\\kite-agent



├── app\_master\_cockpit.py          # Unified Master Operator Console (Streamlit on port 8501)

├── auto\_trade\_hunter.py           # 60-second autonomous scanner (Dual-Book: Max 3/3 daily quota)

├── live\_sentinel\_daemon.py        # Sub-second AURA position guardian (monitors Target/SL/Reversals)

├── order\_flow\_cvd\_engine.py       # Level-2 Cumulative Volume Delta \& Order Book Imbalance engine (v5.1)

├── expiry\_settlement\_watchdog.py  # 15:20 IST Expiry risk manager (ITM STT penalty defense)

├── eod\_ledger\_reporter.py         # 15:30 IST End-of-Day P\&L rollup and Telegram blotter card

├── telegram\_bot\_listener.py       # 2-Way interactive bot answering /status, /positions, /diagnose, /cvd

├── cockpit\_ledger\_bridge.py       # Bridge logging broadcasted baskets into trades\_ledger.json

├── dhan\_order\_router.py           # Multi-leg execution gateway (Paper Mode \& Live Dhan HQ v2 API)

├── chain\_microstructure\_analyzer.py # Real-time Dhan option chain parser \& strike aggregator (186 strikes)

├── live\_spot\_service.py           # Underlying spot quote fetcher

├── market\_day\_supervisor.py       # Master clock supervisor (09:15 -> 15:20 -> 15:30)

├── start\_desk.bat                 # 1-Click Windows desktop launcher (boots all 3 daemons + UI)

├── stop\_desk.bat                  # 1-Click shutdown script (terminates all background processes)

├── trades\_ledger.json             # Dual-store audit ledger for active and closed trades

├── trades\_history.csv             # Permanent historical CSV blotter for compliance and tax

└── secrets



├── dhan.env                   # DHAN\_CLIENT\_ID, DHAN\_ACCESS\_TOKEN

├── telegram.env               # TELEGRAM\_BOT\_TOKEN, TELEGRAM\_CHAT\_ID

└── supabase.env               # SUPABASE\_URL, SUPABASE\_KEY

---



\## 5. Broker Integrations \& Data Ingestion

1\. \*\*Dhan HQ v2 API\*\*:

&#x20;  - `POST https://api.dhan.co/v2/marketfeed/ltp`: Sub-second spot quotes (`IDX\_I: 13, 51, 25, 27`).

&#x20;  - `POST https://api.dhan.co/v2/optionchain`: Real-time 186-strike options chain, Greeks, OI, and depth.

&#x20;  - `POST https://api.dhan.co/v2/orders`: Multi-leg basket routing.

2\. \*\*Zerodha Kite Connect\*\*:

&#x20;  - Margin and available cash telemetry (`HP4636`, ₹657k cash pool).

&#x20;  - Session authentication via `access\_token.txt`.

3\. \*\*Fyers API (Bridge Ready)\*\*:

&#x20;  - Configured for multi-broker redundancy and cross-broker order routing.

4\. \*\*Supabase Cloud Database\*\*:

&#x20;  - Tables: `stockera\_trades` (trade lifecycle) and `trade\_legs` (individual options legs).



\---



\## 6. Official Contract Specifications \& Lot Sizes

\* \*\*BSE SENSEX\*\*: 30 Qty / Lot (Strike step: 100)

\* \*\*NSE NIFTY 50\*\*: 25 Qty / Lot (Strike step: 50)

\* \*\*NSE BANK NIFTY\*\*: 15 Qty / Lot (Strike step: 100)

\* \*\*NSE FIN NIFTY\*\*: 60 Qty / Lot (Strike step: 50)



\---



\## 7. Interactive Telegram Command Suite (`@PropdeskAgentbot`)

\* `/status` — Real-time P\&L, today's trades, win rate, and active legs.

\* `/positions` — Real-time list of all active open legs in `trades\_ledger.json`.

\* `/diagnose <contract> <entry> <ltp>` — Runs the JARVIS Live Running Trade Doctor and returns an instant verdict:

&#x20; \* 🎯 `TARGET 1 REACHED — BOOK 50% \& TRAIL STOP-LOSS TO COST`

&#x20; \* 🛑 `HARD STOP-LOSS BREACHED — CUT POSITION IMMEDIATELY`

&#x20; \* 🟡 `NORMAL RETRACEMENT — MAINTAIN POSITION WITH DISCIPLINE`

&#x20; \* 🟢 `MOMENTUM HEALTHY — GAINS ACCUMULATING`

\* `/cvd \[asset]` — Returns real-time Level-2 Order Book Imbalance and CVD tape reading.

\* `/eod` — Triggers an on-demand audit blotter broadcast.

\* `/help` — Displays command menu.



\---



\## 8. Current Implementation Roadmap \& Open Milestones

\- \[x] Unified Master Cockpit on port 8501 (`app\_master\_cockpit.py`).

\- \[x] Real-time mathematical P\&L calculation from `(exit - entry) \* qty`.

\- \[x] Live Dhan order-book integration with real bid/ask midquotes.

\- \[x] Autonomous background Trade Hunter (`auto\_trade\_hunter.py`) with 3/3 daily quota.

\- \[x] Runtime AURA Sentinel (`live\_sentinel\_daemon.py`).

\- \[x] Level-2 Order Flow \& CVD Engine (`order\_flow\_cvd\_engine.py`).

\- \[x] 15:20 STT defense watchdog and 15:30 EOD Telegram blotter.

\- \[x] 2-way Telegram interactive command listener (`telegram\_bot\_listener.py`).

\- \[x] Production 1-Click desktop startup script (`start\_desk.bat`).

\- \[ ] \*\*Next Milestone\*\*: Canonical Multi-Broker Instrument Mapping Bridge (`dhan\_kite\_bridge.py`) cross-referencing Dhan Security IDs to Zerodha Kite instrument tokens.

\- \[ ] \*\*Next Milestone\*\*: Real-Time Intra-Trade Reversal Warning in `live\_sentinel\_daemon.py` (alerts Telegram when unexpected OI or delta shifts oppose an open position).

\- \[ ] \*\*Next Milestone\*\*: Mobile Web Dashboard (Supabase Realtime WebSocket subscription).



