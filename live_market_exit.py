import os
import sys
from datetime import date, datetime
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "client-id": DHAN_CLIENT_ID,
    "Content-Type": "application/json"
}

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Alert Error] {e}")

def execute_squareoff():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏱️ Executing 15:20 PM Mandatory Square-off...")

    if not supabase:
        print("❌ Supabase not connected.")
        return

    today_str = str(date.today())

    # 1. Fetch active OPEN positions for today
    res = supabase.table("trade_legs")\
        .select("*")\
        .eq("trade_date", today_str)\
        .eq("status", "OPEN")\
        .order("leg_number")\
        .execute()

    open_legs = res.data or []
    if not open_legs:
        print("ℹ️ No open positions to square off.")
        return

    # 2. Fetch nearest live option chain from Dhan for live exit fills
    exp_resp = requests.post("https://api.dhan.co/v2/optionchain/expirylist", headers=HEADERS, json={"UnderlyingScrip": 51, "UnderlyingSeg": "IDX_I"}, timeout=10)
    expiries = exp_resp.json().get("data", [])
    nearest_expiry = expiries[0] if expiries else ""

    oc_resp = requests.post("https://api.dhan.co/v2/optionchain", headers=HEADERS, json={"UnderlyingScrip": 51, "UnderlyingSeg": "IDX_I", "Expiry": nearest_expiry}, timeout=10)
    oc_data = oc_resp.json().get("data", {})
    oc_strikes = oc_data.get("oc", {})

    def get_live_price(strike_val, opt_type):
        for k, v in oc_strikes.items():
            if abs(float(k) - float(strike_val)) < 0.1:
                return float(v.get(opt_type.lower(), {}).get("last_price", 0.0))
        return 0.0

    total_gross_pnl = 0.0
    processed_legs = []

    for leg in open_legs:
        strike = float(leg["security_id"])
        opt_type = "PE" if "PE" in leg["symbol"] else "CE"
        action = leg["transaction_type"].upper()
        qty = int(leg["quantity"])
        entry_price = float(leg["entry_price"])

        # Live exit price from Dhan
        exit_price = get_live_price(strike, opt_type)
        if exit_price <= 0:
            exit_price = entry_price  # Safety fallback

        # Calculate P&L
        if action == "BUY":
            gross_pnl = round((exit_price - entry_price) * qty, 2)
        else:
            gross_pnl = round((entry_price - exit_price) * qty, 2)

        total_gross_pnl += gross_pnl

        # Update in Supabase
        supabase.table("trade_legs").update({
            "exit_price": exit_price,
            "exit_time": datetime.now().isoformat(),
            "gross_pnl": gross_pnl,
            "net_pnl": round(gross_pnl - 45.0, 2),
            "status": "CLOSED",
            "exit_trigger": "TIME_EXIT"
        }).eq("id", leg["id"]).execute()

        processed_legs.append({
            "leg_num": leg["leg_number"],
            "role": leg["leg_role"],
            "symbol": leg["symbol"],
            "action": action,
            "qty": qty,
            "entry": entry_price,
            "exit": exit_price,
            "pnl": gross_pnl
        })

    # Total friction & net
    friction = len(processed_legs) * 45.0
    net_pnl = total_gross_pnl - friction
    icon = "🟢" if net_pnl >= 0 else "🔴"

    # Telegram Message
    lines = [
        "⏱️ <b>MANDATORY SQUARE-OFF AUDIT (15:20 IST)</b>",
        f"• <b>Strategy:</b> {open_legs[0]['strategy_name']} (#{open_legs[0]['cycle_id']})",
        f"• <b>Execution Mode:</b> Time-Triggered Liquidation",
        "═" * 32,
        "<b>REALIZED POSITION AUDIT:</b>"
    ]

    for p in processed_legs:
        p_icon = "🟢" if p["pnl"] >= 0 else "🔴"
        lines.append(
            f"• <b>L{p['leg_num']} [{p['role']}]:</b> {p['action']} {p['symbol']}\n"
            f"  In: ₹{p['entry']:,.2f} ➔ Out: ₹{p['exit']:,.2f} (Qty: {p['qty']})\n"
            f"  P&L: {p_icon} ₹{p['pnl']:,.2f}"
        )

    lines.append("═" * 32)
    lines.append(f"<b>Gross Strategy P&L:</b> ₹{total_gross_pnl:,.2f}")
    lines.append(f"<b>Exchange Fees & Taxes:</b> -₹{friction:,.2f}")
    lines.append(f"<b>Net Realized P&L:</b> {icon} <b>₹{net_pnl:,.2f}</b>")
    lines.append("────────────────────────────")
    lines.append("<i>Status: CLOSED • Synced to Supabase Audit Ledger</i>")

    msg = "\n".join(lines)
    send_telegram(msg)
    print("\n" + msg)

if __name__ == "__main__":
    execute_squareoff()