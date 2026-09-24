import os
import json
import re
from datetime import datetime

LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"

def auto_record_broadcasted_basket(sym, strat_name, spot, legs, credit, max_p, sl_text):
    """Automatically records the broadcasted basket into trades_ledger.json as ACTIVE."""
    trades = []
    if os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
            try:
                trades = json.load(f)
            except Exception:
                trades = []

    # Quota gate: Max 3 trades per day
    if len(trades) >= 3:
        print("⚠️ Maximum 3 trades/day quota reached.")
        return False

    trade_id = f"TRD-{datetime.now().strftime('%Y%m%d')}-{len(trades)+1:02d}"
    
    # Extract primary contract name and estimate entry premium
    primary_leg = legs[0] if isinstance(legs, list) and len(legs) > 0 else f"{sym} Option"
    clean_contract = re.sub(r"\[.*?\]\s*", "", primary_leg).split("@")[0].strip()
    
    # Estimate entry price from credit/debit
    entry_price = abs(float(credit)) if credit != 0 else 100.0
    lot_size = 30 if sym == "SENSEX" else (25 if sym == "NIFTY" else 15)
    
    # Extract Stop Loss & Target estimates
    stop_loss = round(entry_price * 0.80, 2)
    target_1 = round(entry_price * 1.20, 2)
    margin_deployed = round(entry_price * lot_size, 2)

    new_trade = {
        "trade_id": trade_id,
        "symbol": sym,
        "contract": clean_contract,
        "action": "BUY" if "BUY" in primary_leg else "SELL",
        "strategy": strat_name,
        "qty": lot_size,
        "entry_time": datetime.now().strftime("%H:%M:%S"),
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "status": "ACTIVE",
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "margin_deployed": margin_deployed
    }

    trades.append(new_trade)
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)

    print(f"✅ Trade Auto-Logged to Ledger: {trade_id} | {clean_contract} | ACTIVE")
    return True

if __name__ == "__main__":
    print("Bridge ready.")
