import os
import json
import re
import time
from datetime import datetime, date
import requests
from dotenv import load_dotenv
from supabase import create_client, Client
from kiteconnect import KiteConnect

load_dotenv()

# --- Configurations ---
LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"
HISTORY_CSV = r"C:\kite-agent\trades_history.csv"

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
KITE_API_KEY = os.getenv("KITE_API_KEY", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

sp_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

DHAN_HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "client-id": DHAN_CLIENT_ID,
    "Content-Type": "application/json"
}

def send_telegram_alert(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Notice] {e}")

# --- 1. LIVE OPTION LTP FETCHER ---
def get_live_option_ltp(underlying: str, strike: float, opt_type: str) -> float:
    """Fetches real-time market price directly from Dhan Option Chain."""
    if not DHAN_ACCESS_TOKEN or not DHAN_CLIENT_ID:
        return 0.0

    sec_id = 51 if "SENSEX" in underlying.upper() else 13
    try:
        # Get nearest active expiry
        r_exp = requests.post("https://api.dhan.co/v2/optionchain/expirylist", headers=DHAN_HEADERS, json={"UnderlyingScrip": sec_id, "UnderlyingSeg": "IDX_I"}, timeout=5)
        if r_exp.status_code == 200:
            expiries = r_exp.json().get("data", [])
            if expiries:
                nearest_exp = expiries[0]
                # Get option chain
                r_oc = requests.post("https://api.dhan.co/v2/optionchain", headers=DHAN_HEADERS, json={"UnderlyingScrip": sec_id, "UnderlyingSeg": "IDX_I", "Expiry": nearest_exp}, timeout=5)
                if r_oc.status_code == 200:
                    oc = r_oc.json().get("data", {}).get("oc", {})
                    for k, v in oc.items():
                        if abs(float(k) - strike) < 0.1:
                            return float(v.get(opt_type.lower(), {}).get("last_price", 0.0))
    except Exception as e:
        print(f"[Price Fetch Error] {e}")

    return 0.0

# --- 2. STT EXPOSURE SAFEGUARD ---
def check_stt_threat(contract: str, spot: float, qty: int):
    matches = re.findall(r"(\d+)\s*(CE|PE)", contract)
    is_itm = False
    notional_exposure = 0.0
    stt_tax_risk = 0.0

    for strike_str, opt_type in matches:
        strike = float(strike_str)
        if opt_type == "CE" and spot > strike:
            is_itm = True
            notional_exposure += (strike * qty)
        elif opt_type == "PE" and spot < strike:
            is_itm = True
            notional_exposure += (strike * qty)

    if is_itm:
        stt_tax_risk = round(notional_exposure * 0.00125, 2)
    return is_itm, stt_tax_risk

