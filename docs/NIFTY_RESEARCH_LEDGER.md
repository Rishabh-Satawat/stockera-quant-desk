# NIFTY straddle research ledger (canonical, read this first)

This is the single source of truth for the Tradetron NIFTY short-straddle research. Any new thread should read this file before doing anything else.

- Last updated: 2026-10-16 (Round 10 done: R6-P30 reinstated as champion on Open fills, the basis of its own report and of the live fills; no variant beat it by 5%).
- Owner: Rishabh.
- The detailed tables live in the files listed in section 9. This file holds the decisions, rules, ids and lessons.

## 0. Standing instructions from Rishabh (do not break)

- Never recommend capital, lot count or multiplier. Going live is Rishabh's own step; mention Live Offline once per result, no more.
- Portfolio-level SL is out of scope.
- No Python blocks in Tradetron strategies (engine bug, section 7).
- The GitHub repo stays PUBLIC. Never suggest making it private, and do not push research secrets or account ids there without asking.
- Move fast and do not waste credits. Plan first, state the budget, then run. Prefer free reads (result, compare, trades) over new runs.
- NIFTY only for now. SENSEX, FINNIFTY and BANKNIFTY come later, in that order.
- Contract facts:
  - NIFTY weekly expiry is Tuesday; lot 65.
  - SENSEX weekly is Thursday; lot 20.
  - BANKNIFTY and FINNIFTY are monthly only.
  - Never hardcode lot sizes.

## 1. Current strategy (champion) and what it really earns

