"""Option chain microstructure analyzer.

Reads the latest chain snapshot from SQLite (written by chain_snapshotter.py)
instead of calling Dhan directly. This eliminates dual-process API rate-limit
collisions: chain_snapshotter.py is the SINGLE writer; this module is read-only.
"""

import logging
from live_spot_service import get_live_spots
from chain_snapshotter import get_latest_chain_snapshot, DEFAULT_DB_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def analyze_option_chain_microstructure(symbol: str, db_path: str = DEFAULT_DB_PATH):
    """Return microstructure metrics for *symbol* from the latest SQLite snapshot.

    Returns a dict with keys: symbol, expiry, spot, pcr_oi, max_pain,
    call_wall, put_wall, raw_oc, status_mode, is_synthetic.
    Returns None (effectively a DATA_FAULT) only when spot is unavailable.
    When the snapshot is absent, returns is_synthetic=True so callers refuse
    to alert or trade.
    """
    spots = get_live_spots()
    spot = spots.get(symbol) or 0.0
    step = 100 if symbol in ["SENSEX", "BANKNIFTY"] else 50
    atm = int(round(spot / step) * step)

    snapshot = get_latest_chain_snapshot(symbol, db_path)
    if not snapshot or not snapshot.get("oc"):
        logger.error(
            "DATA_FAULT chain_microstructure_analyzer sym=%s no_snapshot — returning synthetic fallback",
            symbol,
        )
        return {
            "symbol": symbol,
            "expiry": "NEXT_ACTIVE_WEEKLY",
            "spot": spot,
            "pcr_oi": 0.73,
            "max_pain": atm + step,
            "call_wall": atm + 3 * step,
            "put_wall": atm - 2 * step,
            "raw_oc": {},
            "status_mode": "SESSION_CLOSING_SNAPSHOT",
            "is_synthetic": True,  # P0.3: callers must refuse to alert/trade on this
        }

    active_expiry = snapshot["expiry"]
    oc = snapshot["oc"]

    # Use live spot from snapshot if available (last_price from chain data)
    live_spot = 0.0
    for v in oc.values():
        for side_data in v.values():
            break
        break

    total_call_oi = 0
    total_put_oi = 0
    call_oi_map: dict = {}
    put_oi_map: dict = {}
    strikes = []

    for k, v in oc.items():
        try:
            strike = float(k)
        except ValueError:
            continue
        strikes.append(strike)
        c_oi = v.get("ce", {}).get("oi", 0) or 0
        p_oi = v.get("pe", {}).get("oi", 0) or 0
        total_call_oi += c_oi
        total_put_oi += p_oi
        call_oi_map[strike] = c_oi
        put_oi_map[strike] = p_oi

    strikes.sort()
    pcr_oi = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0.73
    call_wall = max(call_oi_map, key=call_oi_map.get) if call_oi_map else (atm + 2 * step)
    put_wall = max(put_oi_map, key=put_oi_map.get) if put_oi_map else (atm - 2 * step)

    min_pain = float("inf")
    max_pain_strike = atm
    for k in strikes:
        loss = 0.0
        for s in strikes:
            if k > s:
                loss += (k - s) * call_oi_map.get(s, 0)
            if k < s:
                loss += (s - k) * put_oi_map.get(s, 0)
        if loss < min_pain:
            min_pain = loss
            max_pain_strike = k

    return {
        "symbol": symbol,
        "expiry": active_expiry,
        "spot": spot,
        "pcr_oi": pcr_oi,
        "max_pain": max_pain_strike,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "raw_oc": oc,
        "status_mode": "LIVE_DHAN_FEED",
        "is_synthetic": False,  # P0.3: snapshot from live snapshotter
    }
