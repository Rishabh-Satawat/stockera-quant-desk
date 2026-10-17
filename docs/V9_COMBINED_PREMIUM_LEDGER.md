# V9 Combined-Premium Supertrend straddle — research ledger (read this first)

Single source of truth for the Tradetron **NIFTY combined-premium Supertrend straddle** research.
SEPARATE from the NIFTY short-straddle work (NIFTY_RESEARCH_LEDGER.md) and the BankNifty inside-day strangle (BANKNIFTY_RESEARCH_LEDGER.md). Different structure.

- Last updated: 2026-10-17 (Round 1 done: champion = short-only + Supertrend(10,2) + no target).
- Owner: Rishabh. Source strategy: id 999027898 "V9 Final of Combined Premium Straddle Strategy with Supertrend Logic."

## 0. Standing instructions (do not break)
- Never recommend capital, lot count or multiplier. Going live is Rishabh's own step; mention Live Offline once per result.
- Move fast, do not waste credits. Plan first, state budget, then run. Prefer free reads.
- No Python blocks in Tradetron strategies (engine bug).
- Repo stays PUBLIC; no account ids/secrets pushed without asking.
- Contract facts: NIFTY weekly = Current Week token, Tuesday expiry, lot 65. Never hardcode lot sizes.
- Report NET (not the gross the report page shows by default). Flag COVERAGE_PARTIAL caveats.

## 1. What the strategy is
Combined premium = ATM CE + ATM PE added candle-by-candle (`OHLC Sum`, 5-min). Supertrend run ONCE on that synthetic series.
The original (999027898) is TWO books:
- **Set 1 LONG straddle**: buy ATM CE+PE when combined-premium close > Supertrend (premium uptrend). Exit on flip down.
- **Set 2 SHORT straddle**: sell ATM CE+PE when Supertrend > combined-premium close (premium downtrend). Exit on flip up.
- Universal exit: PNL >= 10,000 x mult, OR weekly-expiry day 15:19. NRML legs, carries intraday.

## 2. Champion (Round 1)
**V9 CP-ST ShortOnly ST10-2 NoTgt, id 999196482.** NIFTY weekly ATM, short straddle only.
- Change vs Rishabh's V9: (1) drop the LONG book; (2) Supertrend multiplier 3 -> 2; (3) remove the 10k target.
- Entry: from 09:15, Supertrend(10,2) on combined premium > its close, book flat; re-enter each signal.
- Exit: combined-premium close crosses back above Supertrend(10,2); plus weekly-expiry 15:19. No target, no fixed stop.
- **Numbers (5-yr 2021-09-12..2026-09-12, net, 1 lot, job ttbt-999159482261017):**
  net Rs 7,87,965; Sharpe 2.70; Sortino 4.02; Calmar 1.41; CAGR 54.8%; DD Rs 38,906 (16.6% peak); exp Rs 197; PF 1.15; 63% win-days; 4,444 trades.
  Report: https://tradetron.tech/bt/view/39f42b1219ef6363978288ac5e3a4a74
- **Alternative (higher per-trade expectancy, fewer trades): SO_NOTGT (10,3 + no target), id 999196294** — net Rs 7,51,439, Sharpe 2.42, exp Rs 223, DD Rs 48,089, 3,698 trades. Lower turnover => less slippage-sensitive live.

