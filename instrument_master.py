"""Instrument master: downloads Dhan scrip master CSV and resolves
near-month futures security_id and lot size for NIFTY, BANKNIFTY, FINNIFTY, SENSEX.

Source: https://images.dhan.co/api-data/api-scrip-master-detailed.csv
Cached to data/scrip_master_cache.csv and refreshed when older than 6 hours.

Actual CSV header:
  EXCH_ID,SEGMENT,SECURITY_ID,ISIN,INSTRUMENT,UNDERLYING_SECURITY_ID,
  UNDERLYING_SYMBOL,SYMBOL_NAME,DISPLAY_NAME,INSTRUMENT_TYPE,SERIES,
  LOT_SIZE,SM_EXPIRY_DATE,...
"""

import os
import csv
import datetime
from datetime import timezone
import threading
import requests
from typing import Optional
from pathlib import Path

_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_CACHE_PATH = Path(__file__).parent / "data" / "scrip_master_cache.csv"
_CACHE_TTL_HOURS = 6

# EXCH_ID for each symbol
_EXCH_ID = {
    "NIFTY": "NSE",
    "BANKNIFTY": "NSE",
    "FINNIFTY": "NSE",
    "SENSEX": "BSE",
}

_lock = threading.Lock()
_loaded_rows: list[dict] = []
_loaded_at: Optional[datetime.datetime] = None


def _download_csv() -> list[dict]:
    """Download and parse the scrip master CSV."""
    r = requests.get(_SCRIP_MASTER_URL, timeout=30)
    r.raise_for_status()

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_bytes(r.content)

    lines = r.content.decode("utf-8", errors="replace").splitlines()
    return list(csv.DictReader(lines))


def _load_from_cache() -> list[dict]:
    """Load from local cache file."""
    lines = _CACHE_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    return list(csv.DictReader(lines))


def _ensure_loaded(force: bool = False) -> list[dict]:
    global _loaded_rows, _loaded_at
    with _lock:
        now = datetime.datetime.now(timezone.utc)
        stale = _loaded_at is None or (now - _loaded_at).total_seconds() > _CACHE_TTL_HOURS * 3600

        if not force and not stale and _loaded_rows:
            return _loaded_rows

        try:
            rows = _download_csv()
        except Exception:
            if _CACHE_PATH.exists():
                rows = _load_from_cache()
            else:
                raise RuntimeError("Cannot load scrip master: download failed and no local cache.")

        _loaded_rows = rows
        _loaded_at = now
        return rows


def _futidx_candidates(symbol: str) -> list[dict]:
    """Return FUTIDX rows matching the given canonical symbol."""
    rows = _ensure_loaded()
    exch = _EXCH_ID.get(symbol.upper(), "NSE")
    today = datetime.date.today().isoformat()  # YYYY-MM-DD

    candidates = []
    for r in rows:
        if r.get("INSTRUMENT", "").strip().upper() != "FUTIDX":
            continue
        if r.get("EXCH_ID", "").strip().upper() != exch:
            continue
        if r.get("UNDERLYING_SYMBOL", "").strip().upper() != symbol.upper():
            continue
        expiry = r.get("SM_EXPIRY_DATE", "").strip()
        if not expiry:
            continue
        if expiry >= today:
            candidates.append(r)

    # Sort by expiry date ascending so index 0 is near-month
    candidates.sort(key=lambda r: r.get("SM_EXPIRY_DATE", "9999-12-31").strip())
    return candidates


def get_near_month_security_id(symbol: str) -> int:
    """Return the near-month FUTIDX security_id for the given index.

    Raises RuntimeError if not found.
    """
    candidates = _futidx_candidates(symbol)
    if not candidates:
        raise RuntimeError(f"No FUTIDX rows found for symbol {symbol!r}")
    near = candidates[0]
    sid = near.get("SECURITY_ID")
    if not sid:
        raise RuntimeError(f"SECURITY_ID column not found in row for {symbol}: {near}")
    return int(str(sid).strip())


def get_lot_size(symbol: str) -> int:
    """Return official lot size for the given index from near-month FUTIDX row.

    Raises RuntimeError if not found.
    """
    candidates = _futidx_candidates(symbol)
    if not candidates:
        raise RuntimeError(f"No FUTIDX rows found for symbol {symbol!r}")
    near = candidates[0]
    lot = near.get("LOT_SIZE")
    if not lot:
        raise RuntimeError(f"LOT_SIZE column not found in row for {symbol}: {near}")
    return int(str(lot).strip())
