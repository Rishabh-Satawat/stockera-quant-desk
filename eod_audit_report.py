import os
from datetime import date, datetime
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if (SUPABASE_URL and SUPABASE_KEY) else None

# Account sizing for ROI calculation (₹50,000 standard desk allocation)
ACCOUNT_CAPITAL = 50000.0

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=5)

def run_eod_audit(target_date: str = None):
    if not target_date:
        target_date = str(date.today())

    if not supabase:
        print("[Error] Supabase not connected.")
        return

    res = supabase.table("trade_legs")\
        .select("*")\
        .eq("trade_date", target_date)\
        .order("created_at")\
        .order("leg_number")\
        .execute()

    records = res.data or []
    if not records:
        print(f"No records found for {target_date}")
        return

    # Separate Hedge cycles from Naked trades
    hedge_cycles = {}
    naked_trades = []

    for r in records:
        if r.get("strategy_type") == "NAKED":
            naked_trades.append(r)
        else:
            cid = r.get("cycle_id", "DEFAULT")
            if cid not in hedge_cycles:
                hedge_cycles[cid] = {"strategy": r["strategy_name"], "legs": []}
            hedge_cycles[cid]["legs"].append(r)

    total_gross = 0.0
    total_friction = 0.0
    total_orders = 0

    lines = [
        f"📊 <b>END-OF-DAY DESK AUDIT REPORT</b>",
        f"📅 Date: <b>{target_date}</b> | Capital: <b>₹{ACCOUNT_CAPITAL:,.0f}</b>",
        "═" * 32
    ]

    # --- SECTION 1: HEDGE STRATEGIES (Cycle by Cycle) ---
    if hedge_cycles:
        lines.append("\n🛡️ <b>HEDGE STRATEGIES (MULTI-LEG)</b>")
        lines.append("────────────────────────────")

        for idx, (cid, data) in enumerate(hedge_cycles.items(), start=1):
            s_name = data["strategy"]
            legs = sorted(data["legs"], key=lambda x: x.get("leg_number", 1))
            
            cycle_gross = sum(float(l["gross_pnl"]) for l in legs)
            cycle_fric = sum(float(l.get("brokerage_and_taxes", 45.0)) for l in legs)
            cycle_net = cycle_gross - cycle_fric
            c_icon = "🟢" if cycle_net >= 0 else "🔴"

            lines.append(f"<b>[Strategy #{idx}] {s_name} ({cid})</b>")
            for l in legs:
                l_icon = "🟢" if float(l["gross_pnl"]) >= 0 else "🔴"
                lines.append(
                    f"  ├ Leg {l['leg_number']} [{l['leg_role']}]: {l['transaction_type']} {l['symbol']}\n"
                    f"  │ In: ₹{float(l['entry_price']):,.2f} | Out: ₹{float(l['exit_price']):,.2f} | Qty: {l['quantity']}\n"
                    f"  │ Leg P&L: {l_icon} ₹{float(l['gross_pnl']):,.2f}"
                )
            lines.append(f"  └ <b>Cycle Net P&L:</b> {c_icon} <b>₹{cycle_net:,.2f}</b> (Friction: ₹{cycle_fric:,.2f})\n")

            total_gross += cycle_gross
            total_friction += cycle_fric
            total_orders += len(legs) * 2

    # --- SECTION 2: NAKED / DIRECTIONAL TRADES ---
    if naked_trades:
        lines.append("⚡ <b>NAKED / DIRECTIONAL TRADES</b>")
        lines.append("────────────────────────────")
        for idx, t in enumerate(naked_trades, start=1):
            pnl = float(t["gross_pnl"])
            fric = float(t.get("brokerage_and_taxes", 45.0))
            net = pnl - fric
            n_icon = "🟢" if net >= 0 else "🔴"

            lines.append(
                f"<b>[Trade #{idx}] {t['strategy_name']}</b> ({t['symbol']})\n"
                f"  In: ₹{float(t['entry_price']):,.2f} | Out: ₹{float(t['exit_price']):,.2f} | Qty: {t['quantity']}\n"
                f"  Net: {n_icon} ₹{net:,.2f} (Gross: ₹{pnl:,.2f} | Fees: ₹{fric:,.2f})\n"
            )

            total_gross += pnl
            total_friction += fric
            total_orders += 2

    # --- SECTION 3: COMBINED EXECUTIVE MATRIX ---
    total_net = total_gross - total_friction
    net_roi = (total_net / ACCOUNT_CAPITAL) * 100
    perf_icon = "🟢" if total_net >= 0 else "🔴"

    lines.append("═" * 32)
    lines.append("📈 <b>COMBINED PERFORMANCE MATRIX</b>")
    lines.append("────────────────────────────")
    lines.append(f"• Total Executed Orders: <b>{total_orders}</b>")
    lines.append(f"• Total Gross P&L: <b>₹{total_gross:,.2f}</b>")
    lines.append(f"• Statutory Friction: <b>-₹{total_friction:,.2f}</b>")
    lines.append(f"• <b>Net Realized P&L:</b> {perf_icon} <b>₹{total_net:,.2f}</b>")
    lines.append(f"• <b>Net Daily ROI:</b> {perf_icon} <b>{net_roi:+.2f}%</b>")
    lines.append("═" * 32)
    lines.append(f"<i>Source: Dhan Live API Fills & Supabase Sync</i>")

    report_text = "\n".join(lines)
    print("\n" + report_text)
    send_telegram(report_text)

if __name__ == "__main__":
    run_eod_audit()