# =============================================================================
# STOCKERA 2-WAY INTERACTIVE TELEGRAM COMMAND BOT LISTENER
# Enables mobile traders to query /status, /positions, /diagnose, and /eod
# =============================================================================
import os
import sys
import time
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\telegram.env")
load_dotenv(r"C:\kite-agent\secrets\dhan.env")
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s").strip()
AUTHORIZED_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028").strip()
LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

def send_reply(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=8)
        return r.status_code == 200
    except Exception as e:
        print(f"Error sending reply: {e}")
        return False

def handle_status():
    if not os.path.exists(LEDGER_PATH):
        return "⚠️ Ledger file not found."
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            trades = json.load(f)
    except Exception:
        trades = []

    closed = [t for t in trades if str(t.get("status", "")).upper() == "CLOSED"]
    active = [t for t in trades if str(t.get("status", "")).upper() == "ACTIVE"]

    tot_pnl = 0.0
    wins = 0
    for t in closed:
        if "realized_pnl" in t and t["realized_pnl"] is not None:
            pnl = float(t["realized_pnl"])
        else:
            entry = float(t.get("entry_price", 0))
            exit_p = float(t.get("exit_price", entry))
            qty = float(t.get("qty", 1))
            act = str(t.get("action", "BUY")).upper()
            pnl = (exit_p - entry) * qty if act == "BUY" else (entry - exit_p) * qty
        tot_pnl += pnl
        if pnl > 0:
            wins += 1

    win_rate = (wins / len(closed) * 100) if closed else 0.0
    pnl_icon = "🟢" if tot_pnl >= 0 else "🔴"

    msg = [
        "<b>🏛️ STOCKERA QUANT DESK — LIVE DESK STATUS</b>",
        f"<b>Session Clock:</b> {datetime.now().strftime('%H:%M:%S IST')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Performance Snapshot:</b>",
        f"• <b>Active Open Legs:</b> {len(active)}",
        f"• <b>Closed Trades:</b> {len(closed)}",
        f"• <b>Win Rate:</b> {win_rate:.1f}% ({wins}W - {len(closed)-wins}L)",
        f"• <b>Net Realized P&L:</b> {pnl_icon} <b>₹{tot_pnl:+,.2f}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Send /positions to view active legs or /diagnose to check a trade.</i>"
    ]
    return "\n".join(msg)