**Baseline (Rishabh's V9, 5-yr re-run, job ttbt-999159246261017):** net Rs 6,47,258; Sharpe 1.99; CAGR 35.7%; DD Rs 59,022; exp Rs 187; 63% win-days; 3,866 trades. Report 3d62c48be2b382d2aecb773a47fa0ac4.

## 3. The findings
1. **The LONG book is dead weight.** Set attribution on the baseline: Set 2 (short) = 110% of net (+Rs 7.13L); Set 1 (long) LOST Rs 66k over 306 round-trips, and ADDS to drawdown. Dropping it lifts return AND cuts DD. Mechanical, not luck.
2. **Tighter Supertrend band (10,2) is the best single knob**: net Rs 7.66L, Sharpe 2.66, lowest rupee DD. Removing the rarely-binding 10k target adds a touch more (champion = both).
3. **Supertrend is robust, not curve-fit**: periods 7/10/14 all net Rs 7.3-7.7L, Sharpe 2.39-2.66.
4. **Significance (paired daily t-test, champion vs baseline): t = 1.44 — NOT distinguishable from zero.** So the +22% net is within daily noise; do NOT sell it as proven alpha. What IS real: dropping a confirmed loser, and the -34% rupee drawdown. Same money, much smoother ride (Sharpe 1.99 -> 2.70).

## 4. Rejected this round (do not re-run)
- Remove the Supertrend exit (hold to target/expiry): DD explodes Rs 48k -> Rs 82k (16.8% -> 35.4% peak), Sharpe 1.69. The ST exit is PROTECTIVE. Hard reject.
- Entry 09:30 (skip open): net collapses Rs 733k -> Rs 444k, Sharpe 1.67. The 09:15 signal carries real value.

## 5. Tradetron mechanics (this strategy)
- Combined premium, entry side: `OHLC Sum(Instrument Name('NFO,NIFTY 50,Current Week,CE,ATM,,'),Instrument Name('NFO,NIFTY 50,Current Week,PE,ATM,,'),'5m')`.
- Exit side (traded legs, set N): `OHLC Sum(Traded Instrument Name('Entry','instrument','NIFTY 50','N','1','1'),Traded Instrument Name('Entry','instrument','NIFTY 50','N','1','2'),'5m')`. Author WITHOUT strategy_id/run_counter (auto-injected); set_number = the set's ORDINAL position (short-only => '1').
- Supertrend on a table: `Position(SUPERTREND(<OHLC Sum>,'10','2'),'-1')`; close element: `Position(CLOSE(<OHLC Sum>),'-1')`.
- Flat check: `Positions Detail('All','All','All','quantity','NIFTY 50') == Number(0)` (All-scope = is-book-flat; allows re-entry each signal).
- Strike: `ATM("NIFTY 50", 0)` (futures-anchored). Validator nudges ATM SPOT for weeklies — untested; a Round-2 item.
- Backtest: fleet ceiling 60 months. End <= today-35. 5-yr window 2021-09-12..2026-09-12 avoids most 2020 COVID coverage holes.
- Capital field display-only; P&L scales with lots. All runs 1 lot.

## 6. Round log
| Round | Date | Spend | Outcome |
|---|---|---|---|
| R1 | 2026-10-17 | Rs 180 (9 runs) | Champion = short-only + ST(10,2) + no target. Net +22% / DD -34% / Sharpe 1.99->2.70 vs Rishabh's V9. Return uplift within daily noise; DD + dropping-loser are the real wins. |

## 7. Plan ahead (Round 2)
1. Second-indicator confirmation (ADX / premium-vs-EMA) to lift expectancy on the busy 10,2 band.
2. ATM SPOT vs ATM strike test.
3. Disaster-only stop (-6-8k) to cap tail days without the NoSTexit damage.
4. Re-entry cap 2-3/day to cut churn (champion trades 4,444x).
5. Out-of-sample 2018-2021 once coverage confirmed; request walk-forward.

## 8. Where everything lives
- Workbook: `/mnt/project-files/reports/nifty-v9/V9_CombinedPremium_Supertrend_Workbook_R1.xlsx`
- Round report: `/mnt/project-files/reports/nifty-v9/round1-combined-premium-supertrend.md`
- Repo copies under `docs/`.

## 9. Strategy ids created this round
Short-only 999196282 · NoSTexit 999196290 · NoTarget 999196294 · ST7-3 999196298 · ST14-3 999196306 · ST10-2 999196314 · Entry930 999196322 · CHAMPION ST10-2 NoTgt 999196482. Baseline 999027898.
