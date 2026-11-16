# BankNifty Inside-Day Short Strangle — v2 Research Ledger
<!-- description: Canonical ledger for the BankNifty Inside-Day Short Strangle. Read FIRST before any new research round. Champion, rejected list, mechanics, per-round tables. -->

**Read this first before running any new round.** Never re-run a tested idea below.

Base strategy: *Final Copy of Trial of BANKNIFTY NFO Dynamic Inside-Day Short Strangle v3 No-Repair Clean*
Template #999197298 · https://tradetron.tech/bt/view/675f59bd8ab9fcd18f81977281d7812e

Logic: when today's open is inside the prior day's High–Low range, at 09:30 sell 1 lot CE at the rounded prior-day HIGH strike and 1 lot PE at the rounded prior-day LOW strike (BankNifty, **monthly** expiry, lot 15). Forced exit 15:20.

Window all runs: **2022-09-12 → 2026-09-07** (~4yr), **Avg of Open/Close fills**, **1 lot**, **NET** figures.

---

## CHAMPIONS

### Risk-adjusted champion — A1_SL2000 (999197478)
- TP +2000 / SL −2000 / time 15:20 (× multiplier).
- Net **₹224,016** · Calmar **1.75** · Sharpe **2.15** · DD_net **₹19,469 / 18.35%** · win 66% · PF ~1.19 · 1848 trips.
- Net after est. brokerage ₹150,096. Per-year 12m ₹59k / 24m ₹98k / 36m ₹175k.
- Report: https://tradetron.tech/bt/view/b1dcb1da9d15057a5d8c9e520bc18dd2
- **The tight PnL stop is the clean DD/Calmar lever.** Best net, Calmar, Sharpe and rupee-DD of the round.

