import os
import time
from datetime import datetime

def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    time_val = now.hour * 100 + now.minute
    return 915 <= time_val <= 1530

def main():
    print("=" * 60)
    print("🏛️ STOCKERA MASTER MARKET DAY SUPERVISOR")
    print("Autonomous Scheduler: Sentinel (09:15) • Watchdog (15:20) • EOD (15:30)")
    print("=" * 60)

    eod_done = False
    watchdog_done = False

    while True:
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")

        # 15:20 IST: Run Expiry & STT Watchdog
        if current_time_str >= "15:20" and not watchdog_done:
            print("\n⏰ 15:20 IST REACHED: Executing Expiry & STT Defense Watchdog...")
            os.system("python expiry_settlement_watchdog.py")
            watchdog_done = True

        # 15:30 IST: Run EOD Performance Blotter
        if current_time_str >= "15:30" and not eod_done:
            print("\n⏰ 15:30 IST MARKET CLOSE: Dispatching EOD Audit Blotter...")
            os.system("python eod_ledger_reporter.py")
            eod_done = True
            print("Session concluded. Standing by for next market day.")

        # Reset flags after midnight
        if current_time_str < "09:00":
            eod_done = False
            watchdog_done = False

        time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSupervisor stopped.")