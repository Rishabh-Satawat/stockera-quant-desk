# BankNifty strangle research ledger (canonical, read this first)

Single source of truth for the Tradetron **BankNifty inside-day short strangle** research.
This is SEPARATE from the NIFTY straddle work (see NIFTY_RESEARCH_LEDGER.md) — different instrument, different structure.

- Last updated: 2026-10-17 (Round 1 done: champion V3 — cut hard stop ₹3,000 → ₹2,000; −24% DD, net flat-to-+10% within noise).
- Owner: Rishabh.

## 0. Standing instructions from Rishabh (do not break)
- Never recommend capital, lot count or multiplier. Going live is Rishabh's own step; mention Live Offline once per result.
- Move fast, do not waste credits. Plan first, state budget, then run. Prefer free reads.
- No Python blocks in Tradetron strategies (engine bug).
- Repo stays PUBLIC; no account ids/secrets pushed without asking.
- Contract facts: BankNifty lot 15; monthly only (weekly discontinued). Never hardcode lot sizes.

## 1. Champion candidate (Round 1)

**V3 "BNF IDStrangle V3 Sym2000", id 999195686.** NIFTY BANK monthly, intraday, 1 lot/leg.
- **Only change vs Rishabh's file (10398878): hard stop −₹3,000 → −₹2,000.** Everything else identical.
- Legs: sell CE at Round(prior-day HIGH,100); sell PE at Round(prior-day LOW,100).
- Entry: Time ≥ 09:30, inside day (open inside yesterday's range), position flat.
- Exit: Time ≥ 15:20 OR P&L ≥ +2000×mult OR P&L < −2000×mult. Reactivate 120 min.

**Numbers (4-yr 2022-09-12 to 2026-09-12, Open fills, 1 lot, job ttbt-999158706261017):**
- Net ₹2,08,163; Max DD ₹20,250; Sharpe 1.97; Sortino 2.86; PF 1.16; expectancy ₹153; 67% win-days; 1,860 trades.
- Report: https://tradetron.tech/bt/view/6d6b1fcc93fb98525c1a2257ff6a881b

**Safest alternative — V4 (TP1500/SL2000, id 999195690):** net ₹1,98,427, DD ₹16,595 (−38% vs base), Sharpe 1.97. Report e45f6d96c75715a647908be984739b7d.

**Baseline (Rishabh's file, 4-yr, job ttbt-999158638261017):** net ₹1,89,469; DD ₹26,758; Sharpe 1.65; PF 1.15; exp ₹141; 70% win-days; 1,882 trades. Report 67b49d0012bb921259004274ea433412.

## 2. The finding
The ₹3,000 stop was the one weakness. Stop sweep at TP2000 is a clean inverted-U peaking at SL2000:
SL1500 net 146,592 / SL2000 net 208,163 / SL2500 net 196,296 / SL3000 net 175,438.
DD falls monotonically as the stop tightens (3000→2000); below 2000 net collapses.

**Significance:** paired t vs base is t=0.53 (V3) / 0.30 (V4) — the net gain is WITHIN NOISE, not proven.
The DD reduction (−24% / −38%) is the real, mechanical win (tighter stop caps per-trade loss). Sharpe 1.65→1.97.

## 3. Rejected this round (do not re-run)
- Looser stop 3000/3500: net −7% to −12%, DD worse.
- Stop 1500: too tight, net −23%.
- Wider strikes +100pt: net −9%.
- **Fixed ATM±300 strikes: net −58%, Sharpe 0.84. The alpha IS the prior-day H/L strike rule — never replace it.**
- Entry 09:45: net −16%.
- No re-entry (react 360): net −21% (but highest per-trade expectancy ₹165 and 73% win-days).

## 4. Data quality
- All runs carry COVERAGE_PARTIAL (high severity): 4 sessions absent, 5 skipped.
- 1,572 prior-day-H/L strikes were unpriceable (illiquid BankNifty monthly chains). Comparison is apples-to-apples (same caveat both sides) but absolute ₹ are a slight over-count.
- BankNifty monthly option data available back to 2022-09 on the Tradetron fleet engine.

## 5. Tradetron mechanics (BankNifty)
- Strike as formula: `Round(Position(HIGH(Symbol(Instrument Name('NFO,NIFTY BANK,,,,,'),'day','All')),-1),100)`.
- `ATM SPOT("NIFTY BANK", N)` works (N×100 pts offset); warns ATM_KEYWORD_WRONG_FOR_EXPIRY (benign, spot vs futures).
- Backtest: strategy_id, start/end (end ≤ today−35), type=intraday, trade_price='Open', confirm_charge. ₹20/run, fleet ~1 min.
- Create rate limit: 10 strategies/hour.
- Capital field is display-only; P&L = f(lots), scales linearly. Backtests ran at 1 lot.

## 6. Round log
| Round | Date | Spend | Outcome |
|---|---|---|---|
| R1 | 2026-10-17 | ₹220 | Champion V3 (stop 3000→2000). 11 runs. Strikes/timing/re-entry all rejected. |

## 7. Plan ahead
1. Deploy V3 (or V4) Live Offline 10–20 sessions.
2. Choose V3 (return) vs V4 (−38% DD).
3. Trailing-stop-to-cost test.
4. High-VIX regime filter.
5. Out-of-sample 2020–2022.
6. Confirm BankNifty chain coverage with Tradetron support.

## 8. Where everything lives
- Workbook: `/mnt/project-files/reports/banknifty/BankNifty_InsideDay_Strangle_Workbook_R1.xlsx`
- Round 1 report: `/mnt/project-files/reports/banknifty/round1-inside-day-strangle.md`
- Repo copies under `docs/`.

## 9. Strategy ids created this round
V1 999195678 · V2 999195682 · V3 999195686 (champion) · V4 999195690 · V6 999195698 · V7 999195702 · V8 999195706 · V9 999195710 · V10 999195770 · V11 999195774. Baseline 10398878.