### Best no-stop-loss variant — C1_T2000_CP150 (999197802)
- No PnL stop. Exits: TP +2000, combined premium ≥ 1.5× entry, time 15:20.
- Net **₹200,060** · Calmar **1.11** · Sharpe 1.69 · DD_net ₹28,407 / **13.34% peak (smoothest curve of the round)** · win **70%** · 1548 trips.
- Net after est. brokerage ₹138,140. Per-year 12m ₹67k / 24m ₹80k / 36m ₹124k.
- The combined-premium exit (the owner's explicit idea) **works** and gives the smoothest equity + highest win-rate, but on **rupee** drawdown it does NOT beat the tight ₹2000 stop (₹28k vs ₹19.5k).

### Belt + braces twin — C2_T2000_SL2000_CP150 (999197810)
- A1 stop + the 1.5× combined-premium exit stacked. Net ₹221,597 · Calmar 1.76 · DD_net ₹19,298 · win 66% · 1854 trips.
- ≈ A1 exactly: the premium exit rarely fires before the ₹2000 stop. Adding it is near-neutral (safe to keep as a secondary guard).

---

## KEY FINDINGS (carry forward)
1. **The stop is the alpha lever, not the exit indicator.** A1's tight ₹2000 stop beat every premium/indicator exit on rupee-DD and Calmar.
2. The loose −₹3000 base stop (A0) bled −₹479k across 290 stops — tightening to −₹2000 is the single biggest DD improvement.
3. **Combined-premium + indicator exits buy a higher win-rate (70–71%) and a smoother %-curve, at ~1.5–2× the rupee drawdown** of a tight PnL stop. Among premium-exit ratios, **1.5× is the DD sweet spot** (looser 1.75×/2.0× raise DD).
4. Trade-removing **filters hurt short premium**: ADX<25 entry filter cut net −28% (I1). Reject filters as a family.
5. **Re-entry (30m) gives the highest headline net but ~2× DD and ~2× turnover** — brokerage-fragile, not a risk-adjusted edge.
6. **Supertrend on the traded strangle premium is unreliable**: illiquid short strikes can't be priced (NO_DATA_SYMBOLS caveat on N4/I3) in backtest and live.

## REJECTED (do not re-test without a new angle)
| variant | id | why rejected |
|---|---|---|
| I1_ADX25 (entry ADX<25) | 999197470 | net −28%; filter removes edge |
| R1_REACT30 (re-entry 30m) | 999197502 | 2× DD + 2× turnover; not risk-adjusted |
| N4_CPST_GATE (ST+prem gate) | 999197466 | NO_DATA_SYMBOLS illiquidity caveat |
| I3_CPST_PURE (pure ST exit) | 999197498 | NO_DATA_SYMBOLS caveat + worst DD (21.6%) |
| N2_CPX175 / N3_CPX200 | 999197486 / 999197494 | looser premium exit → higher DD than N1/C1 |

## ALL RUNS (NET, 1 lot)
| variant | id | net ₹ | Calmar | Sharpe | DD_net ₹ | DD peak% | win% | trips |
|---|---|---|---|---|---|---|---|---|
| A0_BASE | 999197462 | 170,869 | 0.97 | 1.44 | 29,235 | 18.67 | 68 | 1882 |
| **A1_SL2000** | **999197478** | **224,016** | **1.75** | **2.15** | **19,469** | 18.35 | 66 | 1848 |
| N1_CPX150 | 999197482 | 203,395 | 1.05 | 1.63 | 30,572 | 15.60 | 71 | 1714 |
| N2_CPX175 | 999197486 | 207,254 | 0.72 | 1.58 | 45,165 | 18.50 | 71 | 1688 |
| N3_CPX200 | 999197494 | 211,924 | 0.81 | 1.61 | 40,569 | 17.38 | 71 | 1674 |
| N4_CPST_GATE | 999197466 | 196,206 | 0.76 | 1.55 | 41,173 | 17.08 | 70 | 1730 |
| I1_ADX25 | 999197470 | 122,282 | 0.82 | 1.19 | 26,910 | 18.75 | 69 | 1382 |
| I3_CPST_PURE | 999197498 | 143,574 | 0.60 | 1.41 | 41,296 | 21.62 | 65 | 2068 |
| R1_REACT30 | 999197502 | 263,816 | 0.91 | 1.81 | 41,899 | 16.16 | 70 | 2572 |
| **C1_T2000_CP150** | **999197802** | **200,060** | **1.11** | 1.69 | 28,407 | **13.34** | **70** | 1548 |
| **C2_T2000_SL2000_CP150** | **999197810** | **221,597** | **1.76** | **2.12** | 19,298 | 18.35 | 66 | 1854 |

## MECHANICS / CAVEATS
- All runs carry **COVERAGE_PARTIAL high-severity**: the prior-day H/L strikes are often illiquid; ~1567 entries can't be priced in backtest. Same both sides (apples-to-apples), so comparisons hold — but absolute rupee figures are a slight over-count. **Validate the champion on Live Offline first.**
- Brokerage = ₹0 in the engine cost model. "Net after brkg" adds ~₹20/order by hand (fills ≈ 2× trips).
- Figures are per **1 lot** and scale linearly with lots/multiplier. Never recommend capital/lots/multiplier.
- Spend this round: **11 paid runs = ₹220** of the ₹300 (15-run) budget.
- Combined-premium expansion exit markdown shape (verified):
  `Math Operation(LTP(leg1),LTP(leg2),'+') >= Math Operation(Math Operation(TradedPrice(leg1),TradedPrice(leg2),'+'),Number(1.5),'*')`

## UNTESTED IDEAS FOR A NEXT ROUND (budget left ~2 runs this cycle)
- Spot-distance exit + re-enter at new ATM (I2 built, 999197474, not yet run) — orthogonal to the premium signal, may cut DD without killing win-rate.
- Entry-time sweep (09:30 vs 09:45 vs first-candle confirmation).
- CE/PE strike offset one step wider than prior-day H/L (less whipsaw at the cost of premium).
- Net-Delta band exit (scaled by lot × multiplier).
