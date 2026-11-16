# BankNifty — Round C Master Plan: Hunting a Stronger-Than-Baseline Champion

**Date:** 2026-10-21  **Underlying:** NIFTY BANK (monthly-only, last-Tuesday, step 100, lot 35)
**Baseline to beat (CHAMPION):** `BNF IDStrangle v2 A1_SL2000` (id 999197478) — inside-day prior-day-High/Low 2-leg short strangle, TP ₹2000 / SL ₹2000 / 15:20 exit. Net ₹224k, Calmar 1.75, DD_net ₹19.5k, win 66% (4y, Avg fills, 1 lot, NET).

---

## 1. What Rounds A & B proved (so we stop repeating dead ends)

Every variant was backtested 2022-09-12 → 2026-09-12, Avg-of-Open/Close fills, 1 lot, intraday, figures NET of costs.

| Round | Variant | Net ₹ | DD_net ₹ | Win% | Verdict |
|---|---|---|---|---|---|
| A | A1 champion (prior-H/L strangle) | **224,000** | **19,500** | 66 | **CHAMPION** |
| A | Iron fly (inside-day, ±500 wings) | 9,533 | 22,104 | 66 | Reject — cost-killed |
| A | ATM iron fly ±300/±500/±700 | −44k to −69k | 51–69% | 66 | Reject — cost death |
| A | Delta-0.15 strangle (TP/SL) | 102,996 | 17,380 | 68 | Reject — ½ of champion |
| A | Delta-0.15 strangle (prem-stop) | 104,238 | 24,970 | 69 | Reject — ½ of champion |
| B | A1 + re-entry every 15m | 181,528 | 32,203 | 69 | Reject — DD blew up |
| B | A1 + combined-prem 1.5× stop | 200,060 | 28,407 | 70 | Reject — net −11%, DD +46% |
| B | Directional Supertrend ATM-BUY | −175,824 | 182,813 | 45 | **Decisive fail** — theta death |

**The three hard lessons:**
1. **Leg count & turnover are the dominant cost lever.** 4-leg flies/condors are gross-positive but net ≈ 0 — BankNifty per-leg costs (0.1% sell-STT + slippage + exchange fees on fat monthly premium) eat the edge. Stay at **1–2 legs**.
2. **The prior-day High/Low strike placement IS the alpha.** Delta-selected strikes are clean but earn only ~half. Keep prior-H/L; don't replace it.
3. **Adding cost/turnover/long-premium always loses here.** Re-entry, premium-multiple stops, and especially **naked option-buying** (−₹176k, 915 losing stops) all underperform. A1's tight **rupee stop + selective inside-day entry** is the winning shape.

**Conclusion:** the obvious short-strangle tweaks are exhausted. To beat A1 we change *family*, not parameters — toward **defined-risk, regime-gated, selective** structures, and a directional book that **sells with the trend** (spread), never buys.

---

## 2. Round C candidate families (ranked for LOW drawdown + HIGH win-rate)

Each is Tradetron-buildable (no OI/PCR/option-volume; VWAP on futures only; day-candle OHLC, Supertrend/ADX/RSI/EMA/ATR/Bollinger, India VIX, gap%, DTE, delta strikes all available).

