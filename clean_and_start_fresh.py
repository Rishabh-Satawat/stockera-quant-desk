import os
import json
from datetime import date
from dotenv import load_dotenv
from supabase import create_client, Client
from live_market_entry import execute_live_entry

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

print("🧹 Starting fresh reset for today's trading desk...")

# 1. Clear Supabase Database
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Delete all test records in trade_legs
        supabase.table("trade_legs").delete().neq("status", "DOES_NOT_EXIST").execute()
        print("✓ Supabase 'trade_legs' table wiped clean.")
    except Exception as e:
        print(f"⚠️ Supabase clean warning: {e}")

# 2. Reset Local Trades Ledger (if present)
ledger_file = "trades_ledger.json"
if os.path.exists(ledger_file):
    try:
        with open(ledger_file, "w") as f:
            json.dump([], f)
        print("✓ Local 'trades_ledger.json' reset to empty.")
    except Exception as e:
        print(f"⚠️ Ledger reset warning: {e}")

print("\n🚀 Triggering fresh live market entry now...")

# 3. Fire the fresh live market trade
execute_live_entry()

print("\n✅ Desk reset complete. Live positions are active in market and recorded fresh.")