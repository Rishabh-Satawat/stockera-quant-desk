import os
import uuid
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

DHAN_HEADERS = {
    "access-token": DHAN_ACCESS_TOKEN,
    "client-id": DHAN_CLIENT_ID,
    "Content-Type": "application/json",
    "Accept": "application/json"
}

def get_dhan_executed_price(order_id: str) -> float:
    if not order_id or not DHAN_ACCESS_TOKEN:
        return 0.0
    try:
        url = f"https://api.dhan.co/v2/trades/{order_id}"
        resp = requests.get(url, headers=DHAN_HEADERS, timeout=5)
        if resp.status_code == 200:
            trades = resp.json()
            if isinstance(trades, list) and len(trades) > 0:
                total_qty = sum(t.get("tradedQuantity", 0) for t in trades)
                total_val = sum(t.get("tradedQuantity", 0) * t.get("tradedPrice", 0.0) for t in trades)
                return round(total_val / total_qty, 2) if total_qty > 0 else float(trades[0].get("tradedPrice", 0.0))
            elif isinstance(trades, dict) and "tradedPrice" in trades:
                return float(trades["tradedPrice"])
        ord_resp = requests.get(f"https://api.dhan.co/v2/orders/{order_id}", headers=DHAN_HEADERS, timeout=5)
        if ord_resp.status_code == 200:
            return float(ord_resp.json().get("price", 0.0))
    except Exception as e:
        print(f"[Dhan API Error] Order {order_id}: {e}")
    return 0.0

def send_telegram_alert(message_html: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message_html, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Alert Error] {e}")

def record_trade_cycle(strategy_name: str, legs_input: list, strategy_type: str = "HEDGE", cycle_tag: str = None):
    """
    Records a full trade cycle (all 4 legs for Hedge, or 1 leg for Naked)
    into Supabase and pushes a structured alert to Telegram.
    """
    if not cycle_tag:
        cycle_tag = f"C{datetime.now().strftime('%H%M%S')}"

    processed_legs = []
    total_cycle_gross = 0.0

    for leg in legs_input:
        entry_price = float(leg.get("entry_price") or get_dhan_executed_price(leg.get("entry_order_id")) or 0.0)
        exit_price = float(leg.get("exit_price") or get_dhan_executed_price(leg.get("exit_order_id")) or 0.0)
        qty = int(leg.get("quantity", 0))
        action = leg.get("transaction_type", "BUY").upper()

        gross_pnl = round((exit_price - entry_price) * qty if action == "BUY" else (entry_price - exit_price) * qty, 2)
        total_cycle_gross += gross_pnl

        # Indian F&O friction per leg round-trip
        friction = 45.0
        net_pnl = round(gross_pnl - friction, 2)

        leg_record = {
            "cycle_id": cycle_tag,
            "strategy_type": strategy_type,
            "strategy_name": strategy_name,
            "trade_date": str(date.today()),
            "leg_number": leg.get("leg_number", 1),
            "leg_role": leg.get("leg_role", "MAIN"),
            "symbol": leg.get("symbol", ""),
            "security_id": str(leg.get("security_id", "")),
            "transaction_type": action,
            "quantity": qty,
            "entry_order_id": leg.get("entry_order_id"),
            "entry_price": entry_price,
            "exit_order_id": leg.get("exit_order_id"),
            "exit_price": exit_price,
            "status": "CLOSED",
            "gross_pnl": gross_pnl,
            "brokerage_and_taxes": friction,
            "net_pnl": net_pnl
        }

        if supabase:
            try:
                supabase.table("trade_legs").insert(leg_record).execute()
            except Exception as e:
                print(f"[Supabase Error] {e}")

        processed_legs.append(leg_record)

    # Clean instant Telegram Alert for this specific cycle
    est_cycle_friction = len(processed_legs) * 45.0
    net_cycle_pnl = total_cycle_gross - est_cycle_friction
    icon = "🟢" if net_cycle_pnl >= 0 else "🔴"

    lines = [
        f"⚡ <b>[{strategy_name}] — {cycle_tag}</b>",
        f"Type: <b>{strategy_type}</b> | Legs: <b>{len(processed_legs)}</b>",
        "────────────────────────────"
    ]
    for l in processed_legs:
        p_icon = "🟢" if l["gross_pnl"] >= 0 else "🔴"
        lines.append(f"• <b>L{l['leg_number']} ({l['leg_role']}):</b> {l['transaction_type']} {l['symbol']}")
        lines.append(f"  ₹{l['entry_price']:,.2f} ➔ ₹{l['exit_price']:,.2f} (Qty: {l['quantity']}) | P&L: {p_icon} ₹{l['gross_pnl']:,.2f}")

    lines.append("────────────────────────────")
    lines.append(f"Cycle Realized Net: {icon} <b>₹{net_cycle_pnl:,.2f}</b>")
    send_telegram_alert("\n".join(lines))
    print(f"Cycle {cycle_tag} logged and pushed.")

