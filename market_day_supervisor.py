import os
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Dhan Renew Token API endpoint
_DHAN_RENEW_URL = "https://api.dhan.co/v2/access-token"


def is_market_open():
    now = datetime.now()
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    time_val = now.hour * 100 + now.minute
    return 915 <= time_val <= 1530


def _renew_dhan_token() -> bool:
    """Attempt to renew the Dhan access token at 08:45 IST.

    Returns True on success (env file updated atomically).
    Returns False and sends a Telegram alert on failure.
    """
    try:
        import requests
        from dotenv import load_dotenv, dotenv_values
        import re

        env_path = r"C:\kite-agent\secrets\dhan.env"
        load_dotenv(env_path, override=True)
        client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
        current_token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

        if not client_id or not current_token:
            logger.error("Token renewal: DHAN_CLIENT_ID or DHAN_ACCESS_TOKEN missing")
            _send_renewal_failure_alert("Missing DHAN credentials in dhan.env")
            return False

        headers = {
            "access-token": current_token,
            "client-id": client_id,
            "Content-Type": "application/json",
        }
        resp = requests.post(_DHAN_RENEW_URL, headers=headers, timeout=10)

        if resp.status_code == 200:
            data = resp.json()
            new_token = data.get("accessToken") or data.get("access_token", "")
            if not new_token:
                logger.error("Token renewal: API returned 200 but no token in response")
                _send_renewal_failure_alert("API returned 200 but no token in response")
                return False

            # Atomic update of dhan.env
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()
                new_content = re.sub(
                    r"DHAN_ACCESS_TOKEN=.*",
                    f"DHAN_ACCESS_TOKEN={new_token}",
                    content,
                )
                tmp_path = env_path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                os.replace(tmp_path, env_path)
                print(f"   ✅ Dhan token renewed successfully at 08:45 IST")
                logger.info("Token renewal: success — dhan.env updated atomically")
                return True
        else:
            logger.error("Token renewal: HTTP %s from Dhan API", resp.status_code)
            _send_renewal_failure_alert(f"HTTP {resp.status_code} from Dhan API")
            return False

    except Exception as exc:
        logger.error("Token renewal: exception — %s", exc)
        _send_renewal_failure_alert(str(exc))
        return False


def _send_renewal_failure_alert(reason: str) -> None:
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv(r"C:\kite-agent\secrets\telegram.env")
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not bot_token or not chat_id:
            return
        msg = (
            f"🚨 DHAN TOKEN RENEWAL FAILED — SESSION BLOCKED\n"
            f"Reason: {reason}\n"
            f"Run update_dhan_token.py with a fresh token before market open."
        )
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as exc:
        logger.error("Failed to send renewal failure alert: %s", exc)


def main():
    print("=" * 60)
    print("🏛️ STOCKERA MASTER MARKET DAY SUPERVISOR")
    print("Autonomous Scheduler: Renewal (08:45) • Labeller (09:00) • Sentinel (09:15) • Watchdog (15:20) • EOD (15:30)")
    print("=" * 60)

    eod_done = False
    watchdog_done = False
    labeller_done = False
    token_renewal_done = False

    while True:
        now = datetime.now()
        current_time_str = now.strftime("%H:%M")

        # 08:45 IST: Auto-renew Dhan access token (expires every 24 hours)
        if current_time_str >= "08:45" and not token_renewal_done:
            print("\n⏰ 08:45 IST: Auto-renewing Dhan access token...")
            success = _renew_dhan_token()
            if not success:
                print("   ⚠️  Token renewal failed — alert dispatched. Verify credentials before market open.")
            token_renewal_done = True

        # 09:00 IST: Run outcome labeller for prior session candidates
        if current_time_str >= "09:00" and not labeller_done:
            print("\n⏰ 09:00 IST: Running outcome labeller for prior session...")
            try:
                from outcome_labeller import run_labeller
                rows = run_labeller()
                print(f"   Labeller complete: {rows} rows labelled.")
            except Exception as exc:
                logger.error("Outcome labeller failed: %s", exc)
                print(f"   Labeller error (non-fatal): {exc}")
            labeller_done = True

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
        if current_time_str < "08:45":
            eod_done = False
            watchdog_done = False
            labeller_done = False
            token_renewal_done = False

        time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSupervisor stopped.")
