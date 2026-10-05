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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028").strip()

LEDGER_PATH = r"C:\kite-agent\trades_ledger.json"

EXCHANGE_SEGMENTS = {
    "NIFTY": "NSE_FNO",
    "BANKNIFTY": "NSE_FNO",
    "FINNIFTY": "NSE_FNO",
    "SENSEX": "BSE_FNO"
}

SCRIP_MAP = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}


# P0.9: Resolve real numeric security_id from option chain — never use strike as proxy.
def resolve_security_id(symbol: str, strike: float, opt_type: str):
    """
    Queries Dhan /v2/optionchain and returns the integer security_id for the leg.
    Returns None if the ID cannot be verified — callers must hard-fail in that case.
    """
    scrip_id = SCRIP_MAP.get(symbol.upper(), 13)
    h = {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json"
    }
    try:
        r = requests.post(
            "https://api.dhan.co/v2/optionchain",
            headers=h,
            json={"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"},
            timeout=5
        )
        if r.status_code == 200:
            oc = r.json().get("data", {}).get("oc", {})
            for k, v in oc.items():
                try:
                    if abs(float(k) - strike) < 0.5:
                        leg_key = opt_type.lower()  # "ce" or "pe"
                        sec_id = v.get(leg_key, {}).get("security_id")
                        if sec_id is not None:
                            return int(sec_id)
                except Exception:
                    continue
    except Exception as exc:
        logger.error(
            "DATA_FAULT resolve_security_id sym=%s strike=%s opt=%s err=%s",
            symbol, strike, opt_type, exc
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
    order_ids = []
    fill_reports = []

    for idx, leg_text in enumerate(legs):
        leg_info = parse_leg_string(leg_text, default_sym=sym)
        order_num = f"DHAN-ORD-{int(time.time())}-{idx+1}"

        if live_mode and DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID:
            # P0.9: Resolve real numeric security_id before submitting the order.
            security_id = resolve_security_id(
                leg_info["symbol"], leg_info["strike"], leg_info["opt_type"]
            )
            if security_id is None:
                # P0.9: Hard-fail — never log as ACTIVE if security_id is unverified.
                msg = (
                    f"DATA_FAULT execute_basket sym={leg_info['symbol']} "
                    f"strike={leg_info['strike']} opt={leg_info['opt_type']} "
                    f"security_id_unresolved — order REJECTED, NOT logged as ACTIVE"
                )
                logger.error(msg)
                order_ids.append(f"{order_num}-REJECTED_NO_SECID")
                fill_reports.append(
                    f"REJECTED {leg_info['action']} {leg_info['strike']} "
                    f"{leg_info['opt_type']} — security_id unverified (DATA_FAULT)"
                )
                continue

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

    # Only record to ledger if at least one leg was successfully dispatched live,
    # or if running in paper-trading mode. P0.9: never mark ACTIVE on full rejection.
    live_successes = [o for o in order_ids if not any(tag in o for tag in ["REJECTED", "OFFLINE", "FAILED"])]
    if not live_mode or live_successes:
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
        "status": "SUCCESS" if live_successes or not live_mode else "REJECTED",
        "mode": "LIVE" if live_mode else "PAPER_TRADING",
        "orders": order_ids,
        "report": fill_reports
    }
