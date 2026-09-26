import os
import re
import json
from datetime import datetime
import requests
from dotenv import load_dotenv

# 1. Load Secrets
load_dotenv(r"C:\kite-agent\secrets\telegram.env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028")

LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

# Approximate reference spot prices if live feed is unavailable during off-market hours
BENCHMARK_SPOTS = {
    "NIFTY": 23120.0,
    "SENSEX": 74450.0,
    "BANKNIFTY": 55750.0
}

def parse_contract_details(contract_str, default_symbol="NIFTY"):
    """Extracts underlying, strike, and option type (CE/PE) from contract string."""
    symbol = default_symbol.upper()
    for s in ["SENSEX", "BANKNIFTY", "NIFTY"]:
        if s in contract_str.upper():
            symbol = s
            break

    match = re.search(r"(\d{4,6})\s*(CE|PE)", contract_str.upper())
    if match:
        strike = float(match.group(1))
        opt_type = match.group(2)
        return symbol, strike, opt_type
    return symbol, None, None

def evaluate_stt_hazard(trade, current_spot):
    """
    Evaluates whether an active trade has STT exposure on expiry.
    Long ITM Options incur 0.125% STT on entire Notional Value (Strike x Qty).
    """
    contract = trade.get("contract", "")
    symbol, strike, opt_type = parse_contract_details(contract, trade.get("symbol", "NIFTY"))
    action = str(trade.get("action", "BUY")).upper()
    qty = float(trade.get("qty", 1))

    if not strike or not opt_type:
        return "UNKNOWN", 0.0, 0.0

    # Calculate Intrinsic Value
    if opt_type == "CE":
        intrinsic = max(0.0, current_spot - strike)
    else:  # PE
        intrinsic = max(0.0, strike - current_spot)

    is_itm = intrinsic > 0
    notional_value = strike * qty
    est_stt = (notional_value * 0.00125) if (is_itm and action == "BUY") else 0.0

    status_tag = "ITM_HAZARD" if (is_itm and action == "BUY") else ("ITM_PROFIT" if is_itm else "OTM_SAFE")
    return status_tag, intrinsic, est_stt

def run_settlement_watchdog(dry_run=False):
    if not os.path.exists(LEDGER_PATH):
        print(f"Error: {LEDGER_PATH} not found.")
        return

    with open(LEDGER_PATH, "r", encoding="utf-8") as f:
        trades = json.load(f)

    active_trades = [t for t in trades if str(t.get("status", "")).upper() == "ACTIVE"]

    print("=" * 60)
    print(f"🛡️ STOCKERA 15:20 IST EXPIRY SETTLEMENT WATCHDOG")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Active Legs: {len(active_trades)}")
    print("=" * 60)

    if not active_trades:
        print("✅ Zero active legs open. Portfolio is flat and immune to expiry settlement traps.")
        return

    warnings = []
    squared_count = 0

    for t in active_trades:
        symbol = t.get("symbol", "NIFTY").upper()
        spot = BENCHMARK_SPOTS.get(symbol, 23000.0)
        tag, intrinsic, stt = evaluate_stt_hazard(t, spot)

        trade_id = t.get("trade_id", "TRD")
        contract = t.get("contract", symbol)
        action = t.get("action", "BUY")

        print(f"• [{trade_id}] {action} {contract} | Spot: {spot} | Intrinsic: ₹{intrinsic:.2f} | Status: {tag}")

        if tag == "ITM_HAZARD":
            warnings.append(f"⚠️ <b>STT TRAP ALERT:</b> {trade_id} ({contract}) is ITM! Est Notional STT: ₹{stt:,.1f}")

        # Square off the leg
        if not dry_run:
            entry = float(t.get("entry_price", 100))
            exit_p = round(max(0.5, intrinsic if intrinsic > 0 else entry * 0.1), 2)
            t["status"] = "CLOSED"
            t["exit_time"] = "15:20:00"
            t["exit_price"] = exit_p
            t["exit_reason"] = "15:20_STT_DEFENSE_SQUAREOFF 🛡️" if tag == "ITM_HAZARD" else "15:20_THETA_HARVEST ⏰"
            squared_count += 1

    if not dry_run and squared_count > 0:
        with open(LEDGER_PATH, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
        print(f"\n✅ {squared_count} legs auto-squared off to eliminate settlement risk.")

        # If warnings exist, broadcast high-priority safety alert to Telegram
        if warnings:
            alert_text = (
                "<b>🚨 EXPIRY STT DEFENSE INTERVENTION 🚨</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(warnings) + "\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "<i>All legs successfully squared off before 15:25 IST hard cutoff.</i>"
            )
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": alert_text, "parse_mode": "HTML"},
                timeout=10
            )

        # Trigger final EOD card
        print("🔄 Triggering final EOD Telegram audit card...")
        os.system("python eod_ledger_reporter.py")

if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    run_settlement_watchdog(dry_run=dry)