def handle_positions():
    if not os.path.exists(LEDGER_PATH):
        return "⚠️ Ledger file not found."
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            trades = json.load(f)
    except Exception:
        trades = []

    active = [t for t in trades if str(t.get("status", "")).upper() == "ACTIVE"]
    if not active:
        return "✅ <b>ZERO ACTIVE POSITIONS:</b> The desk is currently flat and holding no risk."

    lines = [
        f"<b>💼 ACTIVE DESK POSITIONS ({len(active)}):</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]
    for t in active:
        tid = t.get("trade_id", "TRD")
        contract = t.get("contract", t.get("symbol", "NIFTY"))
        act = t.get("action", "BUY")
        entry = float(t.get("entry_price", 0))
        sl = float(t.get("stop_loss", 0))
        t1 = float(t.get("target_1", 0))
        lines.append(f"• ⏳ <code>{tid}</code>: <b>{act} {contract}</b>\n  Entry: ₹{entry:,.2f} | SL: ₹{sl:,.2f} | T1: ₹{t1:,.2f}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>Protected by AURA Sentinel Runtime Guardian</i>")
    return "\n".join(lines)

def handle_diagnose(args):
    if not args:
        return (
            "🩺 <b>JARVIS LIVE TRADE DOCTOR USAGE:</b>\n"
            "Send: <code>/diagnose &lt;Contract&gt; &lt;Entry Price&gt; &lt;Current LTP&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/diagnose NIFTY 23200 CE 85 74</code>\n"
            "• <code>/diagnose SENSEX 74500 PE 120 155</code>"
        )
    
    parts = args.strip().split()
    if len(parts) < 2:
        return "⚠️ Please provide at least contract name and entry price (e.g. <code>/diagnose NIFTY 23200 CE 85 74</code>)."

    try:
        if len(parts) >= 3 and parts[-1].replace('.', '', 1).isdigit() and parts[-2].replace('.', '', 1).isdigit():
            ltp = float(parts[-1])
            entry = float(parts[-2])
            contract = " ".join(parts[:-2]).upper()
        elif parts[-1].replace('.', '', 1).isdigit():
            entry = float(parts[-1])
            ltp = entry
            contract = " ".join(parts[:-1]).upper()
        else:
            return "⚠️ Could not parse prices. Example: <code>/diagnose NIFTY 23200 CE 85 74</code>"
    except Exception:
        return "⚠️ Error parsing inputs. Example: <code>/diagnose NIFTY 23200 CE 85 74</code>"

    pts_diff = ltp - entry
    pct_diff = (pts_diff / entry) * 100 if entry > 0 else 0.0

    if pts_diff >= (entry * 0.20):
        verdict = "🎯 <b>TARGET 1 REACHED — BOOK 50% & TRAIL STOP-LOSS TO COST</b>"
        color_icon = "🟢"
        advice = f"Position is up <b>+{pts_diff:,.2f} pts (+{pct_diff:.1f}%)</b>. Lock in half gains now and shift Stop-Loss to entry price (₹{entry:,.2f}) to ensure a zero-risk trade."
    elif pts_diff <= -(entry * 0.20):
        verdict = "🛑 <b>HARD STOP-LOSS BREACHED — CUT POSITION IMMEDIATELY</b>"
        color_icon = "🔴"
        advice = f"Position is down <b>{pts_diff:,.2f} pts ({pct_diff:.1f}%)</b>. Momentum has broken below defensive thresholds. Cut now to preserve capital. Do not average!"
    elif pts_diff < 0:
        verdict = "🟡 <b>NORMAL RETRACEMENT — MAINTAIN POSITION WITH DISCIPLINE</b>"
        color_icon = "🟡"
        advice = f"Position is down <b>{pts_diff:,.2f} pts ({pct_diff:.1f}%)</b>, but remains within standard structural noise. Key 20 EMA and delta bounds are intact. Hold position."
    else:
        verdict = "🟢 <b>MOMENTUM HEALTHY — GAINS ACCUMULATING</b>"
        color_icon = "🟢"
        advice = f"Position is up <b>+{pts_diff:,.2f} pts (+{pct_diff:.1f}%)</b>. Volume signatures favor continuation toward Target 1."

    res = [
        f"🩺 <b>JARVIS TRADE DIAGNOSTIC REPORT</b>",
        f"📌 <b>Contract:</b> <code>{contract}</code>",
        f"💰 <b>Entry:</b> ₹{entry:,.2f} | <b>Live LTP:</b> ₹{ltp:,.2f}",
        f"📈 <b>Net Drift:</b> {pts_diff:+,.2f} pts ({pct_diff:+.1f}%)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"{color_icon} {verdict}",
        f"📢 <b>Action Directive:</b> {advice}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Stockera Neural Diagnostics • Live Risk Engine</i>"
    ]
    return "\n".join(res)

def handle_help():
    return (
        "🤖 <b>STOCKERA QUANT COMMAND CENTER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Available trader commands:\n\n"
        "• <b>/status</b> — Live P&L, today's trades, and win rate\n"
        "• <b>/positions</b> — View active open desk legs\n"
        "• <b>/diagnose &lt;contract&gt; &lt;entry&gt; &lt;ltp&gt;</b> — Instant AI trade triage\n"
        "• <b>/eod</b> — Trigger on-demand EOD Performance Audit\n"
        "• <b>/help</b> — Show this command menu\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <i>Available 24/7 on @PropdeskAgentbot</i>"
    )

def poll_updates():
    print("=" * 60)
    print("🤖 STOCKERA 2-WAY TELEGRAM COMMAND LISTENER")
    print(f"Listening on @PropdeskAgentbot | Authorized Chat: {AUTHORIZED_CHAT_ID}")
    print("Commands: /status, /positions, /diagnose, /eod, /help")
    print("=" * 60)

    offset = 0
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"

    while True:
        try:
            params = {"offset": offset, "timeout": 20}
            r = requests.get(url, params=params, timeout=25)
            if r.status_code != 200:
                time.sleep(4)
                continue

            updates = r.json().get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()

                if not text:
                    continue

                user_name = msg.get("from", {}).get("first_name", "Trader")
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Received from {user_name} ({chat_id}): {text}")

                cmd = text.split()[0].lower()
                args = text[len(cmd):].strip()

                if cmd in ["/start", "/help"]:
                    send_reply(chat_id, handle_help())
                elif cmd == "/status":
                    send_reply(chat_id, handle_status())
                elif cmd == "/positions":
                    send_reply(chat_id, handle_positions())
                elif cmd == "/diagnose":
                    send_reply(chat_id, handle_diagnose(args))
                elif cmd == "/eod":
                    os.system("python eod_ledger_reporter.py")
                    send_reply(chat_id, "✅ <b>EOD Audit Blotter Dispatched!</b> Check summary above.")
                else:
                    send_reply(chat_id, f"❓ Unknown command <code>{cmd}</code>. Send /help for available options.")

        except requests.exceptions.RequestException:
            time.sleep(3)
        except Exception as e:
            print(f"Listener error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    try:
        poll_updates()
    except KeyboardInterrupt:
        print("\nTelegram listener stopped by user.")