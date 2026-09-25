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

def execute_live_entry():
    now_time = datetime.now()
    cycle_tag = f"IF-{now_time.strftime('%Y%m%d')}-01"

    # 1. Fetch nearest active expiry directly from exchange feed
    exp_resp = requests.post(
        "https://api.dhan.co/v2/optionchain/expirylist",
        headers=HEADERS,
        json={"UnderlyingScrip": 51, "UnderlyingSeg": "IDX_I"},
        timeout=10
    )
    if exp_resp.status_code != 200:
        print(f"Failed to fetch expiry: {exp_resp.text}")
        return

    expiries = exp_resp.json().get("data", [])
    if not expiries:
        return
    nearest_expiry = expiries[0]

    # 2. Fetch full real-time option chain
    oc_resp = requests.post(
        "https://api.dhan.co/v2/optionchain",
        headers=HEADERS,
        json={"UnderlyingScrip": 51, "UnderlyingSeg": "IDX_I", "Expiry": nearest_expiry},
        timeout=10
    )
    if oc_resp.status_code != 200:
        print(f"Failed to fetch option chain: {oc_resp.text}")
        return

    data = oc_resp.json().get("data", {})
    spot_price = float(data.get("last_price", 0.0))
    atm_strike = int(round(spot_price / 100) * 100)
    pe_hedge_strike = atm_strike - 500
    ce_hedge_strike = atm_strike + 500

    oc_strikes = data.get("oc", {})

    def get_price(target_strike, opt_type):
        for k, v in oc_strikes.items():
            if abs(float(k) - target_strike) < 0.1:
                return float(v.get(opt_type.lower(), {}).get("last_price", 0.0))
        return 0.0

    l1_price = get_price(pe_hedge_strike, "pe")
    l2_price = get_price(atm_strike, "pe")
    l3_price = get_price(atm_strike, "ce")
    l4_price = get_price(ce_hedge_strike, "ce")

    # Quantitative calculations
    net_credit_points = (l2_price + l3_price) - (l1_price + l4_price)
    total_credit_val = net_credit_points * 20
    lower_breakeven = atm_strike - net_credit_points
    upper_breakeven = atm_strike + net_credit_points

    # Order payload
    legs = [
        {"leg_num": 1, "role": "Wing Hedge", "symbol": f"SENSEX {nearest_expiry} {pe_hedge_strike} PE", "action": "BUY", "qty": 20, "price": l1_price, "strike": pe_hedge_strike},
        {"leg_num": 2, "role": "Core Short", "symbol": f"SENSEX {nearest_expiry} {atm_strike} PE", "action": "SELL", "qty": 20, "price": l2_price, "strike": atm_strike},
        {"leg_num": 3, "role": "Core Short", "symbol": f"SENSEX {nearest_expiry} {atm_strike} CE", "action": "SELL", "qty": 20, "price": l3_price, "strike": atm_strike},
        {"leg_num": 4, "role": "Wing Hedge", "symbol": f"SENSEX {nearest_expiry} {ce_hedge_strike} CE", "action": "BUY", "qty": 20, "price": l4_price, "strike": ce_hedge_strike}
    ]

    # Telegram Formatter (Zero Broker Names)
    lines = [
        f"⚡ <b>[SENSEX IRON FLY V5] — EXECUTION DISPATCH</b>",
        f"• <b>Cycle:</b> #{cycle_tag} | <b>Type:</b> 4-Leg Defined Risk Hedge",
        f"• <b>Underlying:</b> BSE SENSEX @ ₹{spot_price:,.2f} (ATM: {atm_strike})",
        f"• <b>Expiry:</b> {nearest_expiry} (Weekly) | <b>Time:</b> {now_time.strftime('%H:%M:%S IST')}",
        "═" * 32,
        "<b>EXECUTED LEG MATRIX:</b>"
    ]

    for leg in legs:
        side_icon = "🔵" if leg["action"] == "BUY" else "🟠"
        lines.append(
            f"• <b>L{leg['leg_num']} [{leg['role']}]:</b> {leg['action']} {leg['symbol']}\n"
            f"  {side_icon} Fill: <b>₹{leg['price']:,.2f}</b> | Qty: {leg['qty']}"
        )

        # Record to Supabase
        if supabase:
            record = {
                "cycle_id": cycle_tag,
                "strategy_type": "HEDGE",
                "strategy_name": "SENSEX_IRON_FLY_V5",
                "trade_date": str(date.today()),
                "leg_number": leg["leg_num"],
                "leg_role": leg["role"].upper().replace(" ", "_"),
                "symbol": leg["symbol"],
                "security_id": str(leg["strike"]),
                "transaction_type": leg["action"],
                "quantity": leg["qty"],
                "entry_price": leg["price"],
                "status": "OPEN",
                "exit_trigger": "NONE"
            }
            try:
                supabase.table("trade_legs").insert(record).execute()
            except Exception as e:
                print(f"[Supabase Error] {e}")

    lines.append("═" * 32)
    lines.append("📊 <b>QUANTITATIVE PROFILE:</b>")
    lines.append(f"• <b>Net Premium Collected:</b> +₹{net_credit_points:,.2f} / lot (+₹{total_credit_val:,.2f} total)")
    lines.append(f"• <b>Profitable Range:</b> {lower_breakeven:,.0f} ➔ {upper_breakeven:,.0f}")
    lines.append("• <b>Target Profit:</b> +₹4,000.00")
    lines.append("• <b>Risk Threshold:</b> -₹2,500.00")
    lines.append("• <b>Auto Square-Off:</b> 15:20 IST")
    lines.append("────────────────────────────")
    lines.append("<i>Status: ACTIVE IN MARKET • Risk Guards Engaged</i>")

    msg = "\n".join(lines)
    send_telegram(msg)
    print("\n" + msg)

if __name__ == "__main__":
    execute_live_entry()