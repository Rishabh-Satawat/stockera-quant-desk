import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

def get_live_spots():
    spots = {"NIFTY": 0.0, "BANKNIFTY": 0.0, "FINNIFTY": 0.0, "SENSEX": 0.0}

    # Tier 1: Dhan HQ v2 Marketfeed — IDX_I segment covers all four indices
    # security_ids: NIFTY=13, BANKNIFTY=25, FINNIFTY=27, SENSEX=51
    if DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID:
        try:
            h = {"access-token": DHAN_ACCESS_TOKEN, "client-id": DHAN_CLIENT_ID, "Content-Type": "application/json"}
            payload = {"IDX_I": [13, 25, 27, 51]}
            r = requests.post("https://api.dhan.co/v2/marketfeed/ltp", headers=h, json=payload, timeout=3)
            if r.status_code == 200:
                data = r.json().get("data", {})
                idx = data.get("IDX_I", {})

                _id_to_sym = {13: "NIFTY", 25: "BANKNIFTY", 27: "FINNIFTY", 51: "SENSEX"}
                for sec_id, sym in _id_to_sym.items():
                    val = idx.get(str(sec_id)) or idx.get(sec_id) or {}
                    if "last_price" in val and float(val["last_price"]) > 0:
                        spots[sym] = round(float(val["last_price"]), 2)
        except Exception:
            pass

    # Tier 2: Yahoo Finance Live API (Universal, Fast, No Auth Required)
    # FINNIFTY has no Yahoo Finance ticker; it remains 0.0 if Dhan fails.
    yf_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    for sym, ticker in yf_map.items():
        if spots[sym] <= 0:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1m&range=1d"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
                if resp.status_code == 200:
                    meta = resp.json()["chart"]["result"][0]["meta"]
                    p = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
                    if p and float(p) > 0:
                        spots[sym] = round(float(p), 2)
            except Exception:
                pass

    # Tier 3: BSE Official Web API for SENSEX
    if spots["SENSEX"] <= 0:
        try:
            r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/Sensex/w", headers={"User-Agent": "Mozilla/5.0"}, timeout=2)
            if r.status_code == 200 and "curval" in r.json():
                spots["SENSEX"] = float(str(r.json()["curval"]).replace(",", ""))
        except Exception:
            pass

    # P0.10: Never return a hardcoded constant — leave zeros for callers to reject.
    return spots

if __name__ == "__main__":
    print("Testing Live Spot Engine:", get_live_spots())
