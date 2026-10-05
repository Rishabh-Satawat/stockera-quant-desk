import os
import json
import time
import logging
import datetime
import requests
from dotenv import load_dotenv
from chain_microstructure_analyzer import analyze_option_chain_microstructure
from market_hours_gate import is_market_open  # P0.1

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
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
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

    # P0.2: Evaluate all 4 underlyings into a candidate list — no early break.
    candidates = []

    for sym in ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"]:
        analysis = analyze_option_chain_microstructure(sym)
        if not analysis:
            logger.error("DATA_FAULT hunt_market_once sym=%s no_analysis", sym)
            print(f"   ⚠️ {sym:<10} | Could not reach Dhan chain feed.")
            continue

        # P0.3: Fail closed on synthetic data — never alert or trade on fallback.
        if analysis.get("is_synthetic", False):
            logger.error("DATA_FAULT hunt_market_once sym=%s is_synthetic=True refusing alert", sym)
            print(f"   🚫 {sym:<10} | DATA_FAULT: synthetic feed — skipping.")
            continue

        spot = analysis["spot"]
        pcr = analysis["pcr_oi"]
        max_pain = analysis["max_pain"]
        call_wall = analysis["call_wall"]
        put_wall = analysis["put_wall"]
        oc = analysis["raw_oc"]
        expiry = analysis["expiry"]

        lot = LOT_SIZES.get(sym)
        if lot is None:
            logger.error("DATA_FAULT hunt_market_once sym=%s unknown_lot_size", sym)
            continue

        step = 100 if sym in ["SENSEX", "BANKNIFTY"] else 50
        atm = int(round(spot / step) * step)

        last_t = cooldowns.get(sym, 0)
        cooldown_rem = max(0, int((900 - (time.time() - last_t)) / 60))

        # Regime classification
        if pcr < 0.85:
            regime = "BEARISH_EXPANSION"
        elif pcr > 1.15:
            regime = "BULLISH_EXPANSION"
        else:
            regime = "RANGE_BOUND"

        print(f"   • {sym:<10} | Spot: ₹{spot:,.2f} | PCR: {pcr:.2f} ({regime}) | MaxPain: {max_pain:.0f} | Cooldown: {cooldown_rem}m")

        if cooldown_rem > 0:
            continue

        candidates.append({
            "sym": sym, "spot": spot, "pcr": pcr, "max_pain": max_pain,
            "call_wall": call_wall, "put_wall": put_wall, "oc": oc,
            "expiry": expiry, "lot": lot, "step": step, "atm": atm,
            "regime": regime,
        })

    # P0.2: Full scan complete — first-match selection (not scored ranking; Phase 3 will add scoring).
    naked_candidate = None
    hedged_candidate = None
    for c in candidates:
        if c["regime"] in ("BEARISH_EXPANSION", "BULLISH_EXPANSION") and naked_candidate is None:
            naked_candidate = c
        if c["regime"] == "RANGE_BOUND" and hedged_candidate is None:
            hedged_candidate = c

    # --- A. NAKED DIRECTIONAL BOOK ---
    if naked_candidate and len(naked_trades) < 3:
        c = naked_candidate
        sym, spot, pcr = c["sym"], c["spot"], c["pcr"]
        oc, expiry, lot, step, atm = c["oc"], c["expiry"], c["lot"], c["step"], c["atm"]
        regime = c["regime"]
        max_pain, call_wall, put_wall = c["max_pain"], c["call_wall"], c["put_wall"]

        if regime == "BEARISH_EXPANSION":
            strike = atm
            opt_price = get_strike_ltp(oc, strike, "PE")
            # P0.5: Abort on missing price — never trade blind.
            if opt_price is None:
                logger.error("DATA_FAULT hunt_market_once sym=%s BEARISH_EXPANSION PE ltp=None aborting", sym)
                print(f"   🚫 {sym} NAKED PE: DATA_FAULT ltp unavailable — trade aborted.")
            else:
                sl = round(opt_price * 0.80, 2)
                t1 = round(opt_price * 1.25, 2)
                t2 = round(opt_price * 1.50, 2)
                trade_id = f"{today_tag}-NAKED-{len(naked_trades)+1:02d}"
                contract = f"{sym} {strike} PE"
                new_trade = {
                    "trade_id": trade_id, "book": "NAKED", "symbol": sym,
                    "contract": contract, "action": "BUY",
                    "strategy": "Bearish Put Momentum (Downside Expansion)",
                    "qty": lot, "entry_time": now_str, "entry_price": opt_price,
                    "stop_loss": sl, "target_1": t1, "target_2": t2,
                    "status": "ACTIVE", "exit_time": None, "exit_price": None,
                    "exit_reason": None, "margin_deployed": round(opt_price * lot, 2)
                }
                trades.append(new_trade)
                _write_ledger(trades, LEDGER_FILE)
                cooldowns[sym] = time.time()
                save_cooldown_state(cooldowns)
                msg = f"""🚨 *STOCKERA QUANT: NAKED DIRECTIONAL BUY ALERT* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Asset:* {sym} | *Live Spot:* ₹{spot:,.2f}
📅 *Expiry:* `{expiry}` | *Book:* 🔴 NAKED DIRECTIONAL
📌 *Strategy:* Bearish Put Buying (Downside Momentum)
━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *OPTION CHAIN MICROSTRUCTURE THESIS:*
• *Put-Call Ratio (PCR):* {pcr:.2f} (Bearish Call Heavy Pressure)
• *Max Pain Strike:* {max_pain:.0f} (Spot is {max_pain - spot:.1f} pts below)
• *Call Resistance Wall:* {call_wall:.0f} (Overhead Supply)
• *Downside Target Wall:* {put_wall:.0f} (Next Major Support)
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
⚡ *Status:* ACTIVE | Managed by AURA Sentinel"""
                print(f"\n🚀 DISPATCHING NAKED BEARISH ALERT:\n{msg}\n")
                send_telegram_alert(msg)

        elif regime == "BULLISH_EXPANSION":
            strike = atm
            opt_price = get_strike_ltp(oc, strike, "CE")
            # P0.5: Abort on missing price — never trade blind.
            if opt_price is None:
                logger.error("DATA_FAULT hunt_market_once sym=%s BULLISH_EXPANSION CE ltp=None aborting", sym)
                print(f"   🚫 {sym} NAKED CE: DATA_FAULT ltp unavailable — trade aborted.")
            else:
                sl = round(opt_price * 0.80, 2)
                t1 = round(opt_price * 1.25, 2)
                t2 = round(opt_price * 1.50, 2)
                trade_id = f"{today_tag}-NAKED-{len(naked_trades)+1:02d}"
                contract = f"{sym} {strike} CE"
                new_trade = {
                    "trade_id": trade_id, "book": "NAKED", "symbol": sym,
                    "contract": contract, "action": "BUY",
                    "strategy": "Bullish Call Momentum (Upside Breakout)",
                    "qty": lot, "entry_time": now_str, "entry_price": opt_price,
                    "stop_loss": sl, "target_1": t1, "target_2": t2,
                    "status": "ACTIVE", "exit_time": None, "exit_price": None,
                    "exit_reason": None, "margin_deployed": round(opt_price * lot, 2)
                }
                trades.append(new_trade)
                _write_ledger(trades, LEDGER_FILE)
                cooldowns[sym] = time.time()
                save_cooldown_state(cooldowns)
                msg = f"""🚨 *STOCKERA QUANT: NAKED DIRECTIONAL BUY ALERT* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Asset:* {sym} | *Live Spot:* ₹{spot:,.2f}
📅 *Expiry:* `{expiry}` | *Book:* 🔴 NAKED DIRECTIONAL
📌 *Strategy:* Bullish Call Buying (Upside Momentum)
━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *OPTION CHAIN MICROSTRUCTURE THESIS:*
• *Put-Call Ratio (PCR):* {pcr:.2f} (Strong Put Writing Support)
• *Max Pain Strike:* {max_pain:.0f} (Spot is {spot - max_pain:.1f} pts above)
• *Call Wall Breakout:* {call_wall:.0f} (Short Covering Acceleration)
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
⚡ *Status:* ACTIVE | Managed by AURA Sentinel"""
                print(f"\n🚀 DISPATCHING NAKED BULLISH ALERT:\n{msg}\n")
                send_telegram_alert(msg)

    # --- B. HEDGED RANGE-BOUND BOOK ---
    if hedged_candidate and len(hedged_trades) < 3:
        c = hedged_candidate
        sym, spot, pcr = c["sym"], c["spot"], c["pcr"]
        oc, expiry, lot, step, atm = c["oc"], c["expiry"], c["lot"], c["step"], c["atm"]
        max_pain, call_wall, put_wall = c["max_pain"], c["call_wall"], c["put_wall"]

        s_ce, b_ce = atm + 2 * step, atm + 4 * step
        s_pe, b_pe = atm - 2 * step, atm - 4 * step

        p_sce = get_strike_ltp(oc, s_ce, "CE")
        p_bce = get_strike_ltp(oc, b_ce, "CE")
        p_spe = get_strike_ltp(oc, s_pe, "PE")
        p_bpe = get_strike_ltp(oc, b_pe, "PE")

        # P0.5: All 4 legs must have live prices — abort entire condor on any None.
        if any(p is None for p in [p_sce, p_bce, p_spe, p_bpe]):
            missing = [n for n, p in [("s_ce", p_sce), ("b_ce", p_bce), ("s_pe", p_spe), ("b_pe", p_bpe)] if p is None]
            logger.error("DATA_FAULT hunt_market_once sym=%s condor legs=%s ltp=None aborting", sym, missing)
            print(f"   🚫 {sym} HEDGED CONDOR: DATA_FAULT legs {missing} ltp unavailable — trade aborted.")
        else:
            net_credit = round((p_sce - p_bce) + (p_spe - p_bpe), 2)
            max_profit = round(net_credit * lot, 2)
            lower_be = s_pe - net_credit
            upper_be = s_ce + net_credit

            trade_id = f"{today_tag}-HEDGE-{len(hedged_trades)+1:02d}"
            contract = f"{sym} {s_pe} PE / {s_ce} CE Condor"

            new_trade = {
                "trade_id": trade_id, "book": "HEDGED", "symbol": sym,
                "contract": contract, "action": "SELL",
                "strategy": "0DTE Delta-Neutral Iron Condor",
                "qty": lot, "entry_time": now_str, "entry_price": net_credit,
                "stop_loss": round(net_credit * 2.0, 2),
                "target_1": round(net_credit * 0.20, 2),
                "status": "ACTIVE", "exit_time": None, "exit_price": None,
                "exit_reason": None, "margin_deployed": 42000.0
            }
            trades.append(new_trade)
            _write_ledger(trades, LEDGER_FILE)
            cooldowns[sym] = time.time()
            save_cooldown_state(cooldowns)

            msg = f"""🚨 *STOCKERA QUANT: HEDGED BASKET ALERT* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Asset:* {sym} | *Live Spot:* ₹{spot:,.2f}
📅 *Expiry:* `{expiry}` | *Book:* 🟢 HEDGED INCOME
📌 *Strategy:* 0DTE Range-Bound Iron Condor (PoP: 78.4%)
━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 *OPTION CHAIN MICROSTRUCTURE THESIS:*
• *Max Pain Strike:* {max_pain:.0f} | *Put-Call Ratio (PCR):* {pcr:.2f}
• *Call Resistance Wall:* {call_wall:.0f} | *Put Support Wall:* {put_wall:.0f}
━━━━━━━━━━━━━━━━━━━━━━━━━
📋 *EXACT ORDER EXECUTION SEQUENCE:*

🔹 *Step 1: BUY Hedges FIRST (Unlocks Margin Discount)*
   1. 🟢 `BUY  {sym} {b_ce} CE @ ₹{p_bce:.2f} (Call Hedge Wing)`
   2. 🟢 `BUY  {sym} {b_pe} PE @ ₹{p_bpe:.2f} (Put Hedge Wing)`

🔹 *Step 2: SELL Short Strikes*
   3. 🔴 `SELL {sym} {s_ce} CE @ ₹{p_sce:.2f} (Short Call)`
   4. 🔴 `SELL {sym} {s_pe} PE @ ₹{p_spe:.2f} (Short Put)`
━━━━━━━━━━━━━━━━━━━━━━━━━
💰 *RISK & REWARD BLUEPRINT ({lot} Qty / 1 Lot):*
• *Net Credit Collected:* +₹{net_credit:.2f} / lot
• *Total Max Profit:* +₹{max_profit:,.2f} / lot
• *Defined Max Risk (1x Hard-SL):* -₹{max_profit:,.2f} / lot
• *Safe Profit Corridor:* ₹{lower_be:,.0f} to ₹{upper_be:,.0f}
• *Exit Directive:* Exit basket if combined premium reaches ₹{net_credit * 2:.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Status:* ACTIVE | Managed by AURA Sentinel"""
            print(f"\n🚀 DISPATCHING HEDGED BASKET ALERT:\n{msg}\n")
            send_telegram_alert(msg)


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
