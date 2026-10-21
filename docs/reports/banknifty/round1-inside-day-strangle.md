# BankNifty Inside-Day Short Strangle — Round 1

**Date:** 2026-10-17
**Underlying:** NIFTY BANK monthly options (Current Month), intraday
**Window:** 2022-09-12 to 2026-09-12 (4.0 yr), Open fills, intraday, 1 lot
**Spend:** ₹220 (11 backtests × ₹20)
**Champion candidate: V3 — cut the hard stop from ₹3,000 to ₹2,000.**

---

## 0. Context — this is a NEW strategy line

Rounds 1–11 in this project were all on a **NIFTY short straddle** (champion R6-P30).
This BankNifty inside-day strangle is a separate strategy Rishabh brought on 2026-10-17.
It has its own ledger and workbook; it does not replace or extend the NIFTY work.

Source strategy: id 10398878 "Copy of Trial of BANKNIFTY NFO Dynamic Inside-Day Short Strangle v3 No-Repair Clean".

---

## 1. What the strategy is

Sell a monthly strangle, intraday, **only on inside days** (today opens within yesterday's range):
- Sell CE at Round(prior-day HIGH, 100); sell PE at Round(prior-day LOW, 100).
- Entry Time ≥ 09:30, position flat.
- Universal Exit: Time ≥ 15:20, OR P&L ≥ +TP, OR P&L < −SL.
- Reactivate every 120 min (re-entry allowed).

---

## 2. Baseline (your file, re-run on 4 years)

| Metric | Value |
|---|---|
| Net P&L (1 lot) | ₹1,89,469 |
| Max DD | ₹26,758 (gross) |
| Sharpe | 1.65 |
| Profit factor | 1.15 |
| Expectancy / trade | ₹141 |
| Win days | 70% |
| Trades | 1,882 |
| Report | https://tradetron.tech/bt/view/67b49d0012bb921259004274ea433412 |

**Weaknesses identified:**
1. Backwards risk:reward — risking ₹3,000 to make ₹1,500.
2. Thin profit factor (1.15); avg loss (₹2,332) > avg win (₹1,827).
3. 1,572 prior-day-H/L strikes were unpriceable (illiquid) — high-severity coverage caveat.

---

## 3. All 10 variants (one change each, same 4-yr window)

| Test | id | TP/SL | Net ₹ | DD ₹ | Sharpe | Verdict |
|---|---|---|---|---|---|---|
| Base | 10398878 | 1500/3000 | 189,469 | 26,758 | 1.65 | — |
| V1 | 999195678 | 2000/3000 | 175,438 | 32,216 | 1.46 | Rejected (net −7%) |
| V2 | 999195682 | 2500/3500 | 166,680 | 38,393 | 1.34 | Rejected (net −12%) |
| **V3 ★** | **999195686** | **2000/2000** | **208,163** | **20,250** | **1.97** | **CHAMPION** |
| V4 | 999195690 | 1500/2000 | 198,427 | 16,595 | 1.97 | Safest (−38% DD) |
| V6 | 999195698 | 1500/3000, +100pt strikes | 171,596 | 20,910 | 1.58 | Rejected (net −9%) |
| V7 | 999195702 | 1500/3000, ATM±300 strikes | 80,323 | 21,882 | 0.84 | Rejected (net −58%) |
| V8 | 999195706 | 1500/3000, entry 09:45 | 159,821 | 29,163 | 1.43 | Rejected (net −16%) |
| V9 | 999195710 | 1500/3000, no re-entry | 150,283 | 25,734 | 1.66 | Rejected (net −21%) |
| V10 | 999195770 | 2000/2500 | 196,296 | 22,210 | 1.75 | Plateau neighbour |
| V11 | 999195774 | 2000/1500 | 146,592 | 19,602 | 1.44 | Too tight (net −23%) |

---

## 4. The finding: the stop was the whole story

**Stop-loss sweep at TP ₹2,000** — a clean inverted-U peaking at SL ₹2,000:

| Stop | Net ₹ | DD ₹ | Sharpe |
|---|---|---|---|
| 1,500 (V11) | 146,592 | 19,602 | 1.44 |
| **2,000 (V3)** | **208,163** | **20,250** | **1.97** |
| 2,500 (V10) | 196,296 | 22,210 | 1.75 |
| 3,000 (V1) | 175,438 | 32,216 | 1.46 |

SL ₹2,000 is a genuine optimum, confirmed on both sides. Every other lever (strikes, entry time, re-entry) lost.

**Most important rejection — V7 (fixed ATM±300 strikes): net −58%, Sharpe 0.84.**
The alpha lives in the prior-day high/low strike placement. Replacing it with a plain ATM strangle destroys the edge. Do not touch the strike rule.

---

## 5. Honesty on significance

Paired daily t-test vs baseline:
- V3: mean daily diff +₹31, t = 0.53 — **net gain NOT statistically distinguishable from zero.**
- V4: mean daily diff +₹15, t = 0.30 — same.

So the **+10% / +5% net is within noise** — do not treat it as a proven return uplift.
What IS robust is the **drawdown reduction** (−24% V3, −38% V4): it is mechanical — a tighter stop
caps per-trade losses by construction — and it shows up as the Sharpe lift (1.65 → 1.97).

**Bottom line:** V3/V4 give you the same money with a materially smoother ride. That is the real win.

All runs still carry the baseline's COVERAGE_PARTIAL caveat and the unpriceable-strike issue; the
comparison is apples-to-apples (same caveat both sides) but absolute figures are a slight over-count.

---

## 6. Champion vs safest — your pick

- **V3 (TP2000/SL2000)** — return-tilted: net ₹2,08,163, DD ₹20,250, Sharpe 1.97.
- **V4 (TP1500/SL2000)** — risk-minimal: net ₹1,98,427, DD ₹16,595 (−38%!), Sharpe 1.97.

Both are single-change wins over your file. The choice between them is a risk-appetite call — yours to make.

---

## 7. Plan ahead

1. Deploy the pick Live Offline for 10–20 sessions to confirm 09:30 fills and the ₹2,000 stop.
2. Choose V3 vs V4.
3. Test a trailing-stop-to-cost (lock winners past +₹1,000).
4. Test a high-VIX regime filter (inside-day strangles bleed on violent trend days).
5. Out-of-sample 2020–2022 to confirm the ₹2,000 stop holds on older data.
6. Confirm BankNifty monthly chain coverage with Tradetron support (1,572 unpriceable strikes).

Going live is Rishabh's own step, done on the strategy's edit page.
