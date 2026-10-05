import os
import json
import requests
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\supabase.env")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")).strip()

LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"

def get_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

def sync_trades_to_supabase(trades=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Supabase credentials missing in secrets/supabase.env")
        return False

    if trades is None:
        if not os.path.exists(LEDGER_FILE):
            print("Ledger file not found.")
            return False
        with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
            try:
                trades = json.load(f)
            except Exception:
                trades = []

    if not trades:
        print("No trades to sync.")
        return False

    records = []
    for t in trades:
        rec = {
            "trade_id": str(t.get("trade_id")),
            "symbol": str(t.get("symbol", "")),
            "contract": str(t.get("contract", "")),
            "action": str(t.get("action", "")),
            "strategy": str(t.get("strategy", "")),
            "qty": int(t.get("qty", 0)),
            "entry_time": str(t.get("entry_time", "")),
            "entry_price": float(t.get("entry_price", 0.0)),
            "stop_loss": str(t.get("stop_loss", "")),
            "target_1": str(t.get("target_1", "")),
            "target_2": str(t.get("target_2", "")),
            "status": str(t.get("status", "ACTIVE")),
            "exit_time": str(t.get("exit_time", "")),
            "exit_price": float(t.get("exit_price", 0.0)) if t.get("exit_price") is not None else None,
            "exit_reason": str(t.get("exit_reason", "")),
            "margin_deployed": float(t.get("margin_deployed", 0.0)),
            "realized_pnl": float(t.get("realized_pnl", 0.0)) if t.get("realized_pnl") is not None else None,
            "gross_roi_pct": float(t.get("gross_roi_pct", 0.0)) if t.get("gross_roi_pct") is not None else None,
            "book": str(t.get("book", "HEDGED"))
        }
        records.append(rec)

    endpoint = f"{SUPABASE_URL}/rest/v1/stockera_trades"
    try:
        r = requests.post(endpoint, headers=get_headers(), json=records, timeout=6)
        if r.status_code in [200, 201]:
            print(f"☁️ SUCCESS: Synced {len(records)} trades to Supabase cloud table 'stockera_trades'!")
            return True
        elif r.status_code == 404:
            print("⚠️ Table 'stockera_trades' not found. Please run the SQL snippet in Supabase SQL Editor first.")
            return False
        else:
            print(f"Supabase sync status {r.status_code}: {r.text}")
            return False
    except Exception as e:
        print(f"🔴 Sync error: {e}")
        return False

if __name__ == "__main__":
    sync_trades_to_supabase()
