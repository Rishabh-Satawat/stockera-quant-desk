"""Instrument master: downloads Dhan scrip master CSV and resolves
near-month futures security_id and lot size for NIFTY, BANKNIFTY, FINNIFTY, SENSEX.

Source: https://images.dhan.co/api-data/api-scrip-master-detailed.csv
Cached to data/scrip_master_cache.csv and refreshed when older than 6 hours.
"""

import os
import csv
import datetime
import threading
import requests
from typing import Optional
from pathlib import Path

_SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
_CACHE_PATH = Path(__file__).parent / "data" / "scrip_master_cache.csv"
_CACHE_TTL_HOURS = 6

_INDEX_NAMES = {
    "NIFTY": ["NIFTY", "NIFTY 50"],
    "BANKNIFTY": ["BANKNIFTY", "NIFTY BANK"],
    "FINNIFTY": ["FINNIFTY", "NIFTY FIN SERVICE"],
    "SENSEX": ["SENSEX", "BSE SENSEX"],
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
        now = datetime.datetime.utcnow()
        stale = _loaded_at is None or (now - _loaded_at).total_seconds() > _CACHE_TTL_HOURS * 3600

        if not force and not stale and _loaded_rows:
            return _loaded_rows

        # Try fresh download first; fall back to cache on network failure
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


def _futidx_rows() -> list[dict]:
    rows = _ensure_loaded()
    return [r for r in rows if r.get("INSTRUMENT", "").strip().upper() == "FUTIDX"]


def _match_symbol(canonical: str, row_symbol: str) -> bool:
    row_sym = row_symbol.strip().upper()
    for alias in _INDEX_NAMES.get(canonical, [canonical]):
        if alias.upper() == row_sym:
            return True
    return False


def get_near_month_security_id(symbol: str) -> int:
    """Return the near-month FUTIDX security_id for the given index.

    Near-month = the row with the earliest expiry date among FUTIDX rows
    for this symbol. Raises RuntimeError if not found.
    """
    fut_rows = _futidx_rows()
    candidates = [r for r in fut_rows if _match_symbol(symbol, r.get("DISPLAY_NAME", "") or r.get("CUSTOM_SYMBOL", "") or r.get("SYMBOL", ""))]

    if not candidates:
        raise RuntimeError(f"No FUTIDX rows found for symbol {symbol!r}")

    # Sort by expiry date string (YYYY-MM-DD sorts lexicographically)
    def expiry_key(r: dict) -> str:
        # Try EXPIRY_DATE column; fall back to EXPIRY
        return r.get("EXPIRY_DATE", r.get("EXPIRY", "9999-12-31")).strip()

    candidates.sort(key=expiry_key)
    near = candidates[0]
    sid = near.get("SEM_SMST_SECURITY_ID") or near.get("SECURITY_ID") or near.get("SM_SECURITY_ID")
    if not sid:
        raise RuntimeError(f"security_id column not found in row for {symbol}: {near}")
    return int(str(sid).strip())


def get_lot_size(symbol: str) -> int:
    """Return official lot size for the given index from FUTIDX rows.

    Raises RuntimeError if not found.
    """
    fut_rows = _futidx_rows()
    candidates = [r for r in fut_rows if _match_symbol(symbol, r.get("DISPLAY_NAME", "") or r.get("CUSTOM_SYMBOL", "") or r.get("SYMBOL", ""))]

    if not candidates:
        raise RuntimeError(f"No FUTIDX rows found for symbol {symbol!r}")

    # All near-month rows should share the same lot size
    lot_col = None
    for col_name in ("LOT_SIZE", "SM_LOT_SIZE", "LOTSIZE"):
        if col_name in candidates[0]:
            lot_col = col_name
            break
    if not lot_col:
        raise RuntimeError(f"Lot size column not found in row for {symbol}: {candidates[0]}")

    return int(str(candidates[0][lot_col]).strip())