if __name__ == "__main__":
    print("Populating sample trade cycles to verify...")

    # Cycle 1: SENSEX Iron Fly V5 (Legs 1 to 4)
    record_trade_cycle(
        strategy_name="SENSEX_IRON_FLY_V5",
        strategy_type="HEDGE",
        cycle_tag="CYCLE-01",
        legs_input=[
            {"leg_number": 1, "leg_role": "HEDGE_BUY", "symbol": "SENSEX 80000 PE", "transaction_type": "BUY", "quantity": 20, "entry_price": 45.20, "exit_price": 12.50},
            {"leg_number": 2, "leg_role": "MAIN_SELL", "symbol": "SENSEX 80500 PE", "transaction_type": "SELL", "quantity": 20, "entry_price": 185.00, "exit_price": 42.10},
            {"leg_number": 3, "leg_role": "MAIN_SELL", "symbol": "SENSEX 80500 CE", "transaction_type": "SELL", "quantity": 20, "entry_price": 190.50, "exit_price": 65.00},
            {"leg_number": 4, "leg_role": "HEDGE_BUY", "symbol": "SENSEX 81000 CE", "transaction_type": "BUY", "quantity": 20, "entry_price": 50.10, "exit_price": 15.80}
        ]
    )

    # Cycle 2: SENSEX Iron Fly V5 Adjustment (Legs 1 to 4)
    record_trade_cycle(
        strategy_name="SENSEX_IRON_FLY_V5",
        strategy_type="HEDGE",
        cycle_tag="CYCLE-02",
        legs_input=[
            {"leg_number": 1, "leg_role": "HEDGE_BUY", "symbol": "SENSEX 80100 PE", "transaction_type": "BUY", "quantity": 20, "entry_price": 48.00, "exit_price": 20.00},
            {"leg_number": 2, "leg_role": "MAIN_SELL", "symbol": "SENSEX 80600 PE", "transaction_type": "SELL", "quantity": 20, "entry_price": 172.00, "exit_price": 55.00},
            {"leg_number": 3, "leg_role": "MAIN_SELL", "symbol": "SENSEX 80600 CE", "transaction_type": "SELL", "quantity": 20, "entry_price": 180.00, "exit_price": 70.00},
            {"leg_number": 4, "leg_role": "HEDGE_BUY", "symbol": "SENSEX 81100 CE", "transaction_type": "BUY", "quantity": 20, "entry_price": 46.00, "exit_price": 18.00}
        ]
    )

    # Naked Directional Trade
    record_trade_cycle(
        strategy_name="NIFTY_ROBUST_MOMENTUM",
        strategy_type="NAKED",
        cycle_tag="NAKED-01",
        legs_input=[
            {"leg_number": 1, "leg_role": "DIRECTIONAL", "symbol": "NIFTY 23500 CE", "transaction_type": "BUY", "quantity": 65, "entry_price": 110.00, "exit_price": 145.00}
        ]
    )