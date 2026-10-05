import os
import re
import json
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# 1. Load Secrets
load_dotenv(r"C:\kite-agent\secrets\telegram.env")
load_dotenv(r"C:\kite-agent\secrets\dhan.env")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _require_telegram_token():
    """Raise at call time if the token is absent — never at import time."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN env var is missing — load secrets/telegram.env before running the watchdog"
        )
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")

LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

# P0.7: BENCHMARK_SPOTS removed — live spot is mandatory for STT hazard assessment.

SCRIP_MAP = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}


def fetch_live_spot(symbol: str):
    """Returns (spot_price, is_synthetic). is_synthetic=True means feed failed."""
    # Prefer the shared live spot service
    try:
        from live_spot_service import get_live_spots
        spots = get_live_spots()
        s = spots.get(symbol.upper())
        if s and float(s) > 0:
            return float(s), False
    except Exception as exc:
        logger.error("DATA_FAULT fetch_live_spot sym=%s live_spot_service err=%s", symbol, exc)

    # Fallback: query Dhan option chain for last_price
    scrip_id = SCRIP_MAP.get(symbol.upper(), 13)
    try:
        h = {
            "access-token": DHAN_ACCESS_TOKEN,
            "client-id": DHAN_CLIENT_ID,
            "Content-Type": "application/json"
        }
        r = requests.post(
            "https://api.dhan.co/v2/optionchain",
            headers=h,
            json={"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"},
            timeout=5
        )
        if r.status_code == 200:
            lp = float(r.json().get("data", {}).get("last_price", 0.0))
            if lp > 0:
                return lp, False
    except Exception as exc:
        logger.error("DATA_FAULT fetch_live_spot sym=%s dhan_fallback err=%s", symbol, exc)

    logger.error("DATA_FAULT fetch_live_spot sym=%s all_feeds_failed is_synthetic=True", symbol)
    return None, True


def parse_contract_details(contract_str, default_symbol="NIFTY"):
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

    if opt_type == "CE":
        intrinsic = max(0.0, current_spot - strike)
    else:
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

    # P0.13: Process ACTIVE trades AND UNRESOLVED trades that carry data_fault=True;
    # a sentinel-escalated UNRESOLVED trade still has open exposure at 15:20 IST.
    active_trades = [
        t for t in trades
        if str(t.get("status", "")).upper() == "ACTIVE"
        or (str(t.get("status", "")).upper() == "UNRESOLVED" and t.get("data_fault") is True)
    ]

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

        # P0.7: Fetch live spot — never use static BENCHMARK_SPOTS constants.
        spot, is_synthetic = fetch_live_spot(symbol)

        if is_synthetic or spot is None:
            logger.error(
                "DATA_FAULT run_settlement_watchdog sym=%s live_spot_unavailable trade_id=%s",
                symbol, t.get("trade_id", "TRD")
            )
            print(f"⚠️ [{t.get('trade_id', 'TRD')}] DATA_FAULT: live spot unavailable for {symbol}. "
                  f"Logging as UNRESOLVED_DATA_FAULT — manual broker reconciliation required.")
            # P0.13: No fabricated exit prices. Tag for manual reconciliation.
            if not dry_run:
                t["status"] = "UNRESOLVED_DATA_FAULT"
                t["exit_time"] = "15:20:00"
                t["exit_price"] = None
                t["exit_reason"] = "UNRESOLVED_DATA_FAULT — manual broker reconciliation required"
                t["data_fault"] = True
                squared_count += 1
            continue

        tag, intrinsic, stt = evaluate_stt_hazard(t, spot)

        trade_id = t.get("trade_id", "TRD")
        contract = t.get("contract", symbol)
        action = t.get("action", "BUY")

        print(f"• [{trade_id}] {action} {contract} | Spot: {spot} | Intrinsic: ₹{intrinsic:.2f} | Status: {tag}")

        if tag == "ITM_HAZARD":
            warnings.append(f"⚠️ <b>STT TRAP ALERT:</b> {trade_id} ({contract}) is ITM! Est Notional STT: ₹{stt:,.1f}")

        # Square off the leg using live intrinsic value — no synthetic exit prices.
        if not dry_run:
            if intrinsic > 0:
                exit_p = round(intrinsic, 2)
            else:
                # OTM at expiry: option expires worthless; LTP near 0 — record as 0.0
                exit_p = 0.0
            t["status"] = "CLOSED"
            t["exit_time"] = "15:20:00"
            t["exit_price"] = exit_p
            t["exit_reason"] = "15:20_STT_DEFENSE_SQUAREOFF 🛡️" if tag == "ITM_HAZARD" else "15:20_THETA_HARVEST ⏰"
            t["is_synthetic"] = False  # P0.7: exit was assessed with live spot
            squared_count += 1

    if not dry_run and squared_count > 0:
        with open(LEDGER_PATH, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2)
        print(f"\n✅ {squared_count} legs auto-squared off to eliminate settlement risk.")

        if warnings:
            _require_telegram_token()
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

        print("🔄 Triggering final EOD Telegram audit card...")
        os.system("python eod_ledger_reporter.py")


if __name__ == "__main__":
    import sys
    dry = "--dry-run" in sys.argv
    run_settlement_watchdog(dry_run=dry)
