import os
import requests
from datetime import date, datetime
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

DHAN_HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "client-id": DHAN_CLIENT_ID,
    "Content-Type": "application/json",
    "Accept": "application/json"
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

def get_dhan_fill(order_id: str) -> float:
    if not order_id or not DHAN_ACCESS_TOKEN:
        return 0.0
    try:
        url = f"https://api.dhan.co/v2/trades/{order_id}"
        resp = requests.get(url, headers=DHAN_HEADERS, timeout=5)
        if resp.status_code == 200:
            trades = resp.json()
            if isinstance(trades, list) and len(trades) > 0:
                tot_qty = sum(t.get("tradedQuantity", 0) for t in trades)
                tot_val = sum(t.get("tradedQuantity", 0) * t.get("tradedPrice", 0.0) for t in trades)
                return round(tot_val / tot_qty, 2) if tot_qty > 0 else float(trades[0].get("tradedPrice", 0.0))
    except Exception as e:
        print(f"[Dhan Fill Fetch Error] {e}")
    return 0.0

# -------------------------------------------------------------
# 1. TRADE ENTRY EVENT
# -------------------------------------------------------------
def trigger_entry(strategy_name: str, cycle_id: str, strategy_type: str, legs_data: list, target_amt: float, sl_amt: float):
    """
    Called at 09:15 AM when orders are executed.
    Inserts status='OPEN' in Supabase and pushes the Entry Alert.
    """
    lines = [
        f"🚀 <b>TRADE ENTRY TRIGGERED</b>",
        f"<b>Strategy:</b> {strategy_name} ({cycle_id})",
        f"<b>Type:</b> {strategy_type} | <b>Legs:</b> {len(legs_data)}",
        f"<b>Time:</b> {datetime.now().strftime('%H:%M:%S IST')}",
        "═" * 32,
        "<b>EXECUTED POSITIONS:</b>"
    ]

    for leg in legs_data:
        entry_price = float(leg.get("entry_price") or get_dhan_fill(leg.get("entry_order_id")) or 0.0)
        leg["entry_price"] = entry_price

        lines.append(
            f"• <b>L{leg.get('leg_number', 1)} [{leg.get('leg_role', 'LEG')}]:</b> {leg.get('transaction_type')} {leg.get('symbol')}\n"
            f"  Fill Price: ₹{entry_price:,.2f} | Qty: {leg.get('quantity')}"
        )

        # Record into Supabase as OPEN
        if supabase:
            record = {
                "cycle_id": cycle_id,
                "strategy_type": strategy_type,
                "strategy_name": strategy_name,
                "trade_date": str(date.today()),
                "leg_number": leg.get("leg_number", 1),
                "leg_role": leg.get("leg_role", "MAIN"),
                "symbol": leg.get("symbol", ""),
                "security_id": str(leg.get("security_id", "")),
                "transaction_type": leg.get("transaction_type", "BUY"),
                "quantity": leg.get("quantity", 0),
                "entry_order_id": leg.get("entry_order_id"),
                "entry_price": entry_price,
                "status": "OPEN",
                "exit_trigger": "NONE"
            }
            try:
                supabase.table("trade_legs").insert(record).execute()
            except Exception as e:
                print(f"[Supabase Entry Error] {e}")

    lines.append("═" * 32)
    lines.append(f"🎯 <b>Target:</b> +₹{target_amt:,.2f} | 🛑 <b>Stop Loss:</b> -₹{sl_amt:,.2f}")
    lines.append("<i>Live tracking active. Signals synced to Streamlit & Supabase.</i>")

    msg = "\n".join(lines)
    send_telegram(msg)
    print("\n[Entry Trigger Pushed to Telegram]")

