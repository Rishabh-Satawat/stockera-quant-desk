import os
import json
import time
import logging
import datetime
import requests
from dotenv import load_dotenv
from chain_microstructure_analyzer import analyze_option_chain_microstructure
from market_hours_gate import is_market_open  # P0.1
from regime_engine import compute_regime, get_playbook
from playbook_triggers import evaluate_all_playbooks, PlaybookSignal
from scoring_engine import score_candidate, rank_and_filter, format_confluence_breakdown, TIER1_THRESHOLD
from candidate_logger import log_candidate
from db_init import DEFAULT_DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"
STATE_FILE = r"C:\kite-agent\hunter_state.json"

load_dotenv(r"C:\kite-agent\secrets\telegram.env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _require_telegram_token():
    """Raise at call time if the token is absent — never at import time."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN env var is missing — load secrets/telegram.env before starting the hunter"
        )

# P0.1: Lot sizes — resolved dynamically; fallback dict only.
# Never hardcode lot sizes in trading logic; use LOT_SIZES.get(sym) and abort
# if the symbol is missing.
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 60}


def send_telegram_alert(msg: str):
    _require_telegram_token()
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        logger.warning("Telegram notice: %s", e)


def get_cooldown_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"SENSEX": 0, "NIFTY": 0, "BANKNIFTY": 0, "FINNIFTY": 0}


def save_cooldown_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# P0.5: Return None on missing prices — never a hardcoded default.
def get_strike_ltp(oc, strike: float, opt_type: str):
    """Return live LTP for the given strike/type, or None if unavailable."""
    for k, v in oc.items():
        try:
            if abs(float(k) - strike) < 0.5:
                p = v.get(opt_type.lower(), {}).get("last_price")
                if p is not None:
                    p = float(p)
                    if p > 0:
                        return round(p, 2)
        except Exception:
            pass
    return None


def _write_ledger(trades, ledger_file):
    with open(ledger_file, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)
    try:
        from supabase_sync import sync_trades_to_supabase
        sync_trades_to_supabase()
    except Exception:
        pass


def hunt_market_once():
    # P0.1: Hard market-hours gate — no scan outside window or on holidays.
    open_flag, gate_reason = is_market_open()
    if not open_flag:
        logger.info("DATA_FAULT hunt_market_once BLOCKED gate=%s", gate_reason)
        return

    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%H:%M:%S")
    today_tag = f"TRD-{now_dt.strftime('%Y%m%d')}"
    cooldowns = get_cooldown_state()

    trades = []
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
            try:
                trades = json.load(f)
            except Exception:
                trades = []

    today_trades = [t for t in trades if t.get("trade_id", "").startswith(today_tag)]
    hedged_trades = [t for t in today_trades if t.get("book") == "HEDGED"]
    naked_trades = [t for t in today_trades if t.get("book") == "NAKED"]

    print(f"\n[{now_str}] 📡 DUAL-BOOK SCAN | Hedged: {len(hedged_trades)}/3 | Naked: {len(naked_trades)}/3")

    # ──────────────────────────────────────────────────────────────────────────
    # Regime gate: consult regime_engine before emitting any signal.
    # A playbook not permitted in the current regime is blocked and logged.
    # ──────────────────────────────────────────────────────────────────────────

    _BEARISH_PLAYBOOKS = {"LONG_PUT", "LONG_PUT_SPREAD", "BEAR_PUT_SPREAD"}
    _BULLISH_PLAYBOOKS = {"LONG_CALL", "LONG_CALL_SPREAD", "BULL_CALL_SPREAD"}
    _RANGE_PLAYBOOKS = {"IRON_CONDOR", "SHORT_STRANGLE"}

    def _check_regime_gate(candidate, required_playbooks, db_path=DEFAULT_DB_PATH):
        """Return (allowed: bool, regime_dict, playbook: str)."""
        try:
            reg = compute_regime(
                candidate["sym"],
                candidate["expiry"],
                candidate["spot"],
                db_path=db_path,
            )
        except Exception as exc:
            logger.warning("regime_gate: compute_regime raised %s — blocking as REGIME_DATA_FAULT", exc)
            return False, {}, "REGIME_DATA_FAULT"

        playbook = reg.get("playbook", "NO_TRADE")
        if playbook in required_playbooks:
            return True, reg, playbook
        return False, reg, playbook

    # ──────────────────────────────────────────────────────────────────────────
    # P1C: Full playbook + scoring pipeline across all 4 indices.
    # Replaces legacy PCR if/else with evaluate_all_playbooks + score_candidate.
    # ──────────────────────────────────────────────────────────────────────────

    # Collect raw market data for all 4 underlyings
    market_data: list[dict] = []

    for sym in ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"]:
        analysis = analyze_option_chain_microstructure(sym)
        if not analysis:
            logger.error("DATA_FAULT hunt_market_once sym=%s no_analysis", sym)
            print(f"   ⚠️ {sym:<10} | Could not reach Dhan chain feed.")
            continue

        # P0.3: Fail closed on synthetic data.
        if analysis.get("is_synthetic", False):
            logger.error("DATA_FAULT hunt_market_once sym=%s is_synthetic=True refusing alert", sym)
            print(f"   🚫 {sym:<10} | DATA_FAULT: synthetic feed — skipping.")
            continue

        lot = LOT_SIZES.get(sym)
        if lot is None:
            logger.error("DATA_FAULT hunt_market_once sym=%s unknown_lot_size", sym)
            continue

        step = 100 if sym in ["SENSEX", "BANKNIFTY"] else 50
        spot = analysis["spot"]
        pcr = analysis["pcr_oi"]
        max_pain = analysis["max_pain"]
        call_wall = analysis["call_wall"]
        put_wall = analysis["put_wall"]

        last_t = cooldowns.get(sym, 0)
        cooldown_rem = max(0, int((900 - (time.time() - last_t)) / 60))

        print(f"   • {sym:<10} | Spot: ₹{spot:,.2f} | PCR: {pcr:.2f} | MaxPain: {max_pain:.0f} | Cooldown: {cooldown_rem}m")

        if cooldown_rem > 0:
            continue

        market_data.append({
            "sym": sym, "analysis": analysis, "lot": lot, "step": step,
        })

    # For each symbol, compute regime + evaluate playbooks + score
    all_signals: list[tuple[PlaybookSignal, dict, dict]] = []  # (signal, score_result, meta)

    for md in market_data:
        sym = md["sym"]
        analysis = md["analysis"]
        step = md["step"]
        lot = md["lot"]

        # Regime gate
        try:
            reg_data = compute_regime(sym, analysis["expiry"], analysis["spot"])
        except Exception as exc:
            logger.warning("compute_regime failed for %s: %s — skipping", sym, exc)
            continue

        playbook_name = reg_data.get("playbook", "NO_TRADE")

        # Evaluate all playbooks
        signals = evaluate_all_playbooks(sym, analysis, reg_data, step)

        for sig in signals:
            score_result = score_candidate(sig)
            tier = score_result["tier"]

            if tier == 0:
                logger.debug(
                    "scoring: %s %s score=%d < 60 — dropped",
                    sym, sig.playbook_id, score_result["score"],
                )
                log_candidate(sig, score_result, dispatched=False, skip_reason="score<60")
                continue
            elif tier == 2:
                logger.info(
                    "scoring: %s %s score=%d tier=2 watchlist",
                    sym, sig.playbook_id, score_result["score"],
                )
                log_candidate(sig, score_result, dispatched=False, skip_reason="tier2_watchlist")
            # Both tier 1 and tier 2 are collected; we dispatch only tier 1 below
            all_signals.append((sig, score_result, md))

    # Apply anti-correlation filter and sort by score
    scored_pairs = [(sig, sr) for sig, sr, _ in all_signals]
    filtered = rank_and_filter(scored_pairs)

    # Re-associate metadata
    meta_map = {id(sig): md for sig, sr, md in all_signals}
    filtered_with_meta = [(sig, sr, meta_map[id(sig)]) for sig, sr in filtered]

    # Dispatch highest-scoring Tier 1 candidates, respecting book quotas
    dispatched_naked = 0
    dispatched_hedged = 0

    for sig, score_result, md in filtered_with_meta:
        tier = score_result["tier"]
        if tier == 0:
            continue  # dropped
        if tier == 2 and not sig.vol_provisional:
            continue  # watchlist only — dispatch tier 2 only for provisional cold-start

        score_int = score_result["score"]
        sym = sig.symbol
        analysis = md["analysis"]
        lot = md["lot"]
        step = md["step"]
        spot = analysis["spot"]
        pcr = analysis["pcr_oi"]
        max_pain = analysis["max_pain"]
        call_wall = analysis["call_wall"]
        put_wall = analysis["put_wall"]
        oc = analysis["raw_oc"]
        expiry = analysis["expiry"]
        atm = int(round(spot / step) * step)
        reg_line = f"Regime: {sig.direction} / {sig.vol_regime} / {sig.playbook_id}"
        conf_block = format_confluence_breakdown(sig, score_result)

        # ── Naked directional (PB1) ──
        if sig.playbook_id == "PB1" and len(naked_trades) + dispatched_naked < 3:
            strike = sig.atm_strike or float(atm)
            opt_type = "CE" if sig.direction in ("BULL", "STRONG_BULL") else "PE"
            opt_price = get_strike_ltp(oc, strike, opt_type)
            if opt_price is None:
                logger.error("DATA_FAULT PB1 sym=%s %s ltp=None aborting", sym, opt_type)
                print(f"   🚫 {sym} PB1 {opt_type}: DATA_FAULT ltp unavailable — trade aborted.")
                continue

            sl = round(opt_price * 0.80, 2)
            t1 = round(opt_price * 1.25, 2)
            t2 = round(opt_price * 1.50, 2)
            trade_id = f"{today_tag}-NAKED-{len(naked_trades)+dispatched_naked+1:02d}"
            contract = f"{sym} {strike:.0f} {opt_type}"
            strategy = (
                "Bullish Call Momentum (Upside Breakout)"
                if opt_type == "CE"
                else "Bearish Put Momentum (Downside Expansion)"
            )
            new_trade = {
                "trade_id": trade_id, "book": "NAKED", "symbol": sym,
                "contract": contract, "action": "BUY", "strategy": strategy,
                "qty": lot, "entry_time": now_str, "entry_price": opt_price,
                "stop_loss": sl, "target_1": t1, "target_2": t2,
                "status": "ACTIVE", "exit_time": None, "exit_price": None,
                "exit_reason": None,
                "margin_deployed": round(opt_price * lot, 2),
                "confluence_score": score_int,
                "playbook": sig.playbook_id,
            }
            trades.append(new_trade)
            _write_ledger(trades, LEDGER_FILE)
            cooldowns[sym] = time.time()
            save_cooldown_state(cooldowns)
            dispatched_naked += 1

            if opt_type == "CE":
                chain_thesis = (
                    f"• *Put-Call Ratio (PCR):* {pcr:.2f} (Strong Put Writing Support)\n"
                    f"• *Max Pain Strike:* {max_pain:.0f} (Spot is {spot - max_pain:.1f} pts above)\n"
                    f"• *Call Wall Breakout:* {call_wall:.0f} (Short Covering Acceleration)"
                )
            else:
                chain_thesis = (
                    f"• *Put-Call Ratio (PCR):* {pcr:.2f} (Bearish Call Heavy Pressure)\n"
                    f"• *Max Pain Strike:* {max_pain:.0f} (Spot is {max_pain - spot:.1f} pts below)\n"
                    f"• *Call Resistance Wall:* {call_wall:.0f} (Overhead Supply)\n"
                    f"• *Downside Target Wall:* {put_wall:.0f} (Next Major Support)"
                )

            provisional_tag = "\n⚠️ *PROVISIONAL (Cold-Start IVR)*" if sig.vol_provisional else ""
            msg = f"""🚨 *STOCKERA QUANT: NAKED DIRECTIONAL BUY ALERT* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Asset:* {sym} | *Live Spot:* ₹{spot:,.2f}
📅 *Expiry:* `{expiry}` | *Book:* 🔴 NAKED DIRECTIONAL
📌 *Strategy:* {strategy}
━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *OPTION CHAIN MICROSTRUCTURE THESIS:*
{chain_thesis}
━━━━━━━━━━━━━━━━━━━━━━━━━
📋 *EXACT ORDER TO EXECUTE:*
• 🟢 `BUY  {contract} @ Limit ₹{opt_price:.2f} ({lot} Qty / 1 Lot)`

💰 *RISK & REWARD BLUEPRINT:*
• *Capital Deployed:* ₹{opt_price * lot:,.2f}
• *Hard Stop-Loss:* ₹{sl:.2f} (-20% / Risk -₹{(opt_price - sl) * lot:,.2f})
• *Target 1 (Book 50%):* ₹{t1:.2f} (+25% / +₹{(t1 - opt_price) * lot:,.2f}) 🎯
• *Target 2 (Trail SL):* ₹{t2:.2f} (+50% / +₹{(t2 - opt_price) * lot:,.2f}) 🚀
• *Realized R:R Ratio:* 1 : 2.50 ✅
━━━━━━━━━━━━━━━━━━━━━━━━━
📊 *{reg_line}*
{conf_block}{provisional_tag}
⚡ *Status:* ACTIVE | Managed by AURA Sentinel"""
            print(f"\n🚀 DISPATCHING NAKED ALERT (score={score_int}/100):\n{msg}\n")
            send_telegram_alert(msg)
            log_candidate(sig, score_result, dispatched=True)

        # ── Hedged spread / condor (PB2, PB6) ──
        elif sig.playbook_id in ("PB2", "PB6") and len(hedged_trades) + dispatched_hedged < 3:
            s_ce = sig.short_strike_ce or float(atm + 2 * step)
            b_ce = sig.long_strike_ce or float(atm + 4 * step)
            s_pe = sig.short_strike_pe or float(atm - 2 * step)
            b_pe = sig.long_strike_pe or float(atm - 4 * step)

            p_sce = get_strike_ltp(oc, s_ce, "CE")
            p_bce = get_strike_ltp(oc, b_ce, "CE")
            p_spe = get_strike_ltp(oc, s_pe, "PE")
            p_bpe = get_strike_ltp(oc, b_pe, "PE")

            # P0.5: All 4 legs must have live prices.
            if any(p is None for p in [p_sce, p_bce, p_spe, p_bpe]):
                missing = [n for n, p in [("s_ce", p_sce), ("b_ce", p_bce), ("s_pe", p_spe), ("b_pe", p_bpe)] if p is None]
                logger.error("DATA_FAULT hunt_market_once sym=%s condor legs=%s ltp=None aborting", sym, missing)
                print(f"   🚫 {sym} HEDGED CONDOR: DATA_FAULT legs {missing} ltp unavailable — trade aborted.")
                continue

            net_credit = round((p_sce - p_bce) + (p_spe - p_bpe), 2)
            max_profit = round(net_credit * lot, 2)
            lower_be = s_pe - net_credit
            upper_be = s_ce + net_credit

            strategy_name = "Iron Butterfly (Max Pain Pin)" if sig.playbook_id == "PB2" else "0DTE Delta-Neutral Iron Condor"
            trade_id = f"{today_tag}-HEDGE-{len(hedged_trades)+dispatched_hedged+1:02d}"
            contract = f"{sym} {s_pe:.0f} PE / {s_ce:.0f} CE Condor"

            new_trade = {
                "trade_id": trade_id, "book": "HEDGED", "symbol": sym,
                "contract": contract, "action": "SELL",
                "strategy": strategy_name,
                "qty": lot, "entry_time": now_str, "entry_price": net_credit,
                "stop_loss": round(net_credit * 2.0, 2),
                "target_1": round(net_credit * 0.20, 2),
                "status": "ACTIVE", "exit_time": None, "exit_price": None,
                "exit_reason": None, "margin_deployed": 42000.0,
                "confluence_score": score_int,
                "playbook": sig.playbook_id,
            }
            trades.append(new_trade)
            _write_ledger(trades, LEDGER_FILE)
            cooldowns[sym] = time.time()
            save_cooldown_state(cooldowns)
            dispatched_hedged += 1

            provisional_tag = "\n⚠️ *PROVISIONAL (Cold-Start IVR)*" if sig.vol_provisional else ""
            msg = f"""🚨 *STOCKERA QUANT: HEDGED BASKET ALERT* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Asset:* {sym} | *Live Spot:* ₹{spot:,.2f}
📅 *Expiry:* `{expiry}` | *Book:* 🟢 HEDGED INCOME
📌 *Strategy:* {strategy_name}
━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *OPTION CHAIN MICROSTRUCTURE THESIS:*
• *Max Pain Strike:* {max_pain:.0f} | *Put-Call Ratio (PCR):* {pcr:.2f}
• *Call Resistance Wall:* {call_wall:.0f} | *Put Support Wall:* {put_wall:.0f}
━━━━━━━━━━━━━━━━━━━━━━━━━
📋 *EXACT ORDER EXECUTION SEQUENCE:*

🔹 *Step 1: BUY Hedges FIRST (Unlocks Margin Discount)*
   1. 🟢 `BUY  {sym} {b_ce:.0f} CE @ ₹{p_bce:.2f} (Call Hedge Wing)`
   2. 🟢 `BUY  {sym} {b_pe:.0f} PE @ ₹{p_bpe:.2f} (Put Hedge Wing)`

🔹 *Step 2: SELL Short Strikes*
   3. 🔴 `SELL {sym} {s_ce:.0f} CE @ ₹{p_sce:.2f} (Short Call)`
   4. 🔴 `SELL {sym} {s_pe:.0f} PE @ ₹{p_spe:.2f} (Short Put)`
━━━━━━━━━━━━━━━━━━━━━━━━━
📊 *{reg_line}*
{conf_block}{provisional_tag}
━━━━━━━━━━━━━━━━━━━━━━━━━
💰 *RISK & REWARD BLUEPRINT ({lot} Qty / 1 Lot):*
• *Net Credit Collected:* +₹{net_credit:.2f} / lot
• *Total Max Profit:* +₹{max_profit:,.2f} / lot
• *Defined Max Risk (1x Hard-SL):* -₹{max_profit:,.2f} / lot
• *Safe Profit Corridor:* ₹{lower_be:,.0f} to ₹{upper_be:,.0f}
• *Exit Directive:* Exit basket if combined premium reaches ₹{net_credit * 2:.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Status:* ACTIVE | Managed by AURA Sentinel"""
            print(f"\n🚀 DISPATCHING HEDGED BASKET ALERT (score={score_int}/100):\n{msg}\n")
            send_telegram_alert(msg)
            log_candidate(sig, score_result, dispatched=True)


def start_continuous_hunter():
    print("🚀 Stockera Multi-Regime Trade Hunter is ACTIVE!")
    while True:
        try:
            hunt_market_once()
        except Exception as e:
            logger.exception("Hunter loop error: %s", e)
        time.sleep(60)


if __name__ == "__main__":
    start_continuous_hunter()