**R6-P30 "NIFTY X7.2 ST period 30", Tradetron id 999154354** (Rishabh's pick, confirmed in Round 10). It runs LIVE AUTO on his account. NIFTY weekly (Current Week), intraday, 1 lot per leg.
- **Legs:**
  - Sell CE at `ATM SPOT("NIFTY 50", 0)`.
  - Sell PE at `ATM SPOT("NIFTY 50", -1)`.
- **Entry:** Time ≥ 09:15, the 5-minute Supertrend(30, 3) of the CE+PE combined premium is above the last closed candle's close, and the position is flat. 99% of entries fire at 09:15.
- **Exits** (Universal Exit, OR-joined):
  - the traded legs' combined premium 5m close is above its Supertrend(30, 3);
  - strategy P&L ≥ 9,000 × multiplier;
  - Time ≥ 15:18.
- **Strategy TSL:** 3,000 / 1,500 / 1,000 rupees, which means that at +3,000 the stop moves to cost.
- **Reactivation:** 360 (default), so one trade a day.

**Numbers (Open fills, 2021-11-16 to 2026-09-08, job ttbt-999129310261013, report https://tradetron.tech/bt/view/5ce54cb776efdf956259a6e660197a8f):**
- Net ₹10,43,205; ROI 580%; CAGR 48.9%; DD ₹19,773.
- Sharpe 4.23; 2,378 trades; win 65%.
- Expectancy ₹458 gross / ₹439 net per leg trade; last 12 months ₹3,37,418 net.
- On Avg fills (2021-10-13 to 2026-09-10, job ttbt-999147086261015): ₹4,05,031, DD ₹29,868.

**Why Open fills are the right basis now:**
- Live P30 on 2026-10-16 filled CE 23050 at ₹101 against a 09:15 print of ₹101.5 (09:16 was ₹87.75), and filled PE 23000 at ₹93.45.
- That is one day, not proof. Keep logging first fill vs print.
- Rounds 7 to 9 used Avg fills, which favour more trades and faster exits. On Open fills those changes lose (section 8, Round 10).

**Optional tweak:** target 12,000 (R10-TP12, id 999187942).
- +2.7% net, expectancy +3%, same DD, t 2.25, ≥ P30 in all 6 years.
- OOS 2020–21: ₹3,30,503 / DD ₹17,355.
- On Avg fills: +1.6% (t 0.56) with DD +28%.
- It is below the +5% bar, so it goes to Live Offline at most.

**Round 9 heroes are demoted:**
- R9-X3s20 (999181390) on Open: +3.5% net, DD +90%, expectancy −35%.
- R9-X1 (999180286) on Open: +4.3%, DD +30%, expectancy −35%.
- Both are behind P30 after brokerage.

## 2. Champion lineage (Open fills, so the absolute figures are inflated)

| Round | Strategy | id | Net | DD | Change |
|---|---|---|---|---|---|
| R1 | V8b | 999097430 | 748,628 | 31,772 | ATM SPOT strikes (the one statistically solid early win), TP 9000, TSL |
| R2 | W2-C6 | 999129558 | 839,708 | 24,271 | Supertrend 14/3, Friday allowed |
| R4 | AP-X7.1 | 999147870 | 1,029,978 | 25,870 | PE one strike OTM (t 2.57) |
| R5 | AP-X7.2 | 999151690 | 1,036,527 | 20,108 | Supertrend period 20 (OOS +7.6%, DD −17.5%) |
| R8 | R8-R1 | 999154822 | 1,106,391 (Avg: 464,698) | 28,935 (Avg: 31,938) | Re-entry 15 min, entries until 14:00 (Avg t 2.03, OOS +22%) |
| R9 | R9-X3s20 | 999181390 | Avg: 557,142; Open: 1,079,311 | Avg: 27,219; Open: 37,486 | Supertrend exit on 3m candles (Avg-fill crown, reversed in R10) |
| R10 | R6-P30 (reinstated) | 999154354 | 1,043,205 | 19,773 | No change: 17 one-change variants on Open fills failed the +5% bar |

## 3. What has been tested and rejected (do not re-run)

**Exits and stops**
- Hard SL (4500, 7500, 30% premium): rejected.
- TP/TSL variations: a flat plateau.
- Strategy stop −7500: passed in-sample, failed out-of-sample (DD +43%).
- Leg SL 30% and 60%: rejected.

**Supertrend settings**
- 7/2: worse.
- Multiplier 2.5 and 3.5: DD +23–25%.
- 3m candles: −11% (t −2.1).
- 10m: DD +40%.
- 15m: no gain.
- Period 20–30 is a plateau.

**Strikes**
- CE must stay ATM; CE±1 is worse.
- Strangle ±2: worse.
- Premium-matched PE: significantly worse.
- PE delta −0.30: on X7.1 it cut DD 17%, but on X7.2 net was −4% and DD +13%.

**Wings**
- 200 pt: lost most of the edge.
- 500 pt: DD doubled.

**Filters**
- VIX ≥ SMA20: −54%.
- VIX < 25 and VIX < 20: neutral or worse.
- Skipping Tuesday: worse.

**Timing**
- Entry 09:30: −70% on C6 (Open fills).
- Entry 09:16: −70%.
- Re-entry after 60 min (C6): neutral.

**Rolls**
- Theta roll of the winner at 50% (X3 on C6; R7 WR50 on Avg fills): only helps 2021–23.
- Loser cut 1.6× / 2.0×, loser cut + survivor at cost, loser roll to ATM (R7): all only help 2021–23. Never retest without a regime gate.
- Entry from 09:20 on Avg fills (R7): −11%, DD doubles.

**Round 8 signals and filters (Avg fills)**
- EMA(20) instead of Supertrend: −16% net (twice the trades; costs eat it).
- RSI(14) of premium < 40 / 45 / 50: no robust gain (t 0.57 at 45, neighbours flat). Also adds nothing on top of the 14:00 cutoff.
- Spot ADX(14) < 25: −53%, DD 78k.
- Loser cut 1.6× gated on VIX ≥ 16: still loses 2026 (₹28k vs ₹94k). Leg cuts are dead.

**Round 9 reversal exits (Avg fills)**
- India VIX +4% in 30 min exit: −21% net, DD 50k.
- Leg-skew exit (CE ≥ 2.5× PE or PE ≥ 2× CE): −11%, 9,734 trades, last 12m collapses.
- Premium 15% above its 1-hour low: −76%, whipsaw.
- 2m Supertrend exit: DD down but net flat, last 12m weak.
- 3m exit + spot 0.6% together (C1): +4% over X3s20 is noise (t 0.42) and costs more in brokerage.

**Round 10 on Open fills (vs P30; do not re-run on P30)**
- Re-entry in every form lowers expectancy and raises DD:
  - morning only (until 10:00: −2.9%; until 11:00: −4.5%; DD +36%);
  - expiry days only on TP12 (until 14:00: +0.8% vs TP12, DD +22%; until 12:00: −2.5%);
  - R8-R1 style (Open: +6%, but expectancy 380 and DD 28.9k).
- Faster exits without re-entry:
  - 3m Supertrend exit: −8.5%;
  - spot 0.6% exit: −6.9%, DD +29%.
- Wider legs CE+1 / PE−1: −7.4%, DD +21%.
- No TSL: −1.7%. Looser TSL 4500/2250/1500 on TP12: weaker than TP12.
- Exit Supertrend period 40: −0.4% (plateau).
- Target 15,000 / 20,000: +2.2% / +2.1%. This is a plateau; TP12 is best.

## 4. Pass rule (pre-register before every run)

Adopt a change only if all of these hold:
- net is +5% or better, or DD is −15% or better, vs the current base;
- a plateau neighbour agrees;
- the out-of-sample window (2020-01-01 to 2021-11-16) is not negative;
- trailing windows are positive;
- the paired daily t is no worse than −1.

Change one thing per run. Run out-of-sample before crowning anything.

## 5. Tradetron mechanics learned the hard way

**Backtest call:** `tt_backtest_strategy(strategy_id, start='2021-10-13', end='2026-10-13', type='intraday', bt_type_confirmed=True, confirm_charge=True, trade_price='Avg of Open and Close')`.
- One run is capped at 60 months (an 81-month request is refused, no charge). Use 2020-01-01 to 2021-11-16 as the separate out-of-sample run.
- Costs ₹20 per run. 60-month runs take 5 to 25 minutes on the fleet.
- The data clamps to 2026-09-08.
- Max 4 concurrent runs.
- At most 10 strategy creates per hour.

**Free reads:** `tt_backtest_result` (sections: headline, regime, sub_windows, series, timing, setwise), `tt_backtest_compare` (paired t) and `tt_backtest_trades` (raw fills).
- Asking for headline + monthly + sub_windows with caps {"sub_windows_full": true} overflows to a saved file; parse it with Python (`sections.monthly[].pnl`, `sections.sub_windows['12m'].kpi.net_pnl`).
- Index spot candles in a condition use `Instrument Name('NFO,NIFTY 50,,,,,')`; `NSE_IDX` is only for INDIA VIX.

**Sweeps:**
- R6 sweeps charged but returned no variants table. Prefer single runs.
- The search literal must be at least 2 characters ("3" is refused).
- Never sweep the "2" leg-index artifact.

**Authoring:**
- TSL fields are absolute rupees, even though the builder label says %.
- `Reactivation minutes` is a METADATA row; the minimum is 2 and the default is 360.

**Leg roll (Repair Once):**
- Condition: `LTP(Traded Instrument Name('Entry','instrument','NIFTY 50',1,1,<leg>)) <= Math Operation(Traded Instrument('Entry','price','NIFTY 50',1,1,<leg>), Number(0.5), '*')`.
- Positions:
  - B: same type, expiry `Traded Instrument Name('Entry','expiry',...)`, strike `Traded Instrument('Entry','strike',...)`.
  - S: new strike at `ATM SPOT`.
- The validator warns REENTRY_VIA_REPAIR_IN_REENTERABLE_SET. That is acceptable when reactivation is 360. For capped re-entry use the staged-set pattern instead.
- After a roll, the Universal Exit supertrend still reads the original Entry legs.

**Data coverage:**
- India VIX history starts 2022-01-03.
- OI, PCR, GEX and depth are not in backtests.
- `OHLC Sum` of rolling weekly options on day candles has no history.

**Round 10 mechanics:**
- `tt_backtest_result` returns `BT_NOT_FINISHED` cheaply for an unfinished run; use it as the poll.
- Asking for `sub_windows` with `{"sub_windows_full": true}` forces a ~2 MB overflow file, which keeps the result out of context; parse it with Python.
- The markdown grammar supports nested `- (group, OR-joined)` / `- (group, AND-joined)` bullets in Entry and Universal Exit.
- Expiry-day test: `Today('NSE')` `==` `Current Week Expiry('NIFTY 50', 0)`.
- A Supertrend "confirmation" written as `Lowest Low Value(CLOSE(...), 2)[-1] > ST[-1]` never delays an exit, because the line flips below price on the crossing bar. Compare each close with its own bar's ST instead.
- Strategy creates: 10 per rolling hour. Plan creates in batches.

## 6. Free analysis already done (do not redo)

- **X7.2 regimes by VIX:** above 25 (23 days) made only ₹3,965 at a 48% win rate. Very low, low, normal and elevated VIX were all profitable.
- **The 09:15 gap:**
  - 759 of 1,179 days show it.
  - The CE+PE open is on average 8.95 pts above the 09:16 price.
  - 48% of 09:15 prices are whole rupees, and there are some bad prints.
  - See `reports/round6/opening-fill-analysis.md`.

## 7. Known engine bug

A `## PYTHON BLOCK` with an internal time-gated `if` makes every entry fire at that gate time (all entries at 15:25).
- `tt_check_backtestability` does not catch it.
- Avoid Python blocks.

## 8. Round log

| Round | Date | Spend | Outcome |
|---|---|---|---|
| R1 | 2026-10-06/09 | ~13 runs | ATM SPOT wins (V8b) |
| R2 | 2026-10-10 | ₹280 | C6 crowned |
| R3 | 2026-10-10 | ₹80 | No change; OOS positive |
| R4 | 2026-10-12 | ₹240 | X7.1 crowned (PE skew) |
| R5 | 2026-10-12 | ₹840 | X7.2 crowned (period 20) |
| R6 | 2026-10-12/13 | ₹300 | Found the 09:15 fill dependence |
| R7 | 2026-10-13 | ₹220 | Realistic fills; leg tweaks fail recently; re-entry is the candidate |
| R8 | 2026-10-13 | ₹280 | R8-R1 crowned (re-entry + entries until 14:00) |
| R9 | 2026-10-15 | ₹280 | R9-X3s20 crowned (3m Supertrend exit); spot-exit X1 is hero 2 (both on Avg fills) |
| R10 | 2026-10-16 | ₹400 | P30 reinstated on Open fills; TP12 is the only small gain; Round 9 heroes lose on Open |

### Round 7 (Avg fills, baseline ttbt-999129342261013). Spent ₹220 on 11 runs; no crown.

| Test | id | Net vs base | DD (base 28,525) | Last 12m (base 96,320) | Verdict |
|---|---|---|---|---|---|
| E920 entry 09:20 | 999154490 | −11% | 59,157 | n/a | Rejected |
| WR50 winner roll 50% to ATM | 999154502 | +9.5% | 50,567 | 77,903 | Rejected (gains only 2021–23) |
| LC16 loser cut 1.6× | 999154506 | +26.8% | 50,297 | 42,560 | Rejected (gains only 2021–23) |
| LC20 loser cut 2.0× | 999154574 | +10.9% | 33,716 | 86,346 | Rejected |
| LCC loser cut 1.6× + survivor at cost | 999154562 | +24.7% | 35,259 | 45,810 | Rejected |
| LCR loser roll to ATM 1.6× | 999154570 | +10.6% | 31,639 | 71,925 | Rejected |
| **RE15 re-entry 15 min, until 13:00** | **999154498** | **+9.6%** | **32,870** | **129,418** | **Candidate** |
| RE30 re-entry 30 min | 999154626 | +1.4% | 32,217 | 110,501 | Neighbour, weaker |

- RE15 out-of-sample (2020-01 to 2021-11, Avg) vs X7.2 Avg out-of-sample: 130,525 vs 121,118 (+7.8%), DD +4.5%.
- **The key lesson:** fixed-trigger leg adjustments (theta roll, loser cut, loser roll) add P&L in 2021–23 and lose it in 2025–26. Do not hard-code them. Gate them on a regime (VIX, or the live OI/CVD/GEX overlay).
- **Re-entry** is the only change better in every trailing window.
- **Next:** see `reports/round7/round8-brainstorm-plan.md`.
- **Results reports:**
  - E920 https://tradetron.tech/bt/view/312a0f76bff70fb13b547e7fa4ce11eb
  - WR50 https://tradetron.tech/bt/view/2968f65ddc3c34c7b5381b582feb0433
  - LC16 https://tradetron.tech/bt/view/ae7a20806f8ada97c2f2b5de017cc2ea
  - LC20 https://tradetron.tech/bt/view/5536f5d5e1ad8dc0906c1235f3233c9e
  - LCC https://tradetron.tech/bt/view/6b6e453eaa4d238d68970bfb316f43ac
  - LCR https://tradetron.tech/bt/view/636a0b48f166f1c37cd9a37da6a5e47f
  - RE15 https://tradetron.tech/bt/view/b26a3575ce647d26b0998e026271623d
  - RE15 OOS https://tradetron.tech/bt/view/fc0834b12aaef00907878a9add72227e
  - RE30 https://tradetron.tech/bt/view/3372271bf21acb821850dc181e3f2d37

### Round 8 (Avg fills, 60-month window 2021-10-13 to 2026-10-13). Spent ₹280 on 14 runs; R8-R1 crowned. Final backtest round.

| Test | id | Net | DD | Last 12m | Verdict |
|---|---|---|---|---|---|
| B0 X7.2 | 999151690 | 382,980 | 28,525 | n/a | Base |
| B1 RE15 | 999154498 | 420,316 | 32,870 | 129,418 | Reference |
| **R1 entries until 14:00** | **999154822** | **464,698** | **31,938** | **145,260** | **Champion: t 2.03 vs RE15; OOS 159,252 (+22%, t 2.56)** |
| R1b until 14:30 | 999154974 | 463,784 | 33,855 | 149,445 | Neighbour agrees |
| R2 re-entry 10 min until 14:00 | 999155130 | 471,647 | 29,770 | 152,961 | Neighbour agrees (t 0.39 vs R1) |
| S1 EMA20 signal | 999154798 | 353,455 | 25,155 | 102,732 | Rejected |
| S2 RSI<45 | 999154802 | 443,474 | 34,794 | 149,268 | Rejected (t 0.57; neighbours flat) |
| S2 RSI<40 / <50 | 999154898 / 999154902 | 414,507 / 420,126 | 30,631 / 36,231 | 138,620 / 143,297 | No gain |
| C1 RSI<45 + 14:00 | 999154970 | 469,866 | 33,212 | 148,284 | Rejected (+1.1% vs R1) |
| S3 spot ADX<25 | 999154826 | 197,044 | 78,107 | 53,970 | Rejected |
| G1 VIX-gated loser cut | 999154814 | 462,242 | 59,147 | 63,423 | Rejected (2026 collapses) |

- **Lesson:** more time in the market (re-entry, later cutoff) is the only thing that improved every window; every trade-removing filter did nothing or hurt.
- **Decision:** backtesting is closed for NIFTY. Next is Live Offline for 10–20 sessions on 999154822, logging 09:15 and re-entry fills, then Rishabh's own go-live step.
- **Full write-up:** `reports/round8/round8-results-and-champion.md`. Job ids in that file and in the workbook.

### Round 9 (Avg fills, 2021-10-13 to 2026-09-10). Spent ₹280 net; R9-X3s20 crowned.

Asked for: detect reversals earlier, exit, re-enter at the new ATM after the move.

| Test | id | Net | DD | Last 12m | Verdict |
|---|---|---|---|---|---|
| B1 P30 + RE15 + 14:00 | 999180290 | 475,398 | 30,888 | 140,471 | Base |
| X3 3m exit (ST 30) | 999180322 | 521,352 | 25,831 | 132,514 | Neighbour agrees; OOS 135,444 |
| X3n2 2m exit | 999181386 | 472,155 | 22,841 | 107,431 | DD-down neighbour |
| **X3s20 R8-R1 + 3m exit** | **999181390** | **557,142** | **27,219** | **147,911** | **Champion (t 1.71; OOS 146,062 / DD 18,509)** |
| X1 spot ±0.6% exit | 999180286 | 550,966 | 27,212 | 127,314 | Hero 2 (OOS 207,380 / DD 15,447; weak 2025) |
| X1n8 spot ±0.8% | 999182578 | 510,675 | 29,936 | 128,094 | Neighbour agrees |
| C1 3m + spot 0.6% | 999182570 | 579,940 | 24,736 | 125,823 | Not adopted |
| X2 leg skew | 999180294 | 422,325 | 26,930 | 58,213 | Rejected |
| X4 VIX jump | 999180330 | 375,894 | 50,203 | 79,116 | Rejected |
| X5 premium bounce | 999180338 | 112,470 | 31,678 | 11,084 | Rejected |

- **Lesson:** no signal predicts a reversal; a faster exit on the same signal catches it earlier, and the 15-minute re-entry re-sells the new ATM. Exit-only timeframe changes help where whole-strategy timeframe changes hurt.
- **Win rate** stayed at 60–62% on every serious variant; gains came from smaller losers.
- **Mechanics learned:** backtest end must be ≥ 35 days before today; `tt_backtest_status` lags, use `tt_backtest_trades(job, limit=1)` `book_state` and then `tt_backtest_result`; fleet runs took 1.5–3 hours this round.
- **Next:** Live Offline on 999181390 (needs NFO enabled on the Zerodha connection in Tradetron first).
- **Full write-up:** `reports/round9/round9-master-plan.md`, `reports/round9/round9-results-and-heroes.md`.

### Round 10 (Open fills, 2021-11-16 to 2026-09-08, the window of Rishabh's P30 report). Spent ₹400 of ₹600 on 20 runs; P30 stays.

Asked for: a much stronger variant than P30 (better ROI, CAGR and expectancy per trade; DD not much worse); a master sheet; width variations; and practitioner ideas.

| Test | id | Net | vs P30 | DD | Net/trade | Verdict |
|---|---|---|---|---|---|---|
| **P30** | **999154354** | **1,043,205** | — | **19,773** | **439** | **Champion** |
| TP12 target 12,000 | 999187942 | 1,071,606 | +2.7% (t 2.25) | 19,773 | 452 | Best; below the bar; Avg stress DD +28% |
| TP15 | 999188406 | 1,066,528 | +2.2% | 19,773 | 450 | Neighbour |
| TP20 | 999188490 | 1,065,021 | +2.1% | 19,773 | 450 | Neighbour |
| TP12w looser TSL | 999188498 | 1,057,866 | +1.4% | 19,773 | 447 | Worse than TP12 |
| E5a TP12 + expiry-day RE until 14:00 | 999188706 | 1,079,805 | +3.5% | 24,063 | 418 | Rejected |
| E5b until 12:00 | 999188710 | 1,044,463 | +0.1% | 24,843 | 424 | Rejected |
| X1 on Open | 999180286 | 1,088,551 | +4.3% | 25,779 | 285 | Rejected |
| X3s20 on Open | 999181390 | 1,079,311 | +3.5% | 37,486 | 284 | Rejected |
| C2 2-close confirm | 999188398 | 1,042,339 | −0.1% | 19,773 | 438 | No effect (construction) |
| X40 exit period 40 | 999188494 | 1,039,176 | −0.4% | 19,773 | 437 | Plateau |
| NT no TSL | 999187950 | 1,025,632 | −1.7% | 20,537 | 432 | Rejected |
| E1b RE15 until 10:00 | 999188058 | 1,012,767 | −2.9% | 27,017 | 421 | Rejected |
| E1 RE15 until 11:00 | 999188054 | 995,980 | −4.5% | 26,816 | 392 | Rejected |
| T2 spot 0.6% exit | 999187930 | 971,166 | −6.9% | 25,506 | 405 | Rejected |
| W2 CE+1 / PE−1 | 999187938 | 965,545 | −7.4% | 23,894 | 399 | Rejected |
| T1 3m exit | 999187926 | 954,720 | −8.5% | 18,704 | 383 | Rejected |
| W1 CE0 / PE−2 | 999187934 | pending | | | | |

- **Lesson:** P30's edge is one 09:15 sale of the rich opening premium held until the trend turns. On Open fills, every change that trades more or exits sooner lowers expectancy. The fill basis decides which variant looks best, so from now on report Open and Avg side by side.
- **Next real levers (new round, Rishabh decides):**
  - the same rules on SENSEX weekly as a second book;
  - far wings (≥ 1,000 pt) for margin efficiency, with margin checked live.
- **Write-up:** `reports/round10/round10-master-plan.md`, `reports/round10/round10-results-and-champion.md`, `reports/round10/round10-strategy-master-sheet.xlsx`.

## 9. Where everything lives

- **Workbook** (all rounds, report links): `/mnt/project-files/reports/nifty-master-research-workbook.xlsx`
- **Narrative report:** `/mnt/project-files/reports/tradetron-straddle-risk-variants.md`
- **Round 7 plan:** `/mnt/project-files/reports/round7/round7-master-plan.md`
- **Round 9 plan and results:** `/mnt/project-files/reports/round9/round9-master-plan.md`, `/mnt/project-files/reports/round9/round9-results-and-heroes.md`
- **Round 10 plan, results and master sheet:** `/mnt/project-files/reports/round10/round10-master-plan.md`, `/mnt/project-files/reports/round10/round10-results-and-champion.md`, `/mnt/project-files/reports/round10/round10-strategy-master-sheet.xlsx`
- **Reusable skill (portable):** `/mnt/project-files/knowledge/skills/options-strategy-alpha-loop/SKILL.md`
- **Round 8 plan and results:** `/mnt/project-files/reports/round8/round8-final-master-plan.md`, `/mnt/project-files/reports/round8/round8-results-and-champion.md`
- **Live overlay plan** (OI, PCR, GEX, CVD leg rules): `/mnt/project-files/reports/round7/live-overlay-plan.md`
- **R4/R5 sheets:** `reports/alpha-pro-master-sheet.csv`, `reports/nifty-round5-master-sheet.csv`
- **Repo copy:** `docs/NIFTY_RESEARCH_LEDGER.md` (PR #15 for R7; Round 8 update in a new PR). Update it after each round too.
- **Memory pointers:** `tradetron-straddle-risk-variants`, `tradetron-research-loop-protocol`

## 10. How a new thread should start

1. Read this file.
2. Read section 8 for the latest round and its pending items.
3. Check the wallet with `tt_wallet_balance`, state a budget, then run.
4. After each round:
   - update section 8 here;
   - append rows to the workbook (scripts in the session scratchpad are temporary; the workbook itself is the record);
   - update the memory one-liners.
