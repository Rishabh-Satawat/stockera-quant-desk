# =============================================================================
# DHAN HQ v2 MULTI-LEG ORDER ROUTER & EXECUTION GATEWAY
# Supports Safe Paper-Trading Simulation & Direct Live Broker Execution
# =============================================================================
import os
import re
import json
import time
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
load_dotenv(r"C:\kite-agent\secrets\telegram.env")
load_dotenv()

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
_tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
if not _tg_token:
    raise RuntimeError("TELEGRAM_BOT_TOKEN env var is missing — load secrets/telegram.env before importing this module")
TELEGRAM_BOT_TOKEN = _tg_token
TELEGRAM_CHAT_ID = _tg_chat

LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

EXCHANGE_SEGMENTS = {
    "NIFTY": "NSE_FNO",
    "BANKNIFTY": "NSE_FNO",
    "FINNIFTY": "NSE_FNO",
    "SENSEX": "BSE_FNO"
}

SCRIP_MAP = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}


# P0.12: Fetch option chain ONCE per (symbol, expiry) — Dhan rate limit is 1 req/3 s.
def fetch_option_chain(symbol: str, expiry_date: str = None) -> dict:
    """
    Fetches Dhan /v2/optionchain once and returns the raw 'oc' dict.
    expiry_date should be "YYYY-MM-DD"; if omitted, Dhan returns the nearest expiry.
    Returns {} on any failure.
    """
    scrip_id = SCRIP_MAP.get(symbol.upper(), 13)
    h = {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json"
    }
    payload = {"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"}
    if expiry_date:
        payload["Expiry"] = expiry_date
    try:
        r = requests.post(
            "https://api.dhan.co/v2/optionchain",
            headers=h,
            json=payload,
            timeout=5
        )
        if r.status_code == 200:
            return r.json().get("data", {}).get("oc", {})
    except Exception as exc:
        logger.error(
            "DATA_FAULT fetch_option_chain sym=%s expiry=%s err=%s",
            symbol, expiry_date, exc
        )
    return {}


# P0.9 / P0.12: Resolve real numeric security_id from a pre-fetched option chain.
def resolve_security_id(symbol: str, strike: float, opt_type: str, expiry_date: str = None, oc: dict = None):
    """
    Returns the integer security_id for the leg from the provided option chain cache.
    If oc is None, fetches the chain (single call); callers should prefer passing the
    pre-fetched oc so the whole basket uses exactly one API call.
    Returns None if the ID cannot be verified — callers must hard-fail in that case.
    """
    if oc is None:
        oc = fetch_option_chain(symbol, expiry_date)
    for k, v in oc.items():
        try:
            if abs(float(k) - strike) < 0.5:
                leg_key = opt_type.lower()  # "ce" or "pe"
                sec_id = v.get(leg_key, {}).get("security_id")
                if sec_id is not None:
                    return int(sec_id)
        except Exception:
            continue
    logger.error(
        "DATA_FAULT resolve_security_id sym=%s strike=%s opt=%s expiry=%s not_found_in_chain",
        symbol, strike, opt_type, expiry_date
    )
    return None


def parse_leg_string(leg_str, default_sym="NIFTY"):
    action = "BUY" if "BUY" in leg_str.upper() else "SELL"
    opt_type = "CE" if "CE" in leg_str.upper() else "PE"

    strike_match = re.search(r"(\d{4,6})", leg_str)
    strike = float(strike_match.group(1)) if strike_match else 0.0

    price_match = re.search(r"₹\s*(\d+(?:\.\d+)?)", leg_str)
    price = float(price_match.group(1)) if price_match else 50.0

    sym = default_sym
    for s in ["SENSEX", "BANKNIFTY", "FINNIFTY", "NIFTY"]:
        if s in leg_str.upper():
            sym = s
            break

    return {
        "symbol": sym,
        "strike": strike,
        "opt_type": opt_type,
        "action": action,
        "price": price,
        "raw": leg_str
    }


