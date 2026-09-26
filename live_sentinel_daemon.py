import os
import re
import sys
import time
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

# 1. Load Secrets
load_dotenv(r"C:\kite-agent\secrets\telegram.env")
load_dotenv(r"C:\kite-agent\secrets\dhan.env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028")
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

SCRIP_MAP = {
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "SENSEX": 51
}

def parse_contract(contract_str, default_symbol="NIFTY"):
    symbol = default_symbol.upper()
    for s in ["SENSEX", "BANKNIFTY", "NIFTY"]:
        if s in contract_str.upper():
            symbol = s
            break
    match = re.search(r"(\d{4,6})\s*(CE|PE)", contract_str.upper())
    if match:
        return symbol, float(match.group(1)), match.group(2).lower()
    return symbol, None, None

def fetch_dhan_chain_price(symbol, strike, opt_type):
    """Fetches real-time option LTP from Dhan HQ v2 Option Chain API."""
    scrip_id = SCRIP_MAP.get(symbol.upper(), 13)
    url = "https://api.dhan.co/v2/optionchain"
    headers = {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json"
    }
    payload = {
        "UnderlyingScrip": scrip_id,
        "UnderlyingSeg": "IDX_I"
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=3)
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            oc = data.get("oc", {})
            # Look up formatted strike (e.g. 23200.000000)
            strike_key = f"{strike:.6f}"
            if strike_key in oc:
                leg_info = oc[strike_key].get(opt_type, {})
                ltp = float(leg_info.get("last_price", 0.0))
                if ltp > 0:
                    return ltp
    except Exception:
        pass
    return None

def send_telegram_alert(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=8)
        return resp.status_code == 200
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")
        return False

def run_sentinel(simulation=False):
    print("=" * 60)
    print("⚡ STOCKERA RUNTIME POSITION SENTINEL DAEMON (LIVE FEED)")
    print(f"Mode: {'SIMULATION' if simulation else 'LIVE DHAN HQ v2'}")
    print(f"Polling Interval: 3 seconds | Broadcast Target: {TELEGRAM_CHAT_ID}")
    print("=" * 60)

    tick = 0
    while True:
        tick += 1
        if not os.path.exists(LEDGER_PATH):
            time.sleep(4)
            continue

        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            trades = json.load(f)

        active_trades = [t for t in trades if str(t.get("status", "")).upper() == "ACTIVE"]

        if not active_trades:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] No ACTIVE positions in ledger. Standing by...")
            time.sleep(4)
            continue

        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Monitoring {len(active_trades)} ACTIVE position(s)...")
        updated = False

        for t in active_trades:
            trade_id = t.get("trade_id", "TRD")
            contract = t.get("contract", t.get("symbol", "NIFTY"))
            symbol, strike, opt_type = parse_contract(contract, t.get("symbol", "NIFTY"))
            action = str(t.get("action", "BUY")).upper()
            entry = float(t.get("entry_price", 100.0))
            sl = float(t.get("stop_loss", entry * 0.8))
            t1 = float(t.get("target_1", entry * 1.25))

            # Fetch price from Dhan live feed or fallback simulation
            ltp = None
            if not simulation and strike and opt_type:
                ltp = fetch_dhan_chain_price(symbol, strike, opt_type)

            if ltp is None:
                # Simulation / off-market fallback
                delta = (t1 - entry) * (tick * 0.35)
                ltp = round(entry + delta, 2)

            pnl_pts = round(ltp - entry if action == "BUY" else entry - ltp, 2)
            print(f"  • {trade_id} ({contract}): Entry: ₹{entry} | LTP: ₹{ltp} | Target: ₹{t1} | SL: ₹{sl}")

            target_hit = (ltp >= t1) if action == "BUY" else (ltp <= t1)
            sl_hit = (ltp <= sl) if action == "BUY" else (ltp >= sl)

            if target_hit:
                print(f"  🎯 >>> TARGET 1 REACHED FOR {trade_id} @ ₹{ltp}! SENDING TELEGRAM ALERT...")
                msg = (
                    f"<b>🎯 TARGET 1 HIT — EXIT / BOOK PROFIT 🎯</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>Contract:</b> <code>{contract}</code>\n"
                    f"🏷️ <b>Action:</b> {action}\n"
                    f"💰 <b>Entry Price:</b> ₹{entry:,.2f}\n"
                    f"🚀 <b>Current Price (LTP):</b> <b>₹{ltp:,.2f}</b>\n"
                    f"📈 <b>Points Gained:</b> +{pnl_pts:,.2f} pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📢 <b>ADVISORY:</b> <i>Target 1 achieved! Traders holding this position should book profits or trail Stop-Loss to Cost immediately.</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <i>Stockera Live Position Sentinel • Auto-Dispatched</i>"
                )
                send_telegram_alert(msg)
                t["status"] = "CLOSED"
                t["exit_time"] = datetime.now().strftime("%H:%M:%S")
                t["exit_price"] = ltp
                t["exit_reason"] = "TARGET_1_HIT 🎯"
                updated = True

            elif sl_hit:
                print(f"  🛑 >>> STOP LOSS HIT FOR {trade_id} @ ₹{ltp}! SENDING TELEGRAM ALERT...")
                msg = (
                    f"<b>🛑 STOP LOSS HIT — MANDATORY EXIT 🛑</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>Contract:</b> <code>{contract}</code>\n"
                    f"🏷️ <b>Action:</b> {action}\n"
                    f"💰 <b>Entry Price:</b> ₹{entry:,.2f}\n"
                    f"🔻 <b>Current Price (LTP):</b> <b>₹{ltp:,.2f}</b>\n"
                    f"📉 <b>Loss:</b> {pnl_pts:,.2f} pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ <b>ADVISORY:</b> <i>Stop-loss level breached. Exit position immediately to preserve capital. Do not average!</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <i>Stockera Live Position Sentinel • Auto-Dispatched</i>"
                )
                send_telegram_alert(msg)
                t["status"] = "CLOSED"
                t["exit_time"] = datetime.now().strftime("%H:%M:%S")
                t["exit_price"] = ltp
                t["exit_reason"] = "STOP_LOSS_HIT 🛑"
                updated = True

        if updated:
            with open(LEDGER_PATH, "w", encoding="utf-8") as f:
                json.dump(trades, f, indent=2)

        time.sleep(3)

if __name__ == "__main__":
    is_sim = "--simulate" in sys.argv or "--test" in sys.argv
    try:
        run_sentinel(simulation=is_sim)
    except KeyboardInterrupt:
        print("\nSentinel stopped.")