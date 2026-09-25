import sys
import os
import re
import requests
from dotenv import load_dotenv

if len(sys.argv) < 2:
    print("❌ Usage: python update_dhan_token.py YOUR_NEW_DHAN_TOKEN")
    sys.exit(1)

# Grab the token safely without bracket indexing
new_token = sys.argv.pop(1).strip()

# Find all .env files in C:\kite-agent and subfolders
env_files = [".env"]
for root, dirs, files in os.walk("."):
    for file in files:
        if file.endswith(".env"):
            p = os.path.join(root, file)
            if p not in env_files:
                env_files.append(p)

updated_count = 0
for env_path in env_files:
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Replace DHAN_ACCESS_TOKEN
        if "DHAN_ACCESS_TOKEN" in content:
            new_content = re.sub(r'DHAN_ACCESS_TOKEN=.*', f'DHAN_ACCESS_TOKEN={new_token}', content)
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            updated_count += 1
            print(f"✓ Updated token in: {env_path}")

# Test connection with Dhan API
load_dotenv(override=True)
client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
headers = {"access-token": new_token, "client-id": client_id}

try:
    resp = requests.get("https://api.dhan.co/v2/profile", headers=headers, timeout=5)
    if resp.status_code == 200:
        print("\n✅ SUCCESS: New Dhan Token is ACTIVE and verified with DhanHQ API!")
        print(f"• Updated across {updated_count} .env files.")
        print("• Valid for next 30 days. No further action needed.")
    else:
        print(f"\n⚠️ Token saved, but Dhan verification returned HTTP {resp.status_code}: {resp.text}")
except Exception as e:
    print(f"\n⚠️ Token saved in files, but verification check returned: {e}")