def send_telegram_execution_alert(basket, order_ids, live=False):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    mode_tag = "🔴 LIVE DHAN HQ v2 FILL" if live else "🟢 PAPER TRADING SIMULATION"
    legs_list = "\n".join([f"• <code>{l}</code>" for l in basket.get("legs", [])])
    orders_str = ", ".join(order_ids)

    msg = (
        f"<b>⚡ MULTI-LEG BASKET EXECUTED ⚡</b>\n"
        f"<b>Execution Mode:</b> {mode_tag}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Asset:</b> {basket.get('sym')} | <b>Spot:</b> ₹{basket.get('spot', 0):,.2f}\n"
        f"📌 <b>Strategy:</b> {basket.get('name')}\n"
        f"🆔 <b>Order ID(s):</b> <code>{orders_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Executed Legs ({basket.get('lot', 65)} Qty / Lot):</b>\n"
        f"{legs_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Net Entry:</b> ₹{basket.get('credit', 0):,.2f} | <b>Max Target:</b> {basket.get('max_p')}\n"
        f"🛡️ <b>SL Guard:</b> {basket.get('max_l')} (AURA Sentinel Armed)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Position logged to Desk Ledger & Sentinel Active</i>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=6)
        return True
    except Exception:
        return False


def execute_basket(basket, live_mode=False):
    sym = basket.get("sym", "NIFTY")
    legs = basket.get("legs", [])
    lot_size = basket.get("lot", 65)
    expiry_date = basket.get("expiry_date")  # P0.12: pass expiry so chain uses correct cycle
    order_ids = []
    fill_reports = []

    # P0.12: Fetch option chain ONCE for the entire basket to avoid Dhan rate limit
    # (1 req / 3 s). Resolve all security IDs before placing any order.
    if live_mode and DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID:
        shared_oc = fetch_option_chain(sym, expiry_date)
        if not shared_oc:
            logger.error(
                "DATA_FAULT execute_basket sym=%s expiry=%s option_chain_unavailable — basket ABORTED",
                sym, expiry_date
            )
            return {
                "status": "REJECTED",
                "mode": "LIVE",
                "orders": [],
                "report": [f"ABORTED: option chain unavailable for {sym} expiry={expiry_date}"]
            }

        # Pre-resolve all security IDs — abort entire basket if any leg fails
        leg_infos = [parse_leg_string(leg_text, default_sym=sym) for leg_text in legs]
        resolved_ids = []
        for leg_info in leg_infos:
            sec_id = resolve_security_id(
                leg_info["symbol"], leg_info["strike"], leg_info["opt_type"],
                expiry_date=expiry_date, oc=shared_oc
            )
            if sec_id is None:
                logger.error(
                    "DATA_FAULT execute_basket sym=%s strike=%s opt=%s "
                    "security_id_unresolved — ENTIRE BASKET ABORTED",
                    leg_info["symbol"], leg_info["strike"], leg_info["opt_type"]
                )
                return {
                    "status": "REJECTED",
                    "mode": "LIVE",
                    "orders": [],
                    "report": [
                        f"ABORTED: security_id unresolved for "
                        f"{leg_info['symbol']} {leg_info['strike']} {leg_info['opt_type']}"
                    ]
                }
            resolved_ids.append(sec_id)
    else:
        leg_infos = [parse_leg_string(leg_text, default_sym=sym) for leg_text in legs]
        resolved_ids = [None] * len(leg_infos)

    for idx, (leg_text, leg_info) in enumerate(zip(legs, leg_infos)):
        order_num = f"DHAN-ORD-{int(time.time())}-{idx+1}"
        security_id = resolved_ids[idx]

        if live_mode and DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID:
            # security_id is already verified above; execution proceeds directly.

            # LIVE EXECUTION VIA DHAN HQ v2 API
            url = "https://api.dhan.co/v2/orders"
            headers = {
                "access-token": DHAN_ACCESS_TOKEN,
                "client-id": DHAN_CLIENT_ID,
                "Content-Type": "application/json"
            }
            payload = {
                "dhanClientId": DHAN_CLIENT_ID,
                "correlationId": order_num,
                "transactionType": leg_info["action"],
                "exchangeSegment": EXCHANGE_SEGMENTS.get(sym, "NSE_FNO"),
                "productType": "INTRADAY",
                "orderType": "LIMIT",
                "validity": "DAY",
                "securityId": str(security_id),  # P0.9: verified numeric ID
                "quantity": lot_size,
                "price": leg_info["price"]
            }
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=4)
                if r.status_code in [200, 201, 202]:
                    dhan_order_id = r.json().get("orderId", order_num)
                    order_ids.append(str(dhan_order_id))
                    fill_reports.append(
                        f"{leg_info['action']} {leg_info['strike']} {leg_info['opt_type']} "
                        f"@ ₹{leg_info['price']} (Order #{dhan_order_id})"
                    )
                else:
                    # API rejected — do NOT log as ACTIVE
                    logger.error(
                        "DATA_FAULT execute_basket dhan_rejected status=%s body=%s",
                        r.status_code, r.text[:200]
                    )
                    order_ids.append(f"{order_num}-API_REJECTED")
                    fill_reports.append(
                        f"REJECTED {leg_info['action']} {leg_info['strike']} "
                        f"{leg_info['opt_type']} @ ₹{leg_info['price']} (Dhan status {r.status_code})"
                    )
            except Exception as exc:
                logger.error("DATA_FAULT execute_basket network_error err=%s", exc)
                order_ids.append(f"{order_num}-OFFLINE")
                fill_reports.append(
                    f"FAILED {leg_info['action']} {leg_info['strike']} "
                    f"{leg_info['opt_type']} @ ₹{leg_info['price']} (network error)"
                )
        else:
            order_ids.append(order_num)
            fill_reports.append(
                f"{leg_info['action']} {leg_info['strike']} {leg_info['opt_type']} "
                f"@ ₹{leg_info['price']} (Simulated Fill)"
            )

    # P0.12 / Cleanup: Record to ledger only if ALL legs succeeded in live mode.
    # A partial fill leaves some legs unhedged — never log that basket as ACTIVE.
    live_successes = [o for o in order_ids if not any(tag in o for tag in ["REJECTED", "OFFLINE", "FAILED"])]
    all_filled = len(live_successes) == len(legs)
    if not live_mode or all_filled:
        try:
            from cockpit_ledger_bridge import auto_record_broadcasted_basket
            auto_record_broadcasted_basket(
                basket["sym"],
                basket["name"],
                basket.get("spot", 0),
                basket["legs"],
                basket.get("credit", 0),
                basket.get("max_p", "1000").replace("₹", "").replace(",", "").split()[0],
                basket.get("sl", "100")
            )
        except Exception as e:
            logger.warning("Ledger logging note: %s", e)
    else:
        logger.error(
            "DATA_FAULT execute_basket all_legs_rejected sym=%s NOT_logged_to_ledger", sym
        )

    send_telegram_execution_alert(basket, order_ids, live=live_mode)

    return {
        "status": "SUCCESS" if all_filled or not live_mode else "PARTIAL_FILL_REJECTED",
        "mode": "LIVE" if live_mode else "PAPER_TRADING",
        "orders": order_ids,
        "report": fill_reports
    }
