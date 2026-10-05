import os
import sys
import json
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 1. Load Secrets
load_dotenv(r"C:\kite-agent\secrets\telegram.env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

def square_off_active_trades(trades):
    """Simulates 15:20 IST EOD square-off for any active trades."""
    modified = False
    for t in trades:
        if str(t.get("status", "")).upper() == "ACTIVE":
            entry = float(t.get("entry_price", 100))
            action = str(t.get("action", "BUY")).upper()
            target = float(t.get("target_1", entry * 1.2))
            
            # Default simulation: close near target or entry if missing
            exit_price = round(target if "condor" in str(t.get("strategy", "")).lower() else entry * 1.15, 2)
            
            t["status"] = "CLOSED"
            t["exit_time"] = "15:20:00"
            t["exit_price"] = exit_price
            t["exit_reason"] = "15:20_EOD_THETA_SQUAREOFF ⏰"
            modified = True
            
    if modified:
        with open(LEDGER_PATH, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
        print("✅ Active trades squared off and updated in ledger.")
    return trades

def calculate_eod_metrics(trades):
    closed_trades = [
        t for t in trades 
        if str(t.get("status", "")).strip().upper() in ["CLOSED", "EXITED", "COMPLETED", "COMPLETE"]
        or (t.get("exit_price") is not None and float(t.get("exit_price", 0)) > 0)
    ]
    active_trades = [t for t in trades if t not in closed_trades]

    wins = []
    losses = []
    total_gross_pnl = 0.0

    for t in closed_trades:
        action = str(t.get("action", "BUY")).strip().upper()
        qty = float(t.get("qty", 0))
        entry = float(t.get("entry_price", 0))
        exit_p = float(t.get("exit_price", entry))

        if "realized_pnl" in t and t["realized_pnl"] is not None:
            pnl = float(t["realized_pnl"])
        elif "points_pnl" in t and t["points_pnl"] is not None and qty > 0:
            pnl = float(t["points_pnl"]) * qty
        else:
            pnl = (exit_p - entry) * qty if action == "BUY" else (entry - exit_p) * qty
        
        t["_computed_pnl"] = pnl
        total_gross_pnl += pnl

        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(pnl)

    total_closed = len(closed_trades)
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 1.0)
    est_charges = total_closed * 55.0
    net_pnl = total_gross_pnl - est_charges

    total_margin_active = sum(float(t.get("margin_deployed", 0)) for t in active_trades)

    return {
        "total_closed": total_closed,
        "active_open": len(active_trades),
        "total_margin_active": total_margin_active,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": win_rate,
        "gross_pnl": total_gross_pnl,
        "est_charges": est_charges,
        "net_pnl": net_pnl,
        "profit_factor": profit_factor,
        "closed_trades": closed_trades,
        "active_trades": active_trades
    }

def format_telegram_card(metrics):
    today_str = datetime.now().strftime("%d %b %Y")
    lines = [
        "<b>🏛️ STOCKERA QUANT DESK — EOD AUDIT BLOTTER</b>",
        f"<b>Date:</b> {today_str} | <b>Session Close:</b> 15:30 IST",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if metrics["total_closed"] > 0:
        pnl_sign = "🟢" if metrics["net_pnl"] >= 0 else "🔴"
        lines.extend([
            "📊 <b>Closed Performance Summary:</b>",
            f"• <b>Total Trades Settled:</b> {metrics['total_closed']}",
            f"• <b>Win / Loss:</b> {metrics['win_count']}W / {metrics['loss_count']}L ({metrics['win_rate']:.1f}% Win Rate)",
            f"• <b>Profit Factor:</b> {metrics['profit_factor']:.2f}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "💰 <b>Financial Reconciliation:</b>",
            f"• <b>Gross Realized P&L:</b> ₹{metrics['gross_pnl']:,.2f}",
            f"• <b>Est. Brokerage & STT:</b> -₹{metrics['est_charges']:,.2f}",
            f"• <b>Net Realized P&L:</b> {pnl_sign} <b>₹{metrics['net_pnl']:,.2f}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📋 <b>Recent Closed Trades:</b>"
        ])
        for t in metrics["closed_trades"][-5:]:
            trade_id = t.get("trade_id", "TRD")
            contract = t.get("contract", t.get("symbol", ""))
            pnl = t.get("_computed_pnl", 0.0)
            pnl_icon = "✅" if pnl >= 0 else "❌"
            reason = t.get("exit_reason", "MANUAL")
            lines.append(f"• {pnl_icon} <code>{trade_id}</code>: {contract} | <b>₹{pnl:+,.1f}</b> ({reason})")

    if metrics["active_open"] > 0:
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"⚠️ <b>Active Open Positions ({metrics['active_open']}):</b>",
            f"• <b>Total Margin Deployed:</b> ₹{metrics['total_margin_active']:,.2f}",
            "• <b>Status:</b> Carried overnight or awaiting 15:20 square-off"
        ])
        for t in metrics["active_trades"][-3:]:
            trade_id = t.get("trade_id", "TRD")
            contract = t.get("contract", t.get("symbol", ""))
            entry = t.get("entry_price", 0)
            lines.append(f"• ⏳ <code>{trade_id}</code>: {contract} @ ₹{entry}")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Automated EOD Reconciliation Engine • Stockera Quant</i>"
    ])
    return "\n".join(lines)

