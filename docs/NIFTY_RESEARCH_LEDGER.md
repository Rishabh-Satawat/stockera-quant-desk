> Copy of the canonical ledger kept in project files at `/mnt/project-files/knowledge/NIFTY_RESEARCH_LEDGER.md`. Update both after each research round.

# NIFTY straddle research ledger (canonical, read this first)

This is the single source of truth for the Tradetron NIFTY short-straddle research. Any new thread should read this file before doing anything else.

- Last updated: 2026-10-13 (Round 7 done).
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

**AP-X7.2, Tradetron id 999151690.** NIFTY weekly (Current Week), intraday, 1 lot per leg.
- **Legs:**
  - Sell CE at `ATM SPOT("NIFTY 50", 0)`.
  - Sell PE at `ATM SPOT("NIFTY 50", -1)` (one strike below ATM).
- **Entry:** Time ≥ 09:15, the 5-minute Supertrend(20, 3) of the CE+PE combined premium is above the last closed candle's close, and the position is flat.
- **Exits** (Universal Exit, OR-joined):
  - the combined premium closes above its Supertrend(20, 3) on 5-minute candles;
  - strategy P&L ≥ 9,000 × multiplier;
  - Time ≥ 15:18.
- **Strategy TSL:** 3,000 / 1,500 / 1,000, in rupees.
- **Reactivation:** 360 min, which means one trade per day.

**Read this before quoting any number.** The ₹10.4 lakh backtest relies on selling at the Open print of the 09:15 bar.
- Realistic fills (trade_price "Avg of Open and Close"; Close is identical on the fleet): **net ₹3,78,871, DD ₹28,525, Sharpe 1.65.** Job ttbt-999129342261013, report https://tradetron.tech/bt/view/556588b40163c5b44bf09d47c5834237
- Entry one minute later (09:16) with Open fills: net ₹3,10,821.
- **From Round 7 on, every backtest uses Avg fills and is compared to ttbt-999129342261013.**
- Live Offline fill logging at 09:15 is the real test of whether the opening edge exists.

## 2. Champion lineage (Open fills, so the absolute figures are inflated)

| Round | Strategy | id | Net | DD | Change |
|---|---|---|---|---|---|
| R1 | V8b | 999097430 | 748,628 | 31,772 | ATM SPOT strikes (the one statistically solid early win), TP 9000, TSL |
| R2 | W2-C6 | 999129558 | 839,708 | 24,271 | Supertrend 14/3, Friday allowed |
| R4 | AP-X7.1 | 999147870 | 1,029,978 | 25,870 | PE one strike OTM (t 2.57) |
| R5 | AP-X7.2 | 999151690 | 1,036,527 | 20,108 | Supertrend period 20 (OOS +7.6%, DD −17.5%) |

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

## 4. Pass rule (pre-register before every run)

Adopt a change only if all of these hold:
- net is +5% or better, or DD is −15% or better, vs the current base;
- a plateau neighbour agrees;
- the out-of-sample window (2020-01-01 to 2021-11-15) is not negative;
- trailing windows are positive;
- the paired daily t is no worse than −1.

Change one thing per run. Run out-of-sample before crowning anything.

## 5. Tradetron mechanics learned the hard way

**Backtest call:** `tt_backtest_strategy(strategy_id, start='2021-11-16', end='2026-10-06', type='intraday', bt_type_confirmed=True, confirm_charge=True, trade_price='Avg of Open and Close')`.
- Costs ₹20 per run.
- The data clamps to 2026-09-07.
- Max 4 concurrent runs.
- At most 10 strategy creates per hour.

**Free reads:** `tt_backtest_result` (sections: headline, regime, sub_windows, series, timing, setwise), `tt_backtest_compare` (paired t) and `tt_backtest_trades` (raw fills).

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

## 9. Where everything lives

- **Workbook** (all rounds, report links): `/mnt/project-files/reports/nifty-master-research-workbook.xlsx`
- **Narrative report:** `/mnt/project-files/reports/tradetron-straddle-risk-variants.md`
- **Round 7 plan:** `/mnt/project-files/reports/round7/round7-master-plan.md`
- **Live overlay plan** (OI, PCR, GEX, CVD leg rules): `/mnt/project-files/reports/round7/live-overlay-plan.md`
- **R4/R5 sheets:** `reports/alpha-pro-master-sheet.csv`, `reports/nifty-round5-master-sheet.csv`
- **Memory pointers:** `tradetron-straddle-risk-variants`, `tradetron-research-loop-protocol`

## 10. How a new thread should start

1. Read this file.
2. Read section 8 for the latest round and its pending items.
3. Check the wallet with `tt_wallet_balance`, state a budget, then run.
4. After each round:
   - update section 8 here;
   - append rows to the workbook (scripts in the session scratchpad are temporary; the workbook itself is the record);
   - update the memory one-liners.
