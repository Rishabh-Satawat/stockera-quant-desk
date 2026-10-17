# V9 Combined-Premium Supertrend Straddle — Round 1

**Date:** 2026-10-17
**Underlying:** NIFTY weekly ATM options (Current Week), combined-premium Supertrend, intraday/weekly carry
**Window:** 2021-09-12 to 2026-09-12 (5.0 yr), Open fills, 1 lot
**Spend:** ₹180 (9 backtests × ₹20)
**Champion: short-only + Supertrend(10,2) + no fixed target.**

---

## 0. What the strategy is

Your V9 builds a **combined premium** = ATM CE + ATM PE added candle-by-candle (5-min), runs **Supertrend** once on that synthetic series, and trades two books:
- **LONG straddle** when combined premium trends *up* (buy vol).
- **SHORT straddle** when combined premium trends *down* (sell vol / harvest theta).

Universal exit: +₹10k target, or weekly-expiry day 15:19.

Your screenshot showed **gross** figures. Net of brokerage/STT/slippage, on a clean 5-yr window, the original is:
net ₹6.47L · CAGR 35.7% · Sharpe 1.99 · expectancy ₹187 · DD ₹59k (15.5% peak) · 3,866 trades.

(The scary "−32% DD" on the report is measured against the ₹1.8L capital box; the real peak-to-trough equity drawdown is ~15%.)

---

## 1. The big finding — the long book is dead weight

Set attribution on your V9:
- **SHORT book: +₹7.13L** (110% of the net).
- **LONG book: −₹66k** over 306 round-trips — and it deepens drawdown.

So half the machine is a confirmed money-loser. Removing it lifts return **and** cuts drawdown. This is mechanical, not luck.

---

## 2. All 9 runs (NET, same 5-yr window, 1 lot)

| Variant | id | Net ₹ | Sharpe | CAGR% | Exp ₹ | DD ₹ | PF | Trades | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| Your V9 (2-book) | 999027898 | 647,258 | 1.99 | 35.7 | 187 | 59,022 | 1.13 | 3866 | Reference |
| Short-only | 999196282 | 732,948 | 2.39 | 52.8 | 218 | 48,089 | 1.15 | 3696 | Big win |
| Short-only, NO Supertrend exit | 999196290 | 598,746 | 1.69 | 47.5 | 266 | 82,210 | 1.15 | 2444 | **Reject — DD 35%** |
| Short-only, no 10k target | 999196294 | 751,439 | 2.42 | 53.5 | 223 | 48,089 | 1.15 | 3698 | Win, best expectancy |
| Short-only, Supertrend 7,3 | 999196298 | 745,955 | 2.44 | 53.3 | 219 | 42,930 | 1.15 | 3748 | Strong |
| Short-only, Supertrend 14,3 | 999196306 | 731,222 | 2.39 | 52.7 | 219 | 45,840 | 1.15 | 3678 | Strong |
| Short-only, Supertrend 10,2 | 999196314 | 765,854 | 2.66 | 54.0 | 192 | 39,524 | 1.15 | 4442 | Top performer |
| Short-only, entry 09:30 | 999196322 | 443,663 | 1.67 | 40.3 | 146 | 56,057 | 1.11 | 3502 | **Reject — open matters** |
| **★ CHAMPION: ShortOnly ST10-2 NoTgt** | **999196482** | **787,965** | **2.70** | **54.8** | **197** | **38,906** | **1.15** | **4444** | **CHAMPION** |

---

## 3. The champion

**V9 CP-ST ShortOnly ST10-2 NoTgt (id 999196482)** — three changes to your V9:
1. Drop the long book (keep only the short straddle).
2. Tighten Supertrend 3 → 2 (flips sooner, protects faster).
3. Remove the ₹10k target (it rarely triggered; letting winners ride to the trend-flip adds a touch).

Result vs your original: **net +21.7%, Sharpe 1.99 → 2.70, Sortino → 4.02, Calmar → 1.41, drawdown −34% (₹59k → ₹39k), expectancy ₹187 → ₹197.**
Report: https://tradetron.tech/bt/view/39f42b1219ef6363978288ac5e3a4a74

**Alternative — if you prefer fewer, higher-quality trades:** SO_NOTGT (Supertrend 10,3 + no target, id 999196294) — net ₹7.51L, Sharpe 2.42, **expectancy ₹223**, 3,698 trades (vs the champion's 4,444). Lower turnover = less slippage-sensitive live. The pick between them is a turnover-appetite call.

---

## 4. Honest read on significance

Paired daily t-test, champion vs your V9: **t = 1.44** (needs ≥ 1.96). So the **+22% net is within daily noise** — not proven new alpha.

What *is* robust:
- **Dropping the long book** (a confirmed −₹66k loser) — mechanical.
- **The −34% drawdown** — mechanical (never holds the losing leg; tighter stop caps losses).
- **Supertrend isn't curve-fit:** periods 7/10/14 all net ₹7.3–7.7L, Sharpe 2.39–2.66.

**Bottom line:** same-or-better money with a materially smoother ride. That is the real, defensible win — the same shape as the BankNifty result.

All runs carry a high-severity COVERAGE_PARTIAL caveat (4 absent / 5 skipped sessions + ~5 unresolved COVID-era strikes); comparisons are apples-to-apples (same caveat each side), absolute ₹ a slight over-count.

---

## 5. Round 2 roadmap

1. Second-indicator confirmation (ADX / premium-vs-EMA) to lift expectancy on the busy 10,2 band.
2. ATM SPOT vs ATM strike (the strike currently anchors to monthly futures).
3. A disaster-only stop (−₹6–8k) to cap tail days without the NoSTexit damage.
4. Re-entry cap (2–3/day) to cut churn — the champion trades 4,444 times.
5. Out-of-sample 2018–2021 once older coverage is confirmed; request walk-forward.

Going live is your own step, on the strategy's edit page. Live Offline (paper) for 10–20 sessions first is the sensible check.
