import os
from dotenv import load_dotenv
from kiteconnect import KiteConnect

# 1. Load credentials
load_dotenv()
API_KEY = os.getenv("KITE_API_KEY", "").strip()

# 2. Check and load access_token.txt
if not os.path.exists("access_token.txt"):
  print(
      "❌ Error: access_token.txt not found! Please run 'python"
      " generate_token.py' first."
  )
  exit(1)

with open("access_token.txt") as f:
  ACCESS_TOKEN = f.read().strip()

# 3. Initialize KiteConnect
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

print("=" * 55)
print("⚡ ZERODHA KITE CONNECT — LIVE TEST")
print("=" * 55)

try:
  # Fetch Profile
  profile = kite.profile()
  print(f"👤 Account Name : {profile.get('user_name')}")
  print(f"🆔 User ID      : {profile.get('user_id')}")
  print(f"📧 Email        : {profile.get('email')}")

  # Fetch Margins & Funds
  margins = kite.margins()
  equity_cash = margins.get("equity", {}).get("available", {}).get("cash", 0)
  print(f"💰 Available Cash: ₹{equity_cash:,.2f}")

  # Fetch Live Market Quotes
  quotes = kite.quote(["NSE:NIFTY 50", "NSE:NIFTY BANK"])
  nifty_ltp = quotes["NSE:NIFTY 50"]["last_price"]
  banknifty_ltp = quotes["NSE:NIFTY BANK"]["last_price"]
  print(f"📈 NIFTY 50 LTP  : {nifty_ltp}")
  print(f"📈 BANK NIFTY LTP: {banknifty_ltp}")

  print("=" * 55)
  print("🎉 SUCCESS: Zerodha Kite API is connected and ready for AI Agent!")
  print("=" * 55)

except Exception as e:
  print(f"❌ Error communicating with Kite API: {e}")