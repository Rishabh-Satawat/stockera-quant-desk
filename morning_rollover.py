import os
import json
import csv
from datetime import datetime

LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"
HISTORY_CSV = r"C:\kite-agent\trades_history.csv"

def rollover_daily_ledger():
    if not os.path.exists(LEDGER_FILE):
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        print("Initialized empty trades ledger.")
        return

    with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
        try:
            trades = json.load(f)
        except Exception:
            trades = []

    # Ensure all historical trades are preserved in CSV
    if trades:
        file_exists = os.path.exists(HISTORY_CSV)
        with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerows(trades)
        print(f"📦 Archived {len(trades)} trades from previous session into {HISTORY_CSV}")

    # Reset ledger for the new morning session
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    print("🌅 Desk Armed: trades_ledger.json reset to empty state for today's session (09:15 IST)!")

if __name__ == "__main__":
    rollover_daily_ledger()
