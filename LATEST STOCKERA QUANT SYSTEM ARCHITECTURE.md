┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              STOCKERA QUANT END-TO-END SYSTEM TOPOLOGY                                 │
└────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                              │
    ┌─────────────────────────────────────────┴─────────────────────────────────────────┐
    ▼                                                                                   ▼
┌─────────────────────────────────────────────┐                     ┌───────────────────────────────────┐
│        TIER 1: REAL-TIME INGESTION          │                     │     TIER 2: DATA REPOSITORY       │
│  • Dhan HQ v2 WebSocket (Sub-second Ticks)  │────────────────────▶│  • Supabase Cloud (Snapshots)     │
│  • Level-2 / Level-3 Order Book Depth       │                     │  • High-Speed Memory Cache (Dicts)│
│  • Cumulative Volume Delta (CVD) Engine     │                     │  • Historical 1-Yr CSV Datasets   │
│  • Kite Connect Position Poller             │                     │  • Canonical Instrument Bridge    │
└─────────────────────────────────────────────┘                     └───────────────────────────────────┘
                        │                                                             │
                        ▼                                                             │
┌─────────────────────────────────────────────────────────────────────────────────────┴─┐
│                    TIER 3: THE MULTI-AGENT QUANT COMMITTEE (THE BRAIN)                │
│                                                                                       │
│  ┌───────────────────────┐   ┌───────────────────────┐   ┌─────────────────────────┐  │
│  │ 🟢 Technical Analyst  │   │ 🔵 Derivatives & OI   │   │ 🟡 Order Flow & Depth   │  │
│  │ • 5/20/50 EMA Slopes  │   │ • Black-76 Greeks     │   │ • L2/L3 Depth Imbalance │  │
│  │ • Multi-TF VWAP       │   │ • Put-Call Ratio (PCR)│   │ • CVD Buying Aggression │  │
│  │ • RSI Momentum Pivots │   │ • Volatility Skew     │   │ • Iceberg Absorption    │  │
│  └───────────────────────┘   └───────────────────────┘   └─────────────────────────┘  │
│             │                            │                            │               │
│             └────────────────────────────┼────────────────────────────┘               │
│                                          ▼                                            │
│                       ┌─────────────────────────────────────┐                         │
│                       │  ⚖️ Lead Quant Arbiter (Consensus)  │                         │
│                       │  • Conviction Scoring (0 - 100%)    │                         │
│                       │  • Emits daily_regime.json (5-15m)  │                         │
│                       └─────────────────────────────────────┘                         │
└──────────────────────────────────────────┬────────────────────────────────────────────┘
                                           │
                                           ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                        TIER 4: THE 6-LAYER INSTITUTIONAL RISK GATE                    │
│  1. Capital Exposure Gate   (Max 2% portfolio risk per trade)                         │
│  2. Regime & Volatility     (No long calls in chop; no unhedged selling in VIX spike) │
│  3. Liquidity & Spread      (Bid-Ask spread < 0.4%, Strike OI > 50,000)               │
│  4. Greeks Armor            (Net Gamma < 0.0015, Net Theta positive for credit)       │
│  5. 15:20 Expiry Watchdog   (Mandatory square-off prompt; prevents ITM intrinsic STT) │
│  6. Active Realized R:R     (Min 1:2 R:R for Debit | Hard 1x-Credit Stop Loss)        │
└──────────────────────────────────────────┬────────────────────────────────────────────┘
                                           │
         ┌─────────────────────────────────┴─────────────────────────────────┐
         ▼                                                                   ▼
┌─────────────────────────────────────────────┐         ┌───────────────────────────────────────────────┐
│     TIER 5A: FRONT-END TRADING DESK         │         │      TIER 5B: AURA SENTINEL & TELEGRAM        │
│  • Streamlit Master Cockpit (Port 8501)     │         │  • Daemon watching open Kite & Dhan legs      │
│  • 1-Click Multi-Leg Execution (Dhan HQ)    │         │  • Detects Adverse Divergence (Long vs Dump)  │
│  • Payoff Curve & Breakeven Visualizers     │         │  • Dispatches Alerts to @PropdeskAgentbot     │
│  • Dynamic PoP (%) & Realized R:R Metrics   │         │  • Voluntary Trade Radar for Unlinked Users   │
└─────────────────────────────────────────────┘         └───────────────────────────────────────────────┘