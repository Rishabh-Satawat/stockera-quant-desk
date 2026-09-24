import os
import pyotp
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
API_SECRET = os.getenv("KITE_API_SECRET")

kite = KiteConnect(api_key=API_KEY)

print(f"Login URL: {kite.login_url()}")
print("1. Open the Login URL above in your browser and log in.")
print("2. After login, copy the 'request_token' from the redirected address bar URL.")

request_token = input("Paste request_token here: ").strip()

# Generate session & access token
data = kite.generate_session(request_token, api_secret=API_SECRET)
access_token = data["access_token"]
kite.set_access_token(access_token)

print(f"\n✅ Session Connected Successfully!")
print(f"Access Token: {access_token[:6]}... (active for today)")

# Test Fetching Account Margins
profile = kite.profile()
print(f"User: {profile.get('user_name')} ({profile.get('user_id')})")

margins = kite.margins()
equity_margin = margins.get('equity', {}).get('net', 0)
print(f"Available Equity Margin: ₹{equity_margin:,.2f}")