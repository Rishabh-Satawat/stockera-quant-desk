import os
import requests
import json
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

def get_live_spots():
    """Return live index spot prices.

    Values are None when unavailable — callers must treat None (and 0.0) as
    DATA_FAULT and refuse to trade.  Never defaults to a hardcoded constant.

    FINNIFTY (security_id=27, IDX_I segment) is fetched via the same Dhan
    LTP endpoint as the other three indices.  There is no Yahoo Finance
    fallback for FINNIFTY; if Dhan returns 0 or the field is absent, FINNIFTY
    is returned as None so callers can detect the fault rather than trading
    on a stale 0.00 price.
    """
    spots: dict = {"NIFTY": None, "BANKNIFTY": None, "FINNIFTY": None, "SENSEX": None}

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
                    # Dhan may key IDX_I entries by string or int
                    val = idx.get(str(sec_id)) or idx.get(sec_id) or {}
                    if "last_price" in val:
                        try:
                            lp = float(val["last_price"])
                            if lp > 0:
                                spots[sym] = round(lp, 2)
                        except (TypeError, ValueError):
                            pass
        except Exception:
            pass

    # Tier 2: Yahoo Finance Live API (Universal, Fast, No Auth Required)
    # NOTE: FINNIFTY has no Yahoo Finance ticker — it is NOT included here.
    # If Dhan returned None for FINNIFTY, callers will see None (DATA_FAULT).
    yf_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    for sym, ticker in yf_map.items():
        if not spots[sym]:
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
    if not spots["SENSEX"]:
        try:
            r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/Sensex/w", headers={"User-Agent": "Mozilla/5.0"}, timeout=2)
            if r.status_code == 200 and "curval" in r.json():
                spots["SENSEX"] = float(str(r.json()["curval"]).replace(",", ""))
        except Exception:
            pass

    # P0.10: Return None for unavailable feeds — callers must reject None/0.
    return spots

if __name__ == "__main__":
    print("Testing Live Spot Engine:", get_live_spots())