# -------------------------------------------------------------
# 2. EXIT EVENTS: TARGET HIT / STOP LOSS HIT / SQUARE-OFF
# -------------------------------------------------------------
def trigger_exit(strategy_name: str, cycle_id: str, exit_reason: str, legs_data: list):
    """
    Called when Target Hits, Stop Loss Hits, or at 15:20 Scheduled Exit.
    exit_reason must be: 'TARGET_HIT', 'STOP_LOSS_HIT', or 'TIME_EXIT'
    """
    if exit_reason == "TARGET_HIT":
        header = "🎯 <b>PROFIT TARGET HIT!</b>"
        theme_icon = "🟢"
    elif exit_reason == "STOP_LOSS_HIT":
        header = "🛑 <b>STOP LOSS TRIGGERED!</b>"
        theme_icon = "🔴"
    else:
        header = "⏱️ <b>SCHEDULED SQUARE-OFF (15:20 IST)</b>"
        theme_icon = "🔵"

    lines = [
        header,
        f"<b>Strategy:</b> {strategy_name} ({cycle_id})",
        f"<b>Trigger Time:</b> {datetime.now().strftime('%H:%M:%S IST')}",
        "═" * 32,
        "<b>EXIT AUDIT BREAKDOWN:</b>"
    ]

    total_gross = 0.0
    for leg in legs_data:
        entry_price = float(leg.get("entry_price") or 0.0)
        exit_price = float(leg.get("exit_price") or get_dhan_fill(leg.get("exit_order_id")) or 0.0)
        qty = int(leg.get("quantity", 0))
        action = leg.get("transaction_type", "BUY").upper()

        gross_pnl = round((exit_price - entry_price) * qty if action == "BUY" else (entry_price - exit_price) * qty, 2)
        total_gross += gross_pnl

        l_icon = "🟢" if gross_pnl >= 0 else "🔴"
        lines.append(
            f"• <b>L{leg.get('leg_number', 1)} [{leg.get('leg_role', 'LEG')}]:</b> {action} {leg.get('symbol')}\n"
            f"  Entry: ₹{entry_price:,.2f} ➔ Exit: ₹{exit_price:,.2f} (Qty: {qty})\n"
            f"  P&L: {l_icon} ₹{gross_pnl:,.2f}"
        )

        # Update in Supabase
        if supabase:
            try:
                supabase.table("trade_legs")\
                    .update({
                        "exit_price": exit_price,
                        "exit_order_id": leg.get("exit_order_id"),
                        "exit_time": datetime.now().isoformat(),
                        "gross_pnl": gross_pnl,
                        "net_pnl": gross_pnl - 45.0,
                        "status": "CLOSED",
                        "exit_trigger": exit_reason
                    })\
                    .eq("cycle_id", cycle_id)\
                    .eq("leg_number", leg.get("leg_number", 1))\
                    .execute()
            except Exception as e:
                print(f"[Supabase Exit Update Error] {e}")

    friction = len(legs_data) * 45.0
    net_pnl = total_gross - friction
    p_icon = "🟢" if net_pnl >= 0 else "🔴"

    lines.append("═" * 32)
    lines.append(f"<b>Gross P&L:</b> ₹{total_gross:,.2f}")
    lines.append(f"<b>Statutory Friction:</b> -₹{friction:,.2f}")
    lines.append(f"<b>Net Realized P&L:</b> {p_icon} <b>₹{net_pnl:,.2f}</b>")
    lines.append(f"<b>Status:</b> Position fully closed & archived.")

    msg = "\n".join(lines)
    send_telegram(msg)
    print(f"\n[{exit_reason} Alert Pushed to Telegram]")

# -------------------------------------------------------------
# Test Simulation
# -------------------------------------------------------------
if __name__ == "__main__":
    print("Testing Trade Event Lifecycle...")

    # Sample 4-Leg Structure
    sample_legs = [
        {"leg_number": 1, "leg_role": "HEDGE_BUY", "symbol": "SENSEX 80000 PE", "transaction_type": "BUY", "quantity": 20, "entry_price": 45.20, "exit_price": 12.50},
        {"leg_number": 2, "leg_role": "MAIN_SELL", "symbol": "SENSEX 80500 PE", "transaction_type": "SELL", "quantity": 20, "entry_price": 185.00, "exit_price": 42.10},
        {"leg_number": 3, "leg_role": "MAIN_SELL", "symbol": "SENSEX 80500 CE", "transaction_type": "SELL", "quantity": 20, "entry_price": 190.50, "exit_price": 65.00},
        {"leg_number": 4, "leg_role": "HEDGE_BUY", "symbol": "SENSEX 81000 CE", "transaction_type": "BUY", "quantity": 20, "entry_price": 50.10, "exit_price": 15.80}
    ]

    # Test Target Hit Trigger
    trigger_exit(
        strategy_name="SENSEX_IRON_FLY_V5",
        cycle_id="CYCLE-LIVE-01",
        exit_reason="TARGET_HIT",
        legs_data=sample_legs
    )