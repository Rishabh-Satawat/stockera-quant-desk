import os
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

token_file = "access_token.txt"
if not os.path.exists(token_file):
    print("❌ access_token.txt not found! Run 'python kite_auto_login.py' first.")
    exit()

with open(token_file) as f:
    token = f.read().strip()

api_key = os.getenv("KITE_API_KEY", "").strip()
if not api_key:
    print("❌ KITE_API_KEY missing in .env")
    exit()

kite = KiteConnect(api_key=api_key)
kite.set_access_token(token)

try:
    profile = kite.profile()
    margins = kite.margins()
    cash = margins.get("equity", {}).get("available", {}).get("cash", 0.0)

    print("=" * 45)
    print("✅ KITE CONNECTIVITY VERIFIED")
    print(f"• Account Holder: {profile.get('user_name')}")
    print(f"• Client ID:      {profile.get('user_id')}")
    print(f"• Available Cash: ₹{cash:,.2f}")
    print("=" * 45)
except Exception as e:
    print(f"❌ Kite Connection Failed: {e}")