# BankNifty v2 — Inside-Day Short Strangle · Round 1 Report

**Base:** *Final Copy of Trial of BANKNIFTY NFO Dynamic Inside-Day Short Strangle v3 No-Repair Clean* (Template #999197298)
**Window:** 2022-09-12 → 2026-09-07 (~4yr) · **Avg of Open/Close fills** · **1 lot** · **NET** · **Spend: ₹220 of ₹300 (11 paid runs)**
**Goal:** low drawdown, high ROI, high win-rate, good Calmar. Three families tested: other indicators · no-stop-loss · combined-premium + indicator exits.

---

## Verdict

| | Strategy | id | Net ₹ | Calmar | Sharpe | DD_net ₹ | DD peak% | Win% |
|---|---|---|---|---|---|---|---|---|
| **Risk-adjusted champion** | A1_SL2000 (TP2000/SL2000) | 999197478 | 224,016 | **1.75** | **2.15** | **19,469** | 18.35 | 66 |
| **Best no-stop-loss (your idea)** | C1_T2000_CP150 | 999197802 | 200,060 | 1.11 | 1.69 | 28,407 | **13.34** | **70** |
| Belt + braces | C2_T2000_SL2000_CP150 | 999197810 | 221,597 | 1.76 | 2.12 | 19,298 | 18.35 | 66 |

**The stop is the alpha lever, not the exit indicator.** A tight ₹2000 PnL stop (A1) delivered the best drawdown, Calmar, Sharpe and net of the whole round. Your combined-premium exit idea (C1) *works* — it gives the smoothest equity curve (13.3% peak DD) and the highest win-rate (70%) — but on **rupee** drawdown it does not beat the tight stop (₹28k vs ₹19.5k).

## What each family showed
- **No-stop-loss + combined-premium exit (N1/N2/N3/C1):** higher win-rate (70–71%) and smoother %-curves, but ~1.5–2× the rupee drawdown of a tight stop. Among the ratios, **1.5× is the DD sweet spot**; looser ratios (1.75×, 2.0×) raise DD.
- **Other indicators:** ADX<25 entry filter (I1) cut net −28% → trade-removing filters hurt short premium. Supertrend on the traded strangle premium (N4/I3) carried illiquidity (NO_DATA_SYMBOLS) caveats → unreliable.
- **Re-entry:** every 30 min (R1) gave the highest headline net (₹264k) but 2× drawdown and 2× turnover → brokerage-fragile, not a risk-adjusted edge.

## Caveats
- All runs **COVERAGE_PARTIAL high-severity**: prior-day H/L strikes are often illiquid (~1567 entries unpriceable). Same both sides, so comparisons are valid, but absolute ₹ is a slight over-count. **Validate on Live Offline first.**
- Brokerage = ₹0 in the engine; the workbook's "Net after brkg" column adds ~₹20/order by hand.
- All figures per **1 lot**, scale linearly. No capital / lot / multiplier is recommended.

## Deliverables
- Workbook: `reports/banknifty-v2/BankNifty_v2_InsideDay_Strangle_Workbook.xlsx` (Summary · All Runs · Exit Attribution · Champion · Per-Year Net · Methodology).
- Ledger: `knowledge/BANKNIFTY_V2_LEDGER.md` (read first before any new round).
- Pre-registered plan: `reports/banknifty-v2/MASTER_PLAN_R1.md`.

## Next step
Going live is your own call. Recommend deploying the champion (A1 or C1) on **Live Offline (paper)** from its Tradetron edit page first, then gating to real money once it holds up.
