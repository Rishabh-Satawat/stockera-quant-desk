import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

# Official Exchange Lot Sizes (Updated from Dhan Terminal)
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 60}

SCRIP_MAP = {
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "SENSEX": 51
}

def fetch_dhan_live_chain(symbol: str):
    """Fetches real-time option chain directly from Dhan HQ v2 API."""
    if not DHAN_ACCESS_TOKEN or not DHAN_CLIENT_ID:
        return None

    scrip_id = SCRIP_MAP.get(symbol, 13)
    h = {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json"
    }

    try:
        # 1. Fetch nearest active expiry
        r_exp = requests.post(
            "https://api.dhan.co/v2/optionchain/expirylist",
            headers=h,
            json={"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"},
            timeout=4
        )
        if r_exp.status_code != 200:
            return None

        exp_list = r_exp.json().get("data", [])
        if not exp_list:
            return None
        active_expiry = exp_list[0]

        # 2. Fetch full real-time option chain for that expiry
        r_oc = requests.post(
            "https://api.dhan.co/v2/optionchain",
            headers=h,
            json={"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I", "Expiry": active_expiry},
            timeout=5
        )
        if r_oc.status_code == 200:
            d = r_oc.json().get("data", {})
            return {
                "expiry": active_expiry,
                "spot": float(d.get("last_price", 0.0)),
                "oc": d.get("oc", {})
            }
    except Exception as e:
        print(f"Dhan Chain fetch notice: {e}")
    return None

def get_exact_option_ltp(chain_data, strike: float, opt_type: str) -> float:
    """Extracts the exact real-time LTP from the Dhan option chain."""
    if not chain_data:
        return 0.0
    oc = chain_data.get("oc", {})
    for k, v in oc.items():
        try:
            if abs(float(k) - strike) < 0.1:
                p = float(v.get(opt_type.lower(), {}).get("last_price", 0.0))
                if p > 0:
                    return round(p, 2)
        except Exception:
            pass
    return 0.0

if __name__ == "__main__":
    print("Testing Dhan Live Option Chain connection...")
    chain = fetch_dhan_live_chain("SENSEX")
    if chain:
        print(f"🟢 Connected to Dhan HQ! Active Expiry: {chain['expiry']} | Spot: ₹{chain['spot']:,.2f}")
        test_p = get_exact_option_ltp(chain, 75300, "CE")
        print(f"📊 Real Live Market LTP for SENSEX 75300 CE: ₹{test_p:.2f}")
    else:
        print("⚠️ Could not reach Dhan API. Check token status.")