### C1 — Trend-gated defined-risk credit spread  *(SELLER, 2-leg, top pick)*
- **Why:** sell *with* the intraday trend; the long leg hard-caps the tail → the low-DD/high-win shape. This is the directional book done right (vs RB3's losing naked buy).
- **Entry:** 15m futures — Supertrend(7,3) agrees with EMA(20) slope AND ADX(14) ≥ 20, after the opening range resolves (09:45–10:30). Uptrend → sell ~0.25Δ put, buy ~0.10Δ put (hedge ≈200–300 pts lower). Mirror for downtrend with calls.
- **Exit:** 50–60% of credit; or Supertrend flip / ADX < 15; hard 15:10; stop = spread MTM ≥ 1.5× credit.
- **Expect:** win 60–70%, DD structurally capped by spread width.

### C2 — Expiry-week DTE-gated OTM credit spread  *(SELLER, 2-leg)*
- **Why:** monthly theta is back-loaded — ~70% of decay in the last ~5 sessions. Concentrate selling into **DTE ≤ 5**. A genuinely different gate (calendar) from the champion (price-structure).
- **Entry:** DTE ≤ 5 AND India VIX 12–20. Sell ~0.12–0.15Δ, hedge ~0.05Δ. Enter ~09:45; bias put/call side by prior-day close vs open.
- **Exit:** 50% credit decay / VIX +15% intraday / 15:15; last-Tuesday square before 15:20.
- **Expect:** win 70–80% in-window, low DD; only ~5 sessions/mo exposure (slow compounding, small sample — needs many expiries to trust).

### C3 — India-VIX-regime-gated short spread  *(SELLER, 2-leg)*
- **Why:** selling win-rate is mostly a vol-regime function. Gate a simple delta short-spread purely on a "Goldilocks" VIX band — distinct from our price-structure gates.
- **Entry:** sell ~0.12Δ hedged spread at 09:45 only when India VIX in 13–18 AND VIX ≤ its 5-day SMA (falling vol).
- **Exit:** 50% credit / VIX +12% spike / 15:10.
- **Expect:** win 70–78% in-band, low DD (no trade in dangerous regimes). Watch: low VIX = thin premium; validate ROI *net of costs*, band fit out-of-sample.

### C4 — Bollinger + RSI(2) mean-reversion, ADX-gated  *(BUYER/narrow, 1–2 leg)*
- **Why:** in low-ADX sessions BankNifty oscillates; fade 2SD band touches. Works on spot candles (no volume needed).
- **Entry:** 5m index — ADX(14) < 18–20; long when price tags lower BB(20,2) AND RSI(2) < 10 → buy ~0.55Δ CE; mirror short. Window 10:00–14:30.
- **Exit:** target BB mid-band; stop ATR(14)×1.5; 14:45 time-exit.
- **Expect:** win 65–75%, small wins; edge lives entirely in the ADX gate — cost-sensitive, backtest hard.

### C5 — Opening-range failed-breakout reclaim (futures-VWAP)  *(BUYER, 1-leg/debit)*
- **Why:** first 15–30m sweep that fails and reclaims VWAP traps breakout traders. VWAP available on futures.
- **Entry:** freeze 09:15–09:30 range; long when price breaks range-low then a 5m futures candle closes back above futures-VWAP and range-low, RSI turning up from <40. Mirror. 09:35–11:00. Add gap% < threshold filter.
- **Exit:** opposite range edge or 1.5× risk; stop below failed-sweep extreme; 13:30.
- **Expect:** win 55–65%, moderate-low DD.

### C6 — Trend-day ADX directional debit spread  *(BUYER/debit, convex complement)*
- **Why:** capture BankNifty's big clean trend days with *defined* debit risk — the convex hedge to a seller-heavy book.
- **Entry:** 15m futures ADX(14) ≥ 25 & rising, price correct side of Supertrend(7,2.5), EMA20>50; buy ATM debit spread (buy ~0.5Δ, sell ~0.25Δ) on first pullback-to-EMA20, not the breakout.
- **Exit:** trail Supertrend/ATR chandelier; partial 1:2; 15:10.
- **Expect:** win 38–48% (low by design), ROI from a few big days. Include knowingly as the convex complement, debit-capped.

**Backtest order:** C1 → C2 → C3 → C4, with C6 as the convex hedge. One change per variant, pre-registered pass rule below, ≤4 runs in flight, Avg fills, longest allowed window. Deprioritised/dropped: calendar spreads (no weekly leg anymore), ratio spreads (naked tail), unfiltered ORB, thin-VIX naked strangles (illusory).

---

## 3. Pass rule (pre-registered, same bar as before)
Adopt a Round C book as a **new champion / co-book** only if, vs A1:
- Net ≥ +5% **and** DD_net no worse than +10%; **or** DD_net −15% with net no worse than −5%.
- Holds in the last 12 months and most calendar years.
- A neighbour parameter agrees (not a lone peak); out-of-sample window not negative.
- Survives **net of BankNifty costs** (favour 2-leg defined-risk over 1-leg naked buys).
A directional book (C1/C6) is also judged as a **diversifier**: low correlation to A1 can earn it a slot even at lower standalone net, because together they smooth the equity curve.

## 4. Evidence caveat
Public sources confirm the structural facts (monthly-only, back-loaded theta, VIX-regime selling, ORB/gap/mean-reversion taxonomy) but publish no verified win/DD/ROI for post-Nov-2024 BankNifty. Every profile above is a grounded *expectation to be confirmed by our own backtest*, not a sourced result.

## 5. Guardrails (unchanged)
No capital/lot/multiplier advice. Going live is Rishabh's own step (Live Offline / paper first). Report NET, flag COVERAGE_PARTIAL. Move fast, don't waste credits; plan first, state budget, prefer free reads.