# --- 3. CORE SENTINEL MONITORING CYCLE ---
def run_sentinel_cycle():
    now_time = datetime.now()
    now_str = now_time.strftime("%H:%M:%S")
    is_eod_window = now_time.time() >= datetime.strptime("15:20", "%H:%M").time()

    # Load active local trades
    trades = []
    if os.path.exists(LEDGER_FILE):
        try:
            with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
                trades = json.load(f)
        except Exception:
            trades = []

    active_trades = [t for t in trades if t.get("status") == "ACTIVE"]

    if not active_trades:
        print(f"[{now_str}] 🛡️ AURA Sentinel: No active directional positions to guard.")
        return

    print(f"[{now_str}] 🛡️ AURA Sentinel: Guarding {len(active_trades)} active positions...")

    for t in active_trades:
        contract = t.get("contract", "")
        sym = t.get("symbol", "NIFTY")
        qty = int(t.get("qty", 1))
        entry_price = float(t.get("entry_price", 0.0))
        sl = float(t.get("stop_loss", entry_price * 0.80))
        t1 = float(t.get("target_1", entry_price * 1.25))
        t2 = float(t.get("target_2", entry_price * 1.50))

        # Parse strike & option type from contract string
        match = re.search(r"(\d+)\s*(CE|PE)", contract)
        if not match:
            continue
        strike = float(match.group(1))
        opt_type = match.group(2)

        # Get live market tick
        live_ltp = get_live_option_ltp(sym, strike, opt_type)
        if live_ltp <= 0.0:
            continue

        pnl_pts = round(live_ltp - entry_price, 2)
        realized_pnl = round(pnl_pts * qty, 2)

        # CHECK 1: TARGET 2 HIT (+50%) -> FULL PROFIT BOOK
        if live_ltp >= t2:
            t["status"] = "CLOSED"
            t["exit_price"] = live_ltp
            t["exit_time"] = now_str
            t["exit_reason"] = "TARGET_2_HIT 🚀"
            t["realized_pnl"] = realized_pnl
            
            msg = f"""🚀 *AURA SENTINEL: TARGET 2 REACHED (+50%)* 🚀
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Contract:* `{contract}`
💰 *Entry Fill:* ₹{entry_price:.2f} ➔ *Exit:* ₹{live_ltp:.2f}
📈 *Net Points:* {pnl_pts:+.2f} pts
💵 *Realized Profit:* 🟢 +₹{realized_pnl:,.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Runner target achieved. Position 100% liquidated.*"""
            print(f"\n{msg}\n")
            send_telegram_alert(msg)

        # CHECK 2: TARGET 1 HIT (+25%) -> TRAIL SL TO COST
        elif live_ltp >= t1 and not t.get("target_1_hit"):
            t["target_1_hit"] = True
            t["stop_loss"] = entry_price  # Move SL to Breakeven
            
            msg = f"""🎯 *AURA SENTINEL: TARGET 1 REACHED (+25%)* 🎯
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Contract:* `{contract}`
💰 *Current CMP:* ₹{live_ltp:.2f} (Entry: ₹{entry_price:.2f})
📈 *Unrealized Gain:* +₹{realized_pnl:,.2f}
🛡️ *Action:* Stop-Loss Trailed to Breakeven (₹{entry_price:.2f})
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Risk-Free Trade Engaged. Holding runner for Target 2.*"""
            print(f"\n{msg}\n")
            send_telegram_alert(msg)

        # CHECK 3: HARD STOP LOSS HIT (-20%)
        elif live_ltp <= sl:
            t["status"] = "CLOSED"
            t["exit_price"] = live_ltp
            t["exit_time"] = now_str
            t["exit_reason"] = "STOP_LOSS_HIT 🛑"
            t["realized_pnl"] = realized_pnl

            msg = f"""🛑 *AURA SENTINEL: HARD STOP LOSS HIT* 🛑
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Contract:* `{contract}`
💰 *Entry Fill:* ₹{entry_price:.2f} ➔ *Exit:* ₹{live_ltp:.2f}
📉 *Net Loss:* {pnl_pts:.2f} pts (-₹{abs(realized_pnl):,.2f})
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Risk threshold reached. Capital shielded.*"""
            print(f"\n{msg}\n")
            send_telegram_alert(msg)

        # CHECK 4: 15:20 EOD SQUARE-OFF WINDOW
        elif is_eod_window:
            t["status"] = "CLOSED"
            t["exit_price"] = live_ltp
            t["exit_time"] = now_str
            t["exit_reason"] = "EOD_AUTO_SQUAREOFF ⏰"
            t["realized_pnl"] = realized_pnl

            msg = f"""⏰ *AURA SENTINEL: 15:20 EOD LIQUIDATION* ⏰
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Contract:* `{contract}`
📈 *Exit Fill:* ₹{live_ltp:.2f}
💵 *Realized P&L:* ₹{realized_pnl:+,.2f}
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Position squared off cleanly before market close.*"""
            print(f"\n{msg}\n")
            send_telegram_alert(msg)

    # Save updated ledger
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)

    # Sync with Supabase cloud
    try:
        from supabase_sync import sync_trades_to_supabase
        sync_trades_to_supabase()
    except Exception:
        pass

if __name__ == "__main__":
    run_sentinel_cycle()