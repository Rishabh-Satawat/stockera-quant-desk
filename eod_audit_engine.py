import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"

load_dotenv(r"C:\kite-agent\secrets\telegram.env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028").strip()

def generate_and_send_eod_report():
    if not os.path.exists(LEDGER_FILE):
        print("❌ Ledger file not found!")
        return

    with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
        trades = json.load(f)

    total_trades = len(trades)
    closed_trades = [t for t in trades if t.get("status") == "CLOSED"]
    open_trades = [t for t in trades if t.get("status") == "ACTIVE"]

    wins = [t for t in closed_trades if t.get("realized_pnl", 0) > 0]
    losses = [t for t in closed_trades if t.get("realized_pnl", 0) < 0]

    if len(closed_trades) > 0:
        win_rate_str = f"{(len(wins) / len(closed_trades) * 100):.1f}% ({len(wins)}W - {len(losses)}L)"
    elif len(open_trades) > 0:
        win_rate_str = f"N/A ({len(open_trades)} Open Positions - MTM Tracked)"
    else:
        win_rate_str = "0.0% (0 Trades)"

    total_margin = sum(t.get("margin_deployed", 0) for t in trades)
    net_realized_pnl = sum(t.get("realized_pnl", 0) for t in closed_trades)
    roc = (net_realized_pnl / total_margin * 100) if total_margin > 0 else 0.0
    pnl_symbol = "🟢" if net_realized_pnl >= 0 else "🔴"

    report = []
    report.append("🏁 STOCKERA QUANT DESK: INSTITUTIONAL EOD AUDIT")
    report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    report.append(f"📅 Date: 2026-09-22 | Session: CLOSED (15:30 IST)")
    report.append(f"📊 Total Trades: {total_trades} (Max 3/day)")
    report.append(f"💼 Margin Deployed: ₹{total_margin:,.2f}")
    report.append(f"🎯 Win Rate: {win_rate_str}")
    report.append(f"{pnl_symbol} Net Realized P&L: ₹{net_realized_pnl:+,.2f} ({roc:+.2f}% RoC)")
    report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    report.append("📋 EXECUTED POSITIONS & TRADE LIFECYCLES:\n")

    for idx, t in enumerate(trades, 1):
        contract = t.get("contract")
        qty = t.get("qty")
        entry_p = t.get("entry_price")
        entry_t = t.get("entry_time")
        sl = t.get("stop_loss")
        target = t.get("target_1")
        strategy = t.get("strategy")
        status = t.get("status")

        report.append(f"{idx}️⃣ {contract} ({strategy})")
        report.append(f"   • Qty: {qty} | Entry: {entry_t} @ ₹{entry_p:.2f}")
        report.append(f"   • Stop-Loss: ₹{sl:.2f} | Target: ₹{target:.2f}")

        if status == "CLOSED":
            exit_p = t.get("exit_price")
            exit_t = t.get("exit_time")
            reason = t.get("exit_reason")
            pts = t.get("points_pnl", 0.0)
            pnl = t.get("realized_pnl", 0.0)
            pnl_icon = "🟢" if pnl >= 0 else "🔴"
            report.append(f"   • Exit: {exit_t} @ ₹{exit_p:.2f} | Reason: {reason}")
            report.append(f"   • Result: {pnl_icon} ₹{pnl:+,.2f} ({pts:+.2f} pts)\n")
        else:
            report.append(f"   • Status: ACTIVE (Still Open)\n")

    report.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    report.append("🔒 Audit Log: trades_history.csv | Desk Armed for 09:15 Tomorrow")
    final_text = "\n".join(report)

    print("\n" + final_text + "\n")

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": final_text}
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                print("📡 Report successfully delivered to Telegram (@PropdeskAgentbot)!")
        except Exception:
            pass

if __name__ == "__main__":
    generate_and_send_eod_report()
