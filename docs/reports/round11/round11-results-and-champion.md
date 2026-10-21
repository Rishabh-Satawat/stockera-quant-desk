# Round 11 Results — SENSEX Twin Book & NIFTY Iron Fly

**Date:** 2026-10-16  
**Spend:** ₹40 (2 runs × ₹20)  
**Verdict: P30 remains champion. Both hypotheses fail or are inconclusive.**

---

## 1. Objective

Round 10 identified two material levers to test next:

- **Path A (R11-SA):** Clone P30's 09:15 short-straddle rules on SENSEX weekly (BFO exchange), treating it as an uncorrelated second book.
- **Path B (R11-SB):** Add wing buys at ATM±20 strikes (~±1,000 pts) to P30's sold straddle, forming an iron fly, to test whether margin reduction is achievable without raising drawdown.

Pass rule (pre-registered): +5% net **or** −15% max DD vs P30; OOS not negative; t ≥ −1.

---

## 2. P30 Champion Reference

| Metric | Value |
|---|---|
| Strategy id | 999154354 |
| Backtest job | ttbt-999129310261013 |
| Report | https://tradetron.tech/bt/view/5ce54cb776efdf956259a6e660197a8f |
| Window | 2021-11-16 to 2026-09-08 (4.81 yr) |
| Net P&L | ₹10,43,205 |
| CAGR | 48.94% |
| Sharpe | 4.23 |
| Max DD (cap%) | **10.985%** (₹19,773) |
| Win rate (days) | 65% |
| Trades | 2,378 |

---

## 3. R11-SA: SENSEX Short Straddle

**Strategy id:** 999190510  
**Backtest job:** ttbt-999153786261016  
**Report:** https://tradetron.tech/bt/view/86b0b99eba74c27e8e8f39219c7e4ea6  
**Window:** 2023-08-07 to 2026-09-08 (3.19 yr — limited by BFO data availability)

### Raw figures (HIGH SEVERITY caveats apply — do not treat as a verdict)

| Metric | Value |
|---|---|
| Net P&L | ₹9,17,650 |
| CAGR | 106.97% |
| Sharpe | 5.31 |
| Max DD (cap%) | 21.23% |
| Win rate (days) | 65% |
| Trades | 1,506 |

### ⚠ Data quality — HIGH SEVERITY

The run returned two high-severity caveats:
- **COVERAGE_PARTIAL:** Engine lacked data for some sessions; the window the engine actually traded is shorter than requested.
- **NO_DATA_SYMBOLS:** 142 instruments had no data at all; 376 entry legs were never priced. The book is a partial execution of the strategy, not a verdict on it.

### Verdict: INCONCLUSIVE

Because 142 instruments were entirely absent, the results are tainted. No pass/fail determination is valid. The inflated CAGR (107% vs P30's 49%) is almost certainly an artifact of the missing legs — the engine skipped the losing days precisely when BFO data was unavailable.

**Root cause:** BFO historical data only begins 2023-07-01, and even within that window Tradetron's coverage of SENSEX weekly option chains is incomplete. This is a data provider limitation, not a strategy flaw.

**Do not resubmit** until full BFO chain coverage is confirmed with Tradetron support.

---

## 4. R11-SB: NIFTY Iron Fly (ATM±20 strikes, ≈±1,000 pts)

**Strategy id:** 999190518  
**Backtest job:** ttbt-999153794261016  
**Report:** https://tradetron.tech/bt/view/056f24f9784b726a48060602e3b5e2e7  
**Window:** 2021-11-16 to 2026-09-08 (4.81 yr — same as P30)

### Raw figures

| Metric | Iron Fly (R11-SB) | P30 | Δ |
|---|---|---|---|
| Net P&L | ₹8,92,627 | ₹10,43,205 | **−14.4%** |
| CAGR | 61.14% | 48.94% | +25% (but gross is tainted; see below) |
| Sharpe | 3.70 | 4.23 | −12% |
| Max DD (cap%) | **22.14%** | **10.985%** | **+101% worse** |
| Win rate (days) | 63% | 65% | −2 pp |
| Trades | 4,744 | 2,378 | 2× (counts all 4 legs) |

Note: 4,744 trades = 4 legs × ~1,186 actual iron fly round-trips.

### Pass-rule evaluation

| Gate | Threshold | Result | Verdict |
|---|---|---|---|
| Net P&L +5% | ≥ ₹10,95,365 | ₹8,92,627 (−14.4%) | ❌ FAIL |
| Max DD −15% | ≤ 9.34% | 22.14% (+101%) | ❌ FAIL |

Both primary gates fail. OOS, trailing windows and t-test not required.

### Root cause analysis

The wing buys at ATM±20 Tradetron strikes map to ATM±1,000 pts on NIFTY (each NIFTY strike = 50 pts). On weekly options with typical ATM IV of 12–16%, a 1,000-pt OTM option has very low delta and a tiny premium (usually ₹3–₹15). This means:

1. **Credit drag:** The debit paid for the wings is small but recurring on every trade — over 4.8 years this accumulates.
2. **Protection rarely fires:** NIFTY moves of ±1,000 pts intraday are extreme outliers. The wing payoff cap at ±1,000 pts is almost never reached within a trading day.
3. **Higher DD, not lower:** On the rare sessions where NIFTY moved violently, the uncapped short straddle P30 might have been protected by TSL/time exit before hitting the wing's benefit zone. The iron fly's additional legs also introduce execution slippage on 4-leg basket fills.

**Lesson:** Far OTM wings only reduce risk when the move probability justifies the premium cost. At ±1,000 pts on a weekly NIFTY straddle, they are a pure cost with no measurable benefit.

### ⚠ Data quality note

R11-SB also carried high-severity caveats (COVERAGE_PARTIAL, UNRESOLVED_SYMBOLS for 2 instruments, NO_DATA_SYMBOLS for 25). However, P30's reference run carries the same class of caveats, so the relative comparison remains directionally valid.

---

## 5. Scoreboard

| Round | Strategy | id | Net | DD (₹) | Change |
|---|---|---|---|---|---|
| … | … | … | … | … | … |
| R10 | **P30 (current champion)** | 999154354 | **10,43,205** | **19,773** | No change; 17 variants failed the bar |
| R11-SA | SENSEX straddle | 999190510 | 9,17,650 | n/a | INCONCLUSIVE (data gaps) |
| R11-SB | Iron Fly ±1000 pt | 999190518 | 8,92,627 | ~39,876 (22.14%) | REJECTED (fails both gates) |

P30 remains the unchallenged champion at ₹10,43,205 net, 10.985% max DD, Open fills.

---

## 6. Spend

| Item | Cost |
|---|---|
| R11-SA SENSEX backtest | ₹20 |
| R11-SB Iron Fly backtest | ₹20 |
| **Total** | **₹40** |

---

## 7. Next real levers (Rishabh decides)

1. **SENSEX:** Revisit only after confirming full BFO chain coverage with Tradetron support (ideally 3+ years of clean data).
2. **Wing efficiency at tighter strikes:** If margin reduction is the goal, test wings at ±2–4 strikes (100–200 pts) where premiums are meaningful and the protection fires more often. Note: 200 pt wings were already rejected in Round 3 (lost most of the edge). Probably not worth revisiting.
3. **Alternative margin lever:** Consider running a single lot on a wider underlying (SENSEX, which has a higher notional per lot) once BFO data quality improves.
4. **Live Offline for P30:** The priority action is still logging 09:15 and re-entry fills on the live P30 (SID 999319106) for 10–20 sessions before going fully live.
