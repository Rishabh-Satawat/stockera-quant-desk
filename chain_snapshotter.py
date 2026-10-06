"""Chain snapshotter — polls all 4 index option chains every ~20-30 s.

Rate limit: 1 unique Dhan API request per 3 seconds (global lock).
Staggered round-robin schedule: NIFTY → BANKNIFTY → FINNIFTY → SENSEX,
two requests per symbol (expirylist + chain), 3 s apart, ~32 s cycle.

Persists raw snapshots to chain_snapshots table (WAL mode).
IV = NULL when Dhan returns 0 or None — never stores 0 as a numeric IV.
"""

import os
import time
import datetime
import threading
import logging
import sqlite3
from zoneinfo import ZoneInfo
from typing import Optional
from dotenv import load_dotenv
import requests

from db_init import init_db, get_connection, DEFAULT_DB_PATH
import bar_builder as _bar_builder

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_SCRIP_MAP = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}
_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

# Global rate limiter: at most 1 request per 3 s across all symbols
_RATE_LOCK = threading.Lock()
_LAST_REQUEST_TS: float = 0.0
_MIN_INTERVAL: float = 3.1  # slightly above 3 s for safety


def _throttled_post(url: str, payload: dict, timeout: int = 5) -> Optional[dict]:
    global _LAST_REQUEST_TS
    with _RATE_LOCK:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _LAST_REQUEST_TS)
        if wait > 0:
            time.sleep(wait)
        try:
            h = {
                "access-token": _ACCESS_TOKEN,
                "client-id": _CLIENT_ID,
                "Content-Type": "application/json",
            }
            r = requests.post(url, headers=h, json=payload, timeout=timeout)
            _LAST_REQUEST_TS = time.monotonic()
            if r.status_code == 200:
                return r.json()
            logger.warning("HTTP %s from %s", r.status_code, url)
            return None
        except Exception as exc:
            logger.error("Request failed %s: %s", url, exc)
            _LAST_REQUEST_TS = time.monotonic()
            return None


