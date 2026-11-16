# BankNifty Inside-Day Short Strangle — v2 Master Plan (pre-registered)

**Date:** 2026-10-17
**Target file:** `Final Copy of ... Inside-Day Short Strangle v3 No-Repair Clean` (id 999197298)
**Goal (Rishabh):** very low drawdown, higher ROI, higher win rate, good Calmar.
**Budget cap:** 15 paid backtests = ₹300 (pack exhausted; ₹20/run cash). Report spend at end.
**Fills:** `Avg of Open and Close` for the WHOLE round (realistic). The prior v1 round and the
target's own backtest used Open fills, which inflate short-premium ~2-3×; those numbers are a
ceiling, not a forecast. Everything here is re-anchored on Avg so it is internally honest.
**Window:** 2022-09-12 → 2026-09-12 (4.0 yr). BankNifty monthly option data on the fleet starts
~2022-09, and backtests must end ≥35 days before today (today 2026-10-17 → end ≤ 2026-09-12).
A true pre-2022 out-of-sample is not available; robustness leans on per-year consistency,
last-12-months, and neighbour agreement instead.

---

## What the target strategy is (do not break the alpha)
Sell a BankNifty monthly strangle on an **inside day**: CE struck at `Round(prior-day HIGH,100)`,
PE at `Round(prior-day LOW,100)`. Enter from 09:30 when the day opens inside yesterday's range and
the book is flat. Exit at 15:20, or +₹1500×mult, or −₹3000×mult. Reactivate 120 min.

**The prior-day H/L strike rule IS the edge** (v1 proved fixed ATM±300 lost −58%). Every variant
keeps it. We only touch the **stop / exit / re-entry / regime filter**.

## Carried findings from v1 (do not re-run)
- Stop is the clean DD lever: SL 3000→2000 cut DD −24% (net within noise). SL<2000 collapses net.
- Entry 09:45 lost −16%; wider strikes −9%; no-re-entry (react 360) lost −21% but gave the best
  per-trade expectancy and 73% win-days.
- Net-gain significance was within daily noise (t≈0.5); the DD reduction was the real, mechanical win.

## Pass rule (adopt a change only if ALL hold vs the current base)
1. Net +5% with DD no worse than +10%, OR DD −15% with net no worse than −5%.
2. At/above base in most calendar years AND the last 12 months.
3. A neighbour value agrees (a lone peak is noise).
4. Paired daily t reported (t≥2 real; 1–2 needs support; <−1 rejects).
5. Survives brokerage (~₹20/order added by hand on high-turnover variants).
6. No high-severity caveat touches net/DD/trades; a >50% jump from one change is "too good" → inspect fills.

---

## Pre-registered runs (≤15)

**Anchor (2)** — establishes the realistic-fills base:
1. `A0_BASE_AVG` — target as-is (TP1500/SL3000), Avg fills.
2. `A1_SL2000` — TP2000/SL2000 (v1 champ ported to Avg). Better of A0/A1 becomes base **B**.

**Family N — no stop-loss + combined-premium exit (Rishabh's #2 & #3) (4):**
3. `N1_CPX150` — remove −₹ PnL stop; exit when combined LTP ≥ **1.5×** combined entry premium.
4. `N2_CPX175` — same, **1.75×** (neighbour).
5. `N3_CPX200` — same, **2.0×** (neighbour, looser).
6. `N4_CPST_GATE` — remove −₹ PnL stop; exit when **Supertrend(10,3) flips up on the sold-legs'
   combined premium AND combined LTP ≥ 1.3× entry** (his literal "indicator confirms AND premium > value").

**Family I — other indicators (Rishabh's #1) (3):**
7. `I1_ADX25` — enter only when spot ADX(14) < 25 (range regime favours a strangle; expect filters to cut edge — testing it answers the ask).
8. `I2_SPOTDIST` — keep base stop; add exit when |spot − entry spot| ≥ 0.6% (delta/recenter proxy).
9. `I3_CPST_PURE` — remove −₹ stop; pure Supertrend-flip-up exit on combined premium, no premium gate (contrast to N4).

**Family R — re-entry cadence (alpha-loop's strongest prior lever) (2):**
10. `R1_REACT30` — reactivate 30 min (vs 120).
11. `R2_REACT60` — reactivate 60 (neighbour).

**Champion build + neighbour (reserve, 2 of the 4 remaining slots):**
12. `C1_COMBO` — stack the winning stop + exit + cadence.
13. reserve neighbour / tie-break.

Stop early if two batches produce no pass; keep the rest of the budget.

## Deliverables
Fresh v2 workbook + v2 ledger + round report; 1–3 hero candidates with net/DD/Calmar/win-rate/
last-12m/t and the one reason each might fail; Live Offline plan (going live is Rishabh's own step).
