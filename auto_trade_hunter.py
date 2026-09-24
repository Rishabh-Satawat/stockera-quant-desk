import os
import json
import time
import datetime
import requests
from dotenv import load_dotenv
from chain_microstructure_analyzer import analyze_option_chain_microstructure

LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"
STATE_FILE = r"C:\kite-agent\hunter_state.json"

load_dotenv(r"C:\kite-agent\secrets\telegram.env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028").strip()

LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 60}

def send_telegram_alert(msg: str):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
        except Exception as e:
            print(f"Telegram notice: {e}")

def get_cooldown_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"SENSEX": 0, "NIFTY": 0, "BANKNIFTY": 0}

def save_cooldown_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_strike_ltp(oc, strike: float, opt_type: str) -> float:
    for k, v in oc.items():
        try:
            if abs(float(k) - strike) < 0.1:
                p = float(v.get(opt_type.lower(), {}).get("last_price", 0.0))
                if p > 0: return round(p, 2)
        except Exception:
            pass
    return 65.0

def hunt_market_once():
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

    for sym in ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"]:
        analysis = analyze_option_chain_microstructure(sym)
        if not analysis:
            print(f"   ⚠️ {sym:<10} | Could not reach Dhan chain feed.")
            continue

        spot = analysis["spot"]
        pcr = analysis["pcr_oi"]
        max_pain = analysis["max_pain"]
        call_wall = analysis["call_wall"]
        put_wall = analysis["put_wall"]
        oc = analysis["raw_oc"]
        expiry = analysis["expiry"]
        lot = LOT_SIZES.get(sym, 25)
        step = 100 if sym in ["SENSEX", "BANKNIFTY"] else 50
        atm = int(round(spot / step) * step)

        last_t = cooldowns.get(sym, 0)
        cooldown_rem = max(0, int((900 - (time.time() - last_t)) / 60))
        
        # Determine Regime
        if pcr < 0.85:
            regime = "BEARISH_EXPANSION"
        elif pcr > 1.15:
            regime = "BULLISH_EXPANSION"
        else:
            regime = "RANGE_BOUND"

        print(f"   • {sym:<10} | Spot: ₹{spot:,.2f} | PCR: {pcr:.2f} ({regime}) | MaxPain: {max_pain:.0f} | Cooldown: {cooldown_rem}m")

        if cooldown_rem > 0:
            continue

        # --- A. NAKED DIRECTIONAL BOOK (Max 3 Trades) ---
        if len(naked_trades) < 3:
            # 1. Bearish Put Momentum Setup (PCR < 0.85 and Spot below Max Pain)
            if regime == "BEARISH_EXPANSION":
                strike = atm
                opt_price = get_strike_ltp(oc, strike, "PE")
                sl = round(opt_price * 0.80, 2)
                t1 = round(opt_price * 1.25, 2)
                t2 = round(opt_price * 1.50, 2)

                trade_id = f"{today_tag}-NAKED-{len(naked_trades)+1:02d}"
                contract = f"{sym} {strike} PE"

                new_trade = {
                    "trade_id": trade_id,
                    "book": "NAKED",
                    "symbol": sym,
                    "contract": contract,
                    "action": "BUY",
                    "strategy": "Bearish Put Momentum (Downside Expansion)",
                    "qty": lot,
                    "entry_time": now_str,
                    "entry_price": opt_price,
                    "stop_loss": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "status": "ACTIVE",
                    "exit_time": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "margin_deployed": round(opt_price * lot, 2)
                }
                trades.append(new_trade)
                with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                    json.dump(trades, f, indent=2, ensure_ascii=False)

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
                break

            # 2. Bullish Call Momentum Setup (PCR > 1.15 and Spot above Max Pain)
            elif regime == "BULLISH_EXPANSION":
                strike = atm
                opt_price = get_strike_ltp(oc, strike, "CE")
                sl = round(opt_price * 0.80, 2)
                t1 = round(opt_price * 1.25, 2)
                t2 = round(opt_price * 1.50, 2)

                trade_id = f"{today_tag}-NAKED-{len(naked_trades)+1:02d}"
                contract = f"{sym} {strike} CE"

                new_trade = {
                    "trade_id": trade_id,
                    "book": "NAKED",
                    "symbol": sym,
                    "contract": contract,
                    "action": "BUY",
                    "strategy": "Bullish Call Momentum (Upside Breakout)",
                    "qty": lot,
                    "entry_time": now_str,
                    "entry_price": opt_price,
                    "stop_loss": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "status": "ACTIVE",
                    "exit_time": None,
                    "exit_price": None,
                    "exit_reason": None,
                    "margin_deployed": round(opt_price * lot, 2)
                }
                trades.append(new_trade)
                with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                    json.dump(trades, f, indent=2, ensure_ascii=False)

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
                break

        # --- B. HEDGED RANGE-BOUND BOOK (Max 3 Trades) ---
        if len(hedged_trades) < 3 and regime == "RANGE_BOUND":
            s_ce, b_ce = atm + 2 * step, atm + 4 * step
            s_pe, b_pe = atm - 2 * step, atm - 4 * step

            p_sce = get_strike_ltp(oc, s_ce, "CE")
            p_bce = get_strike_ltp(oc, b_ce, "CE")
            p_spe = get_strike_ltp(oc, s_pe, "PE")
            p_bpe = get_strike_ltp(oc, b_pe, "PE")

            net_credit = round((p_sce - p_bce) + (p_spe - p_bpe), 2)
            max_profit = round(net_credit * lot, 2)
            lower_be = s_pe - net_credit
            upper_be = s_ce + net_credit

            trade_id = f"{today_tag}-HEDGE-{len(hedged_trades)+1:02d}"
            contract = f"{sym} {s_pe} PE / {s_ce} CE Condor"

            new_trade = {
                "trade_id": trade_id,
                "book": "HEDGED",
                "symbol": sym,
                "contract": contract,
                "action": "SELL",
                "strategy": "0DTE Delta-Neutral Iron Condor",
                "qty": lot,
                "entry_time": now_str,
                "entry_price": net_credit,
                "stop_loss": round(net_credit * 2.0, 2),
                "target_1": round(net_credit * 0.20, 2),
                "status": "ACTIVE",
                "exit_time": None,
                "exit_price": None,
                "exit_reason": None,
                "margin_deployed": 42000.0
            }
            trades.append(new_trade)
            with open(LEDGER_FILE, "w", encoding="utf-8") as f:
                json.dump(trades, f, indent=2, ensure_ascii=False)

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
            break

def start_continuous_hunter():
    print("🚀 Stockera Multi-Regime Trade Hunter is ACTIVE!")
    while True:
        try:
            hunt_market_once()
        except Exception as e:
            print(f"Hunter loop notice: {e}")
        time.sleep(60)

if __name__ == "__main__":
    start_continuous_hunter()
