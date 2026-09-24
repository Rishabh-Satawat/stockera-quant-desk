import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

def get_live_spots():
    spots = {"NIFTY": 0.0, "BANKNIFTY": 0.0, "SENSEX": 0.0}

    # Tier 1: Dhan HQ v2 Marketfeed with correct NSE & BSE segments
    if DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID:
        try:
            h = {"access-token": DHAN_ACCESS_TOKEN, "client-id": DHAN_CLIENT_ID, "Content-Type": "application/json"}
            payload = {"NSE_IDX": [13, 25], "BSE_IDX": [51]}
            r = requests.post("https://api.dhan.co/v2/marketfeed/ltp", headers=h, json=payload, timeout=3)
            if r.status_code == 200:
                data = r.json().get("data", {})
                nse = data.get("NSE_IDX", {})
                bse = data.get("BSE_IDX", {})

                n_val = nse.get("13") or nse.get(13) or {}
                if "last_price" in n_val and float(n_val["last_price"]) > 0:
                    spots["NIFTY"] = round(float(n_val["last_price"]), 2)

                bn_val = nse.get("25") or nse.get(25) or {}
                if "last_price" in bn_val and float(bn_val["last_price"]) > 0:
                    spots["BANKNIFTY"] = round(float(bn_val["last_price"]), 2)

                sx_val = bse.get("51") or bse.get(51) or {}
                if "last_price" in sx_val and float(sx_val["last_price"]) > 0:
                    spots["SENSEX"] = round(float(sx_val["last_price"]), 2)
        except Exception:
            pass

    # Tier 2: Yahoo Finance Live API (Universal, Fast, No Auth Required)
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

    # Safety fallbacks if offline
    if spots["NIFTY"] <= 0: spots["NIFTY"] = 25820.0
    if spots["BANKNIFTY"] <= 0: spots["BANKNIFTY"] = 54150.0
    if spots["SENSEX"] <= 0: spots["SENSEX"] = 84250.0

    return spots

if __name__ == "__main__":
    print("Testing Live Spot Engine:", get_live_spots())
