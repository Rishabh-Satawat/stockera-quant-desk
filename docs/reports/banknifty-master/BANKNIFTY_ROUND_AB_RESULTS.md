# BankNifty Rounds A & B — Backtest Results & Report Links

Window 2022-09-12 → 2026-09-12 · Avg-of-Open/Close fills · 1 lot · intraday · figures **NET** of costs.
All runs carry a COVERAGE_PARTIAL (high-severity) caveat from a few illiquid far-OTM monthly strikes — the same caveat on both sides, so comparisons are apples-to-apples. Report NET, never gross.

**Champion (baseline):** `BNF IDStrangle v2 A1_SL2000` — strategy id 999197478 — net ₹224k, Calmar 1.75, DD_net ₹19.5k, win 66%.

| ID | Variant | Strat id | Net ₹ | DD_net ₹ | DD_net % | Win % | Sharpe | Calmar | Trades | Report |
|---|---|---|---|---|---|---|---|---|---|---|
| RA1 | Iron fly (inside-day, ±500) | 999227054 | 9,533 | 22,104 | 19.7 | 66 | 0.16 | 0.10 | 2544 | [report](https://tradetron.tech/bt/view/f1209948ff28af43867f58ff2c3990dc) |
| RA2 | ATM iron fly ±500 | 999227058 | −43,498 | 51,333 | 51.3 | 67 | −0.60 | −0.26 | 4068 | [report](https://tradetron.tech/bt/view/fb2a4b166f4b01835ace01082cf3312c) |
| RA5 | Delta-0.15 strangle (TP/SL) | 999227150 | 102,996 | 17,380 | 8.9 | 68 | 1.64 | 1.11 | — | [report](https://tradetron.tech/bt/view/e0dd8eb16f45f0892e2f34e347dca8fb) |
| RA6 | Delta-0.15 strangle (prem-stop) | 999227154 | 104,238 | 24,970 | 14.8 | 69 | 1.60 | 0.78 | — | [report](https://tradetron.tech/bt/view/cdefd21adbdd24787c922a7a5ce52347) |
| RB1 | A1 + re-entry 15m | 999227298 | 181,528 | 32,203 | 18.5 | 69 | 1.34 | 0.92 | 2780 | [report](https://tradetron.tech/bt/view/b1db01027f1e40581d65be7893a8dc43) |
| RB2 | A1 + combined-prem 1.5× stop | 999228354 | 200,060 | 28,407 | 13.3 | 70 | 1.69 | 1.11 | 1548 | [report](https://tradetron.tech/bt/view/01b71f19f483b59ea6bed9aa5d49992f) |
| RB3 | Directional Supertrend ATM-BUY | 999228362 | −175,824 | 182,813 | 170.9 | 45 | −0.78 | −0.55 | 1896 | [report](https://tradetron.tech/bt/view/6b81095d10095b55f62881de08806501) |

(RA3/RA4 ATM flies −₹68.6k/−₹45.6k also rejected; shown in the plan's summary table.)

**Verdict:** champion A1 unchanged after 10+ variants. Full reasoning and the Round C plan to beat it in `BANKNIFTY_ROUND_C_PLAN.md`.
