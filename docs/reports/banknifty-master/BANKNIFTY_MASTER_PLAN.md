# 🏛️ BANK NIFTY — God-Level Strategy Master Plan
### A full research universe for a great Bank Nifty alpha strategy on Tradetron

**Author desk:** quant + options trader + sceptical reviewer (one agent).
**Owner:** Rishabh. **Date:** 2026-10-21. **Platform:** Tradetron (plain condition keywords only — no Python blocks).
**Objective (Rishabh's words, ranked):** LOW drawdown → HIGH win-rate → good expectancy-per-trade → good net ROI → good Calmar.

> This replaces the "keep tweaking one inside-day strangle" approach. It is a map of the *whole* Bank Nifty option-strategy space, filtered for what today's market structure allows and what Tradetron can actually build and backtest, then ordered into credit-efficient research rounds.

---

## 1. Market structure as of Oct 2026 — what changed and why it reshapes everything

These are the facts that decide which strategies are even possible. Sourced from NSE/SEBI circulars and Zerodha bulletins (see research appendix).

| Fact | Detail | Design consequence |
|---|---|---|
| **Weekly expiry gone** | SEBI 1-weekly-per-exchange rule (eff. 20 Nov 2024). NSE kept weeklies on **Nifty only**. Bank Nifty's last weekly was 13 Nov 2024. | **Bank Nifty is a MONTHLY product.** All classic 9:20 0DTE / weekly-theta scalps are dead on BN. Expiry events dropped from ~52/yr to ~12/yr. Think in **monthly DTE cycles**, not expiry-day gamma. |
| **Expiry day = last TUESDAY** | NSE moved Thu→Tue (Tuesday regime from ~2 Sep 2025). | Tradetron `Current Month` token resolves this automatically — never hardcode the weekday. |
| **Lot size = 35** | History 25→15→25→30→**35** (eff. 25 Apr 2025). ⚠️ **CLAUDE.md §6 still says 15 — STALE.** | Backtest P&L is per-1-lot and scales linearly, so backtests are unaffected. But real sizing/margin uses 35. **Flagged for Rishabh to confirm before I correct the repo spec.** We never hardcode lots. |
| **STT on sold options ↑** | 0.0625% → **0.1% of premium** (eff. 1 Oct 2024). | Higher friction on high-turnover selling. Always add brokerage **and** recheck STT in the cost model for churny variants. |
| **Expiry-day margin** | +2% ELM on short options on expiry day; calendar-spread margin benefit removed on the expiring leg (Feb 2025). | Holding naked shorts into monthly expiry Tuesday is more expensive — favour defined-risk or square-off before expiry. |
| **Volatility regime** | India VIX ~14–15, 52wk ~8.7–28.9. Structurally **calmer** than 2021–23. | Premium-selling tailwind, but thinner premiums; filters that need high VIX fire rarely. |
| **Microstructure** | Strike step **100**; higher premium/gamma/vega than Nifty; liquidity concentrated in **monthly ATM** — far-OTM monthly strikes are thin (wide spreads, poor fills). | This is *exactly* the COVERAGE_PARTIAL caveat we keep hitting. Prefer near-ATM and **delta-based** strikes over far fixed-point OTM. Defined-risk wings must sit where there's liquidity. |
| **Event edge** | RBI MPC / bank earnings (HDFC, ICICI, SBI, Kotak, Axis) drive outsized BN moves. | A genuine, bank-specific volatility edge Nifty doesn't have — worth a dedicated event overlay. |

**The headline implication:** Bank Nifty's edge today is **monthly premium decay in a calm-VIX regime, harvested with defined or tightly-stopped risk, near the liquid ATM**, plus a smaller **intraday directional** book to diversify the seller's left tail. That is what this plan is built around.

---

## 2. What we already know (don't re-run these)

From v1/v2 Bank Nifty rounds and 11 rounds of NIFTY straddle research:

- **The stop is the alpha lever, not the exit indicator.** A tight ₹2000 PnL stop (champion A1_SL2000, id 999197478) gave the best Calmar (1.75) / DD (₹19.5k) of everything tried.
- **Combined-premium exit (1.5×) works** — highest win-rate (70–71%), smoothest % curve — but on *rupee* DD it does **not** beat a tight PnL stop. (C1_T2000_CP150, id 999197802.)
- **Trade-removing filters hurt short premium** (ADX<25 entry cut net −28%).
- **Re-entry raises net but ~2× DD and 2× turnover** (brokerage-fragile).
- **Supertrend on the *traded strangle* premium is unreliable** — illiquid short strikes can't be priced (confirmed by the Tradetron map: combined-premium candle has open/close only, no high/low). Put Supertrend on **futures**, not on the sold premium.
- **The prior-day H/L strike rule is real alpha** for the inside-day strangle; fixed ATM lost −58%.
- **Realistic fills matter:** always backtest `trade_price='Avg of Open and Close'`; Open fills inflate short premium 2–3×.

These become priors, not experiments.

---

## 3. The strategy universe — 10 families

Each family has its own sheet block in `BankNifty_Master_Sheet.xlsx` / `.csv` with every variant. Below is the rationale, the core rules, and the Tradetron buildability for each. **Priority** reflects fit to Rishabh's objective (low DD + high win first).

### SELLERS (premium collection — the core book)

**F1 · Iron Fly (defined-risk ATM straddle) — PRIORITY 1**
Short ATM CE+PE + long OTM wings. Max loss is capped by the wings → mechanically low DD, directly serving goal #1. Research says collect ≈⅓ of wing width, close at 50% max profit.
- Entry: inside-day gate (reuse our alpha) OR plain 09:30; flat. Exit: 15:15 square-off, or combined-premium 1.5× stop, or 50% credit booked.
- TT: legs via `ATM SPOT('NIFTY BANK', N)` (N in strike-steps); wings ±3/5/7 steps. One ATM anchor throughout (validator rule). Buildable, clean.

**F2 · Iron Condor (delta-0.15 shorts + wings) — PRIORITY 1**
Wider breakevens than the fly, higher win-rate, still defined-risk. Roll untested side when tested short-delta hits ~0.30.
- TT: shorts via `Find Strike('NIFTY BANK', Select Expiry('month',0), 'delta', Number(±0.15), 'CE'/'PE', 'any')`. **Caveat:** `'any'` is unbounded and Find Strike can silently drop a leg if it returns none → put the long wings in their **own set entered first** and gate the shorts on their fill. Verify the monthly expiry token by lookup at build time.

**F3 · Short Strangle by Delta — PRIORITY 2**
Our v2 strangle used prior-day H/L strikes; this swaps in **delta-selected** strikes (0.10/0.15/0.20) — the institutional default — with our proven combined-premium 1.5× stop. Tests whether delta strikes beat the prior-H/L rule.
- TT: Find Strike as F2; same leg-drop guard.

**F4 · ATM Short Straddle + re-center — PRIORITY 2**
Classic ATM straddle with the two documented stop styles: (a) per-leg 30% SL (exit only the stopped leg, winner runs), (b) combined-premium 1.3×/1.5× stop + **re-center** at new ATM (capped re-entries via a runtime counter). Delta-neutral recenter on a 150-pt spot move is a variant.
- TT: per-leg SL anchored `cond_type='Entry'` (critical — self-anchor never arms). Re-center cap via `Init Var`/`Get Runtime Number`. Spot move via `EntryUnderlyingPrice('NIFTY BANK')`.

**F5 · Inside-Day Strangle extensions (carry the existing champion) — PRIORITY 2**
Build on A1_SL2000 rather than abandon it: (a) **convert to an inside-day iron fly** (cap the −2000 tail with wings → lower DD), (b) add a VIX regime gate, (c) add the spot-distance recenter (I2, already authored id 999197474, never run).
- TT: all buildable; I2 is ready to run.

### DIRECTIONAL (intraday buying / spreads — the diversifier book)

**F6 · Supertrend / ADX trend-following → debit spread — PRIORITY 3**
Signal on **BN futures** (ST SMA 10/3 on 5m is the community default), buy ATM/1-ITM in the trend, or a debit spread to cut theta. Documented win-rate is low (~40%) but RR ~3.5 — a different, negatively-correlated profile that cushions the seller's trend-day losses.
- TT: `ST SMA(Symbol(Futures('NIFTY BANK'),'5m','All'),10,3)` read via `Position(...,-1)`; ADX via `ADX(Symbol(...),14)`. Buildable. Put ST on futures, NOT on sold premium.

**F7 · Opening Range Breakout → defined-risk — PRIORITY 3**
15-min (09:15–09:29) / 30-min range; buy ATM on a close beyond the range, opposite-edge stop, 1:2 target, 15:00 square-off. Debit-spread version for defined risk.
- TT: `ORB(Instrument Name('NFO,NIFTY BANK,,,,,'),'High','09:15','09:28')`; **must gate behind `Time('NSE') > Number('929')`** and set end_time one minute short, or it returns null.

**F8 · VWAP reclaim / rejection — PRIORITY 4**
Reclaim-long / rejection-short on **BN futures** (VWAP has no data on index spot — no volume), optional RSI(9) 38–58 filter, best window 09:50–11:30.
- TT: `VWAP(Futures('NIFTY BANK'))` vs `LTP(Futures('NIFTY BANK'))`. Buildable on futures only.

**F9 · Prior-day H/L breakout + Gap — PRIORITY 4**
PDH/PDL 15-min-close breakout buy; gap-up continuation / gap-fail fade; ORB+PDH/PDL confluence.
- TT: prior-day levels from **day candles** `Position(HIGH(Symbol(...,'day','All')),-1)` (the `Previous Close` keyword is NOT backtestable). Gap = today-open(0) vs prior-close(-1) via Math Operation.

### OVERLAYS (apply to the best base from each book)

**F10 · Volatility / Event overlays — PRIORITY 4**
(a) India VIX regime gate (sell only when VIX in a 12–20 band), (b) VIX-expansion exit (VIX +4% vs 30m ago → cut shorts), (c) RBI-policy-day long straddle (event vol).
- TT: VIX via `Instrument Name('NSE_IDX,INDIA VIX,,,,,')` — condition-only, but **does** backtest (minute bars from 2020). RBI-day needs a date list → flag feasibility before spending.

---

## 4. Risk-management framework (applies to every variant)

A strategy is entry + exit + stop + repair + sizing + regime. Every variant must specify all six.

- **Entry:** time gate (`Time('NSE') >= Number('930')`), regime/structure condition (inside-day, ST flip, ORB break, VIX band), and `Positions Detail(...)==0` flat-check. Entries-until cutoff for intraday (`Time < Number('1500')`).
- **Exit (profit):** 50% credit for defined-risk sellers; 1:2 for directional; combined-premium decay to 0.6× for straddles; hard time exit 15:15–15:20.
- **Stop (loss):** the proven lever. Sellers → tight PnL stop (₹2000-class, scaled by `Multiplier()`) **or** defined-risk wings. Directional → opposite range edge / structure stop. Combined-premium K× as a secondary.
- **Repair / adjustment:** roll untested condor side at short-delta ~0.30; re-center straddle on 150-pt move or net-delta band (`Net Delta('NIFTY BANK')`); per-leg trail **anchored `cond_type='Entry'`**, Repair-Continuous gated by its own runtime flag (or it loops → Blocked).
- **Runtime variables:** re-entry cap counter (`Init Var set1count=0` → `Get Runtime Number('set1count') < Number(N)`); "stop for the day after N losing exits"; freeze opening-range level at entry. Always compare `Get Runtime Number` explicitly (0/unset reads false).
- **Sizing / portfolio heat:** per CLAUDE.md, max 3 hedged + 3 naked/day; defined-risk variants count as hedged. We never recommend capital/lots/multiplier — P&L is per-1-lot and scales.
- **Cost realism:** `Avg of Open and Close` fills; add ~₹20/order brokerage by hand; re-check the 0.1% sell-STT on churny variants; monthly-expiry +2% ELM if held to expiry.

---

## 5. Research rounds, budget & pass rules

₹20 per backtest. No hard cap from Rishabh, but credit-frugal: **≤ 4 runs in flight, each round gated on the previous, stop a family after two no-pass batches.** Suggested staging (adjustable):

| Round | Families | Runs | ~Spend | Goal |
|---|---|---|---|---|
| A — Defined-risk core | F1 iron fly, F2 condor, F5.2 inside-day fly | 8–10 | ₹160–200 | Find the lowest-DD seller that holds net |
| B — Strike & adjustment | F3 delta-strangle, F4 straddle+recenter | 6–8 | ₹120–160 | Beat the prior-H/L strike; test re-centering |
| C — Directional diversifier | F6 ST/ADX spread, F7 ORB | 6–8 | ₹120–160 | A negatively-correlated book for trend days |
| D — Overlays & robustness | F10 VIX gate, best-of neighbours, OOS 2020–22, brokerage | 6–8 | ₹120–160 | Confirm the survivors; blend a portfolio |
| **Total (staged)** | | **~30** | **~₹600** | Only spent if each round earns the next |

**Pass rule (pre-registered — adopt a change only if ALL hold vs the current base):**
1. Net +5% with max DD no worse than +10%, OR max DD −15% with net no worse than −5%.
2. At/above base in most calendar years AND the last 12 months.
3. A neighbour value agrees (no lone peaks).
4. Out-of-sample (2020–2022, never tuned) not negative / not clearly worse.
5. Paired daily t reported; t≥2 real, 1–2 needs OOS support, <−1 rejects.
6. After brokerage + 0.1% STT it still wins.
7. No high-severity caveat touching net/DD/trades (a jump >50% or Sharpe >5 → inspect fills first).

**Ranking for the crown (Rishabh's objective):** among passers, rank by **Calmar first, then DD (rupee), then win-rate, then net** — not by headline net. A high-net high-DD variant (like R1 re-entry) does not win.

---

## 6. Deliverables each round
1. Round plan (pre-registered) → this file family.
2. Master sheet row per variant (planned, run, rejected) in `BankNifty_Master_Sheet.xlsx`.
3. Results workbook (like the v2 one): Summary, All Runs, Exit Attribution, Champion, Per-Year, Methodology.
4. Updated ledger `knowledge/BANKNIFTY_V2_LEDGER.md` (champion, rejected, mechanics).
5. Hero candidates (1–3): rules in plain English, net/DD/win/Calmar/t/OOS, and the one reason each might fail.
6. Live Offline plan — going live is Rishabh's own step.

---

## 7. Looping prompt (paste to resume any round)

> Run the next round of the Bank Nifty master plan. Read `reports/banknifty-master/BANKNIFTY_MASTER_PLAN.md`, `reports/banknifty-master/BankNifty_Master_Sheet.xlsx`, and `knowledge/BANKNIFTY_V2_LEDGER.md` first; never re-run a tested idea. Pick the highest-priority unstarted family/variants from the sheet. Write the round's pre-registered pass rule and budget before spending. Author one-change variants with plain condition keywords only (no Python); for any keyword whose exact shape you are not certain of, call `tt_find_keyword`/`tt_lookup_keyword` and copy the example; `tt_validate_markdown` then `tt_create_strategy` (≤10 creates/hr). Backtest `trade_price='Avg of Open and Close'`, window ending ≥35 days before today, ≤4 runs in flight; verify each run with `tt_backtest_trades(job_id,limit=1)`. Read each result free, judge against the rule, record every row in the sheet. Rank survivors by Calmar→DD→win→net. Run neighbours + OOS 2020–22 for anything that passes. Add brokerage (~₹20/order) and re-check 0.1% sell-STT on churny variants. Stop a family after two no-pass batches. Update the ledger, sheet and a results workbook, then report hero candidates. No capital/lot/multiplier advice; Live Offline first; going live is Rishabh's step. Bank Nifty = monthly expiry (`Current Month`), lot 35, strike step 100 — never hardcode lots.

---

## 8. Open questions for Rishabh (not blockers — I'll proceed on defaults)
1. **Lot size:** research says current BN lot = **35** (CLAUDE.md §6 says 15). Backtests don't care (per-lot scaling), but want me to correct the repo spec? *(Default: leave it, flag only.)*
2. **Book preference:** pure defined-risk sellers (lowest DD), or a blended seller + directional book (smoother across regimes)? *(Default: build both, let the numbers decide.)*
3. **Hold style:** intraday square-off only, or allow multi-day positional monthly holds (bigger theta, overnight gap risk)? *(Default: start intraday, test positional in Round B.)*

Everything else proceeds on the defaults above.
