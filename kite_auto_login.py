import os
import re
import sys
import urllib.parse
from datetime import datetime
import pyotp
import requests
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

KITE_API_KEY = os.getenv("KITE_API_KEY", "").strip()
KITE_API_SECRET = os.getenv("KITE_API_SECRET", "").strip()
KITE_USER_ID = os.getenv("KITE_USER_ID", "").strip()
KITE_PASSWORD = os.getenv("KITE_PASSWORD", "").strip()
KITE_TOTP_KEY = os.getenv("KITE_TOTP_KEY", "").replace(" ", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[Telegram Alert Error] {e}")

def generate_kite_session():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Headless Kite Login for {KITE_USER_ID}...")

    if not all([KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_KEY]):
        err_msg = "❌ Missing Kite credentials in .env"
        print(err_msg)
        send_telegram(f"⚠️ <b>Kite Auth Failed:</b> {err_msg}")
        return False

    session = requests.Session()

    try:
        # Step 1: User & Password
        login_resp = session.post(
            "https://kite.zerodha.com/api/login",
            data={"user_id": KITE_USER_ID, "password": KITE_PASSWORD},
            timeout=10
        )
        login_data = login_resp.json()
        if login_data.get("status") != "success":
            raise Exception(f"Login Step 1 failed: {login_data.get('message', 'Invalid credentials')}")

        request_id = login_data["data"]["request_id"]
        print("✓ Step 1: User ID and password verified.")

        # Step 2: 2FA TOTP
        totp = pyotp.TOTP(KITE_TOTP_KEY)
        twofa_code = totp.now()

        twofa_resp = session.post(
            "https://kite.zerodha.com/api/twofa",
            data={
                "user_id": KITE_USER_ID,
                "request_id": request_id,
                "twofa_value": twofa_code,
                "twofa_type": "totp",
                "skip_session": ""
            },
            timeout=10
        )
        twofa_data = twofa_resp.json()
        if twofa_data.get("status") != "success":
            raise Exception(f"2FA Step 2 failed: {twofa_data.get('message', 'Invalid TOTP')}")

        print("✓ Step 2: TOTP 2FA verified successfully.")

        # Step 3: Follow OAuth Hops to Capture request_token
        current_url = f"https://kite.zerodha.com/connect/login?api_key={KITE_API_KEY}&v=3"
        request_token = None

        # Iterate through internal Zerodha redirects (up to 5 hops)
        for hop in range(5):
            try:
                r = session.get(current_url, allow_redirects=False, timeout=10)
                loc = r.headers.get("Location", "")
                
                # If relative URL, expand to full Zerodha domain
                if loc.startswith("/"):
                    loc = "https://kite.zerodha.com" + loc

                # Check if this hop contains request_token
                if "request_token=" in loc:
                    match = re.search(r"request_token=([a-zA-Z0-9]+)", loc)
                    if match:
                        request_token = match.group(1)
                        break

                if not loc:
                    break

                current_url = loc

            except requests.exceptions.ConnectionError as ce:
                # If it tried to redirect to 127.0.0.1:5000, parse the token from error URL
                match = re.search(r"request_token=([a-zA-Z0-9]+)", str(ce))
                if match:
                    request_token = match.group(1)
                break

        if not request_token:
            raise Exception(f"Could not extract request_token after OAuth redirects. Last URL: {current_url}")

        print(f"✓ Step 3: OAuth request_token captured: {request_token[:6]}******")

        # Step 4: Exchange for Kite Access Token
        kite = KiteConnect(api_key=KITE_API_KEY)
        session_data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
        access_token = session_data["access_token"]

        # Step 5: Save token
        token_path = os.path.join(os.path.dirname(__file__), "access_token.txt")
        with open(token_path, "w") as f:
            f.write(access_token)

        print(f"✓ Step 4: Access token written to {token_path}")

        success_alert = (
            f"🔑 <b>ZERODHA KITE AUTH SUCCESS</b>\n"
            f"• User: <b>{KITE_USER_ID}</b>\n"
            f"• Status: 🟢 <b>Token Generated & Active</b>\n"
            f"• Generated At: {datetime.now().strftime('%H:%M:%S IST')}\n"
            f"• Ready for 09:15 AM automated market open."
        )
        send_telegram(success_alert)
        return True

    except Exception as e:
        err = f"❌ <b>Kite Auto-Auth Error:</b> {e}"
        print(err)
        send_telegram(err)
        return False

if __name__ == "__main__":
    generate_kite_session()