def _iv_guard(raw_iv) -> Optional[float]:
    """Returns None if raw_iv is 0, falsy, or non-positive — never stores 0."""
    if raw_iv is None:
        return None
    try:
        v = float(raw_iv)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _fetch_and_persist(symbol: str, db_path: str) -> int:
    scrip_id = _SCRIP_MAP[symbol]
    now_ist = datetime.datetime.now(tz=_IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    past_close = now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 30)

    # Request 1: expirylist
    exp_resp = _throttled_post(
        "https://api.dhan.co/v2/optionchain/expirylist",
        {"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"},
    )
    if not exp_resp:
        logger.error("DATA_FAULT expirylist failed sym=%s — skipping snapshot", symbol)
        return 0

    exp_list = exp_resp.get("data", [])
    if not exp_list:
        return 0

    active_expiry = exp_list[0]
    if past_close and active_expiry <= today_str and len(exp_list) > 1:
        active_expiry = exp_list[1]

    # Request 2: option chain
    chain_resp = _throttled_post(
        "https://api.dhan.co/v2/optionchain",
        {"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I", "Expiry": active_expiry},
    )
    if not chain_resp:
        logger.error("DATA_FAULT chain fetch failed sym=%s expiry=%s", symbol, active_expiry)
        return 0

    d = chain_resp.get("data", {})
    oc = d.get("oc", {})
    if not oc:
        return 0

    ts_ist = datetime.datetime.now(tz=_IST).isoformat()

    # Store underlying spot price as a SPOT sentinel row so bar_builder
    # can aggregate underlying_bars without a separate API call.
    underlying_ltp = d.get("last_price") or d.get("underlying_ltp") or d.get("underlyingLtp")
    rows = []
    if underlying_ltp is not None:
        try:
            _ultp = float(underlying_ltp)
            if _ultp > 0:
                rows.append((
                    symbol,
                    active_expiry,
                    0.0,        # strike = 0 for spot sentinel
                    "SPOT",
                    ts_ist,
                    _ultp,
                    0,          # oi
                    0,          # volume
                    None,       # iv
                    None, None, None, None,  # greeks
                    scrip_id,
                    0,          # is_synthetic
                ))
        except (TypeError, ValueError):
            pass
    for strike_key, legs in oc.items():
        try:
            strike = float(strike_key)
        except ValueError:
            continue
        for side, opt_type in (("ce", "CE"), ("pe", "PE")):
            leg = legs.get(side, {})
            if not leg:
                continue
            ltp = leg.get("last_price")
            if ltp is None:
                continue
            security_id = leg.get("security_id")
            if not security_id:
                continue
            greeks = leg.get("greeks") or {}
            iv_val = _iv_guard(leg.get("implied_volatility"))
            rows.append((
                symbol,
                active_expiry,
                strike,
                opt_type,
                ts_ist,
                float(ltp),
                int(leg.get("oi") or 0),
                int(leg.get("volume") or 0),
                iv_val,                          # NULL when zero/None
                greeks.get("delta"),
                greeks.get("theta"),
                greeks.get("gamma"),
                greeks.get("vega"),
                int(security_id),
                0,  # is_synthetic = 0 (live feed)
            ))

    if not rows:
        return 0

    conn = get_connection(db_path)
    try:
        conn.executemany(
            """INSERT OR REPLACE INTO chain_snapshots
               (symbol, expiry, strike, option_type, timestamp,
                ltp, oi, volume, iv, delta, theta, gamma, vega,
                security_id, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Snapshot saved: sym=%s expiry=%s rows=%d", symbol, active_expiry, len(rows))
    return len(rows)


def get_latest_chain_snapshot(
    symbol: str,
    db_path: str = DEFAULT_DB_PATH,
    max_age_seconds: float = 90,
) -> dict:
    """Return the most recent chain snapshot for *symbol* from SQLite.

    Returns a dict with keys:
      "oc"                  - {strike_str: {"ce": {...}, "pe": {...}}}
      "expiry"              - expiry date string (YYYY-MM-DD)
      "symbol"              - the symbol
      "snapshot_age_seconds"- age of snapshot in seconds (float)

    Returns an empty dict ({}) when:
      - No snapshot exists yet.
      - The newest snapshot's date != today's trading date in IST.
      - The snapshot is older than max_age_seconds (default 90s).

    An empty return triggers is_synthetic=True in chain_microstructure_analyzer
    which causes the hunter to log DATA_FAULT and abort — fail-closed design.

    The returned dict is derived from the chain_snapshots table written by
    the single-writer snapshotter; callers MUST NOT hit Dhan directly.
    """
    try:
        init_db(db_path)
        now_ist = datetime.datetime.now(tz=ZoneInfo("Asia/Kolkata"))
        today_str = now_ist.strftime("%Y-%m-%d")

        conn = get_connection(db_path)
        try:
            # Find the latest timestamp for this symbol
            cur = conn.execute(
                "SELECT MAX(timestamp) FROM chain_snapshots WHERE symbol = ?",
                (symbol,),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return {}

            latest_ts = row[0]

            # Parse the ISO timestamp (may have +05:30 offset or be naive IST)
            try:
                snap_dt = datetime.datetime.fromisoformat(latest_ts)
                if snap_dt.tzinfo is None:
                    snap_dt = snap_dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
                else:
                    snap_dt = snap_dt.astimezone(ZoneInfo("Asia/Kolkata"))
            except ValueError:
                logger.error(
                    "get_latest_chain_snapshot sym=%s invalid ts=%s", symbol, latest_ts
                )
                return {}

            # Staleness gate 1: snapshot must be from today (IST date)
            snap_date_str = snap_dt.strftime("%Y-%m-%d")
            if snap_date_str != today_str:
                logger.warning(
                    "STALENESS_GATE sym=%s snap_date=%s today=%s — rejecting stale snapshot",
                    symbol, snap_date_str, today_str,
                )
                return {}

            # Staleness gate 2: snapshot must be recent enough
            age_seconds = (now_ist - snap_dt).total_seconds()
            if age_seconds > max_age_seconds:
                logger.warning(
                    "STALENESS_GATE sym=%s age=%.1fs max=%ss — rejecting stale snapshot",
                    symbol, age_seconds, max_age_seconds,
                )
                return {}

            cur = conn.execute(
                """SELECT strike, option_type, expiry, ltp, oi, volume,
                          iv, delta, theta, gamma, vega, security_id
                   FROM chain_snapshots
                   WHERE symbol = ? AND timestamp = ?""",
                (symbol, latest_ts),
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            return {}

        oc: dict = {}
        expiry = ""
        for strike, opt_type, row_expiry, ltp, oi, volume, iv, delta, theta, gamma, vega, sec_id in rows:
            expiry = row_expiry
            k = str(int(strike)) if strike == int(strike) else str(strike)
            if k not in oc:
                oc[k] = {}
            oc[k][opt_type.lower()] = {
                "last_price": ltp,
                "oi": oi,
                "volume": volume,
                "implied_volatility": iv,
                "security_id": sec_id,
                "greeks": {
                    "delta": delta,
                    "theta": theta,
                    "gamma": gamma,
                    "vega": vega,
                },
            }

        return {
            "symbol": symbol,
            "expiry": expiry,
            "oc": oc,
            "snapshot_age_seconds": round(age_seconds, 1),
        }

    except Exception as exc:
        logger.error("get_latest_chain_snapshot sym=%s err=%s", symbol, exc)
        return {}


def poll_once(symbol: str, db_path: str = DEFAULT_DB_PATH) -> int:
    """Fetch one chain snapshot and persist. Returns rows inserted."""
    init_db(db_path)
    if not _ACCESS_TOKEN or not _CLIENT_ID:
        raise RuntimeError("Dhan credentials not loaded")
    return _fetch_and_persist(symbol, db_path)


def _kick_bar_builder(db_path: str) -> None:
    """Fire bar_builder.build_bars() in a daemon thread — non-blocking."""
    def _run():
        try:
            summary = _bar_builder.build_bars(db_path)
            logger.info("bar_builder cycle complete: %s", summary)
        except Exception as exc:
            logger.error("bar_builder error: %s", exc)

    t = threading.Thread(target=_run, daemon=True, name="bar-builder")
    t.start()


def run_forever(db_path: str = DEFAULT_DB_PATH) -> None:
    """Round-robin poller across all 4 symbols. Blocks until interrupted."""
    init_db(db_path)
    logger.info("Chain snapshotter started. DB: %s", db_path)

    # Stagger start times: each symbol delayed by 8 s within the cycle
    # so they never fire simultaneously.
    idx = 0
    while True:
        symbol = _SYMBOLS[idx % len(_SYMBOLS)]
        try:
            rows = _fetch_and_persist(symbol, db_path)
            if rows == 0:
                logger.warning("Zero rows for %s — data fault or off-hours", symbol)
        except Exception as exc:
            logger.error("Unhandled error polling %s: %s", symbol, exc)
        idx += 1

        # After every full cycle (all 4 symbols polled), trigger bar aggregation
        # in a background daemon thread so it never delays the rate-limited loop.
        if idx % len(_SYMBOLS) == 0:
            _kick_bar_builder(db_path)

        # Sleep between symbols so we don't hit the rate limit back-to-back.
        # Each symbol needs 2 requests (expirylist + chain); the throttle
        # adds ~3.1 s per request internally.  Extra 2 s between symbols
        # gives ~32 s full-cycle.
        time.sleep(2)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH
    run_forever(db)