def send_telegram_card(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200, resp.json()
    except Exception as e:
        return False, str(e)

def _check_iv_stagnation(db_path: str, lookback_sessions: int = 3) -> None:
    """Warn when iv_history hasn't grown for `lookback_sessions` consecutive trading sessions.

    Reads the most recent `lookback_sessions` distinct trade_dates for each symbol;
    if none were added in the last N sessions, logs a WARNING so operators know
    that IVR/IVP calculations will degrade.
    """
    try:
        from db_init import DEFAULT_DB_PATH as _DEFAULT_DB_PATH, init_db
        import sqlite3
        from datetime import date, timedelta

        db_path = db_path or _DEFAULT_DB_PATH
        init_db(db_path)

        conn = sqlite3.connect(db_path, timeout=10)
        try:
            # Build a list of the last N calendar days (approximate trading sessions)
            today = date.today().isoformat()
            cutoff = (date.today() - timedelta(days=lookback_sessions * 2)).isoformat()

            for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
                rows = conn.execute(
                    "SELECT COUNT(*) FROM iv_history WHERE symbol=? AND trade_date >= ? AND trade_date <= ?",
                    (sym, cutoff, today),
                ).fetchone()
                count = rows[0] if rows else 0
                if count == 0:
                    logger.warning(
                        "IV_STAGNATION: no iv_history rows for %s in last %d sessions — "
                        "IVR/IVP will degrade.  Ensure record_eod_iv() is being called at 15:30 IST.",
                        sym, lookback_sessions,
                    )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("_check_iv_stagnation: failed — %s", exc)


def _record_eod_ivs_all_indices(db_path: str = None) -> None:
    """Call volatility_engine.record_eod_iv for all 4 indices at 15:30 IST close.

    Requires active chain snapshot data for today; logs a warning and continues
    for any symbol where data is unavailable.  Never raises — EOD reporting
    must complete even if IV recording partially fails.
    """
    try:
        from volatility_engine import record_eod_iv
        from expiry_calendar import get_near_expiry
        from db_init import DEFAULT_DB_PATH
    except ImportError as exc:
        logger.warning("_record_eod_ivs: import failed — %s", exc)
        return

    if db_path is None:
        db_path = DEFAULT_DB_PATH

    for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
        try:
            expiry = get_near_expiry(sym).isoformat()
        except Exception as exc:
            logger.warning("_record_eod_ivs: cannot get expiry for %s — %s", sym, exc)
            continue
        try:
            written = record_eod_iv(sym, expiry, db_path)
            if written:
                logger.info("EOD IV recorded: %s", sym)
            else:
                logger.warning("EOD IV: no valid data to record for %s", sym)
        except Exception as exc:
            logger.warning("_record_eod_ivs: record_eod_iv failed for %s — %s", sym, exc)


def main():
    if not os.path.exists(LEDGER_PATH):
        print(f"Error: {LEDGER_PATH} not found.")
        return

    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        trades = json.load(f)

    # Optional flag to square off all active trades
    if "--squareoff" in sys.argv:
        trades = square_off_active_trades(trades)

    # At 15:30 IST: persist today's ATM IV for all 4 indices into iv_history.
    # This is what makes IVR/IVP functional after the first 20 trading sessions.
    _record_eod_ivs_all_indices()
    _check_iv_stagnation(None)

    metrics = calculate_eod_metrics(trades)

    # Terminal output
    card_text = format_telegram_card(metrics)
    print("\n" + "=" * 55)
    print("TERMINAL AUDIT PREVIEW:")
    print("=" * 55)
    print(card_text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", ""))
    print("=" * 55)

    # Dispatch to Telegram
    success, res = send_telegram_card(card_text)
    if success:
        print("Telegram Dispatch Status: 200 OK (Message delivered to Telegram)")
    else:
        print(f"Telegram Dispatch Failed: {res}")

if __name__ == "__main__":
    main()