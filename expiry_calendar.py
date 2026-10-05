"""Dynamic expiry calendar derived from Dhan expirylist at runtime.

Never uses hardcoded dates. Caches expirylist responses for 60 s.
"""

import os
import time
import datetime
import requests
import threading
from zoneinfo import ZoneInfo
from typing import Optional
from dotenv import load_dotenv

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
_DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
_DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

_IST = ZoneInfo("Asia/Kolkata")
_MARKET_CLOSE_HOUR = 15
_MARKET_CLOSE_MINUTE = 30

# IDX_I scrip ids matching SCRIP_MAP in chain_microstructure_analyzer
_SCRIP_MAP = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}

_CACHE: dict[str, tuple[float, list[datetime.date]]] = {}
_CACHE_TTL = 60.0
_LOCK = threading.Lock()


def _fetch_expirylist(symbol: str) -> list[datetime.date]:
    scrip_id = _SCRIP_MAP.get(symbol)
    if not scrip_id:
        raise ValueError(f"Unknown symbol: {symbol!r}")
    if not _DHAN_ACCESS_TOKEN or not _DHAN_CLIENT_ID:
        raise RuntimeError("Dhan credentials not loaded — cannot fetch expirylist")

    h = {
        "access-token": _DHAN_ACCESS_TOKEN,
        "client-id": _DHAN_CLIENT_ID,
        "Content-Type": "application/json",
    }
    r = requests.post(
        "https://api.dhan.co/v2/optionchain/expirylist",
        headers=h,
        json={"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"},
        timeout=5,
    )
    r.raise_for_status()
    raw = r.json().get("data", [])
    return [datetime.date.fromisoformat(d) for d in raw]


def _get_cached(symbol: str) -> list[datetime.date]:
    now = time.monotonic()
    with _LOCK:
        ts, data = _CACHE.get(symbol, (0.0, []))
        if now - ts < _CACHE_TTL and data:
            return data
    fresh = _fetch_expirylist(symbol)
    with _LOCK:
        _CACHE[symbol] = (now, fresh)
    return fresh


def get_all_expiries(symbol: str) -> list[datetime.date]:
    """All available expiries for symbol, ascending (sourced live)."""
    return list(_get_cached(symbol))


def get_near_expiry(symbol: str) -> datetime.date:
    """Nearest non-expired expiry.

    Uses IST now; if market is past close (>= 15:30) the front expiry is
    considered expired and the next one is returned.
    """
    expiries = _get_cached(symbol)
    if not expiries:
        raise RuntimeError(f"Empty expirylist for {symbol}")

    now_ist = datetime.datetime.now(tz=_IST)
    today = now_ist.date()
    past_close = now_ist.hour > _MARKET_CLOSE_HOUR or (
        now_ist.hour == _MARKET_CLOSE_HOUR
        and now_ist.minute >= _MARKET_CLOSE_MINUTE
    )

    for exp in expiries:
        if exp > today:
            return exp
        if exp == today and not past_close:
            return exp
    # all expiries exhausted — return last one as fallback (shouldn't happen mid-day)
    return expiries[-1]


def get_dte_minutes(
    symbol: str,
    expiry: datetime.date,
    as_of: Optional[datetime.datetime] = None,
) -> float:
    """Minutes from as_of to expiry close (15:30 IST).

    Returns 0.0 when as_of is at or past expiry close.
    as_of defaults to datetime.now(Asia/Kolkata).
    """
    if as_of is None:
        as_of = datetime.datetime.now(tz=_IST)
    elif as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=_IST)

    expiry_close = datetime.datetime(
        expiry.year, expiry.month, expiry.day,
        _MARKET_CLOSE_HOUR, _MARKET_CLOSE_MINUTE, 0,
        tzinfo=_IST,
    )
    delta = (expiry_close - as_of).total_seconds() / 60.0
    return max(0.0, delta)
