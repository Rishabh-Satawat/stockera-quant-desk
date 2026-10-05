"""Volatility Engine — Phase 1B.

Reads from chain_snapshots and underlying_bars in SQLite.
Computes IVR, IVP, 25-delta risk reversal, VRP, and volatility regime.

All inputs are read from the single-writer chain_timeseries.db; this module
never calls Dhan directly.
"""

import math
import logging
import datetime
import sqlite3
from typing import Optional
from zoneinfo import ZoneInfo

from db_init import DEFAULT_DB_PATH, get_connection

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _today_str() -> str:
    return datetime.datetime.now(tz=_IST).strftime("%Y-%m-%d")


def _session_ivs(symbol: str, expiry: str, db_path: str) -> list[float]:
    """Return all non-null ATM-ish IVs recorded today (any strike) as a list."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT iv FROM chain_snapshots
               WHERE symbol=? AND expiry=? AND iv IS NOT NULL
                 AND date(timestamp)=?
               ORDER BY timestamp""",
            (symbol, expiry, today),
        )
        return [row[0] for row in cur.fetchall() if row[0] is not None and row[0] > 0]
    finally:
        conn.close()


def _latest_snapshot_rows(
    symbol: str, expiry: str, db_path: str
) -> list[tuple]:
    """Return all rows from the latest snapshot for symbol+expiry today."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT MAX(timestamp) FROM chain_snapshots
               WHERE symbol=? AND expiry=? AND date(timestamp)=?""",
            (symbol, expiry, today),
        )
        row = cur.fetchone()
        if not row or row[0] is None:
            return []
        latest_ts = row[0]
        cur = conn.execute(
            """SELECT strike, option_type, iv, delta, gamma, oi
               FROM chain_snapshots
               WHERE symbol=? AND expiry=? AND timestamp=?""",
            (symbol, expiry, latest_ts),
        )
        return cur.fetchall()
    finally:
        conn.close()


def _underlying_bars_5m(symbol: str, db_path: str) -> list[float]:
    """Return today's 5-minute close prices for the symbol."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT close FROM underlying_bars
               WHERE symbol=? AND bar_tf='5m' AND date(bar_open_ts)=?
               ORDER BY bar_open_ts""",
            (symbol, today),
        )
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# IV Rank & Percentile
# ──────────────────────────────────────────────────────────────────────────────

def compute_ivr(ivs: list[float]) -> Optional[float]:
    """IV Rank = (IV_current - IV_min) / (IV_max - IV_min) * 100."""
    if len(ivs) < 2:
        return None
    iv_min = min(ivs)
    iv_max = max(ivs)
    if iv_max == iv_min:
        return None
    return (ivs[-1] - iv_min) / (iv_max - iv_min) * 100.0


def compute_ivp(ivs: list[float]) -> Optional[float]:
    """IV Percentile = % of session observations below current IV."""
    if len(ivs) < 2:
        return None
    current = ivs[-1]
    below = sum(1 for v in ivs[:-1] if v < current)
    return below / (len(ivs) - 1) * 100.0


# ──────────────────────────────────────────────────────────────────────────────
# 25-Delta Risk Reversal
# ──────────────────────────────────────────────────────────────────────────────

def _find_delta_strike(rows: list[tuple], target_delta: float) -> Optional[float]:
    """Return the IV of the strike whose delta is closest to target_delta."""
    best_iv = None
    best_diff = float("inf")
    for strike, opt_type, iv, delta, gamma, oi in rows:
        if delta is None or iv is None or iv <= 0:
            continue
        diff = abs(delta - target_delta)
        if diff < best_diff:
            best_diff = diff
            best_iv = iv
    return best_iv


def compute_rr_25(rows: list[tuple]) -> Optional[float]:
    """25-delta Risk Reversal = IV_25Δput - IV_25Δcall."""
    call_rows = [(s, ot, iv, d, g, o) for s, ot, iv, d, g, o in rows if ot == "CE"]
    put_rows = [(s, ot, iv, d, g, o) for s, ot, iv, d, g, o in rows if ot == "PE"]
    if not call_rows or not put_rows:
        return None
    # Call side: target delta ≈ +0.25
    iv_call = _find_delta_strike(call_rows, 0.25)
    # Put side: delta is negative, target ≈ -0.25
    iv_put = _find_delta_strike(put_rows, -0.25)
    if iv_call is None or iv_put is None:
        return None
    return iv_put - iv_call


# ──────────────────────────────────────────────────────────────────────────────
# Realized Volatility (5m bars, session-annualized)
# ──────────────────────────────────────────────────────────────────────────────

def compute_rv_5m(closes: list[float]) -> Optional[float]:
    """Annualized RV from 5m log returns. Session annualization: 375 min/session, 252 sessions/year."""
    if len(closes) < 2:
        return None
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    n = len(log_returns)
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / n
    std = math.sqrt(variance)
    # 5m bars: 75 bars per session (375 min / 5), 252 sessions/year
    bars_per_session = 75
    sessions_per_year = 252
    annualization = math.sqrt(bars_per_session * sessions_per_year)
    return std * annualization


# ──────────────────────────────────────────────────────────────────────────────
# ATM IV
# ──────────────────────────────────────────────────────────────────────────────

def _atm_iv(rows: list[tuple]) -> Optional[float]:
    """ATM IV: nearest-to-0.5 delta call strike IV."""
    call_rows = [(s, ot, iv, d, g, o) for s, ot, iv, d, g, o in rows if ot == "CE"]
    if not call_rows:
        return None
    return _find_delta_strike(call_rows, 0.5)


# ──────────────────────────────────────────────────────────────────────────────
# Volatility Regime
# ──────────────────────────────────────────────────────────────────────────────

def ivr_to_regime(ivr: Optional[float]) -> str:
    if ivr is None:
        return "UNKNOWN"
    if ivr < 25:
        return "LOW_VOL"
    if ivr <= 70:
        return "NORMAL_VOL"
    if ivr <= 85:
        return "ELEVATED_VOL"
    return "HIGH_VOL"


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def compute_vol_metrics(symbol: str, expiry: str, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Compute all volatility metrics for symbol+expiry.

    Returns dict with keys:
      ivr, ivp, rr_25, vrp, vol_regime, atm_iv, rv_5m
    None values indicate insufficient or unavailable data.
    """
    ivs = _session_ivs(symbol, expiry, db_path)
    rows = _latest_snapshot_rows(symbol, expiry, db_path)
    closes = _underlying_bars_5m(symbol, db_path)

    ivr = compute_ivr(ivs)
    ivp = compute_ivp(ivs)
    rr_25 = compute_rr_25(rows) if rows else None
    atm_iv_val = _atm_iv(rows) if rows else None
    rv = compute_rv_5m(closes)

    vrp = None
    if atm_iv_val is not None and rv is not None:
        vrp = atm_iv_val - rv

    vol_regime = ivr_to_regime(ivr)

    return {
        "ivr": ivr,
        "ivp": ivp,
        "rr_25": rr_25,
        "vrp": vrp,
        "vol_regime": vol_regime,
        "atm_iv": atm_iv_val,
        "rv_5m": rv,
    }
