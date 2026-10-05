"""Regime Engine — Phase 1B.

Computes the 2-Axis Market Regime: Direction Score × Volatility Level.

Direction Score: 7 inputs, each contributing ±1 (range −7 to +7).
Volatility Level: from volatility_engine.ivr_to_regime().
Playbook: gating matrix from Alpha Master Plan §3.5.
"""

import logging
import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from db_init import DEFAULT_DB_PATH, get_connection
from volatility_engine import compute_vol_metrics, ivr_to_regime

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")


# ──────────────────────────────────────────────────────────────────────────────
# Direction Score Labels
# ──────────────────────────────────────────────────────────────────────────────

def score_to_direction(score: int) -> str:
    if score >= 5:
        return "STRONG_BULL"
    if score >= 2:
        return "BULL"
    if score >= -1:
        return "NEUTRAL"
    if score >= -4:
        return "BEAR"
    return "STRONG_BEAR"


# ──────────────────────────────────────────────────────────────────────────────
# Playbook Gating Matrix
# ──────────────────────────────────────────────────────────────────────────────

_PLAYBOOK_MATRIX: dict[tuple[str, str], str] = {
    ("STRONG_BULL", "LOW_VOL"):       "LONG_CALL_SPREAD",
    ("BULL",        "LOW_VOL"):       "LONG_CALL_SPREAD",
    ("STRONG_BULL", "NORMAL_VOL"):    "BULL_CALL_SPREAD",
    ("BULL",        "NORMAL_VOL"):    "BULL_CALL_SPREAD",
    ("STRONG_BULL", "ELEVATED_VOL"):  "LONG_CALL",
    ("BULL",        "ELEVATED_VOL"):  "LONG_CALL",
    ("STRONG_BULL", "HIGH_VOL"):      "LONG_CALL",
    ("BULL",        "HIGH_VOL"):      "LONG_CALL",
    ("STRONG_BEAR", "LOW_VOL"):       "LONG_PUT_SPREAD",
    ("BEAR",        "LOW_VOL"):       "LONG_PUT_SPREAD",
    ("STRONG_BEAR", "NORMAL_VOL"):    "BEAR_PUT_SPREAD",
    ("BEAR",        "NORMAL_VOL"):    "BEAR_PUT_SPREAD",
    ("STRONG_BEAR", "ELEVATED_VOL"):  "LONG_PUT",
    ("BEAR",        "ELEVATED_VOL"):  "LONG_PUT",
    ("STRONG_BEAR", "HIGH_VOL"):      "LONG_PUT",
    ("BEAR",        "HIGH_VOL"):      "LONG_PUT",
    ("NEUTRAL",     "LOW_VOL"):       "SHORT_STRANGLE",
    ("NEUTRAL",     "NORMAL_VOL"):    "IRON_CONDOR",
    ("NEUTRAL",     "ELEVATED_VOL"):  "STRADDLE_BUY",
    ("NEUTRAL",     "HIGH_VOL"):      "STRADDLE_BUY",
}


def get_playbook(direction: str, vol_regime: str) -> str:
    return _PLAYBOOK_MATRIX.get((direction, vol_regime), "NO_TRADE")


# ──────────────────────────────────────────────────────────────────────────────
# Helper: today's string
# ──────────────────────────────────────────────────────────────────────────────

def _today_str() -> str:
    return datetime.datetime.now(tz=_IST).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────────────────────────────────────
# Component 1: 15m VWAP Position
# ──────────────────────────────────────────────────────────────────────────────

def _score_vwap(symbol: str, spot: float, db_path: str) -> int:
    """Price vs session VWAP from 15m underlying_bars. +1 above, -1 below."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT open, high, low, close, volume
               FROM underlying_bars
               WHERE symbol=? AND bar_tf='15m' AND date(bar_open_ts)=?
               ORDER BY bar_open_ts""",
            (symbol, today),
        )
        bars = cur.fetchall()
    finally:
        conn.close()

    if not bars:
        return 0

    # Session VWAP = sum(typical_price * volume) / sum(volume)
    total_vol = sum(b[4] for b in bars)
    if total_vol == 0:
        return 0
    vwap = sum(((b[1] + b[2] + b[3]) / 3.0) * b[4] for b in bars) / total_vol

    return 1 if spot > vwap else -1


# ──────────────────────────────────────────────────────────────────────────────
# Component 2: 60m Swing Structure
# ──────────────────────────────────────────────────────────────────────────────

def _score_swing(symbol: str, db_path: str) -> int:
    """60m swing: group last 4×15m bars into 2 60m periods, detect HH/HL or LH/LL."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT high, low FROM underlying_bars
               WHERE symbol=? AND bar_tf='15m' AND date(bar_open_ts)=?
               ORDER BY bar_open_ts DESC LIMIT 8""",
            (symbol, today),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    # Need at least 8 bars (2 complete 60m candles of 4×15m each)
    if len(rows) < 8:
        return 0

    # Most recent 4 bars → "current 60m", next 4 → "prior 60m"
    cur_bars = rows[:4]
    prior_bars = rows[4:8]

    cur_high = max(b[0] for b in cur_bars)
    cur_low = min(b[1] for b in cur_bars)
    prior_high = max(b[0] for b in prior_bars)
    prior_low = min(b[1] for b in prior_bars)

    hh = cur_high > prior_high
    hl = cur_low > prior_low
    lh = cur_high < prior_high
    ll = cur_low < prior_low

    if hh and hl:
        return 1
    if lh and ll:
        return -1
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Component 3: PCR Z-Score
# ──────────────────────────────────────────────────────────────────────────────

def _score_pcr(symbol: str, expiry: str, db_path: str) -> int:
    """Rolling session PCR z-score. z > +1 → bearish (put heavy) → -1; z < -1 → +1."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT timestamp, option_type, SUM(oi) as total_oi
               FROM chain_snapshots
               WHERE symbol=? AND expiry=? AND date(timestamp)=?
               GROUP BY timestamp, option_type
               ORDER BY timestamp""",
            (symbol, expiry, today),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    # Build PCR time series: PCR = put_oi / call_oi per snapshot
    from collections import defaultdict
    ts_oi: dict = defaultdict(dict)
    for ts, opt_type, total_oi in rows:
        ts_oi[ts][opt_type] = total_oi

    pcrs = []
    for ts, oi_map in sorted(ts_oi.items()):
        call_oi = oi_map.get("CE", 0)
        put_oi = oi_map.get("PE", 0)
        if call_oi > 0:
            pcrs.append(put_oi / call_oi)

    if len(pcrs) < 3:
        return 0

    mean = sum(pcrs) / len(pcrs)
    variance = sum((p - mean) ** 2 for p in pcrs) / len(pcrs)
    import math
    std = math.sqrt(variance) if variance > 0 else 0

    if std == 0:
        return 0

    current_pcr = pcrs[-1]
    z = (current_pcr - mean) / std

    if z > 1:
        return -1  # put-heavy → bearish
    if z < -1:
        return 1   # call-heavy → bullish
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Component 4: OI Buildup
# ──────────────────────────────────────────────────────────────────────────────

def _score_oi_buildup(symbol: str, expiry: str, db_path: str) -> int:
    """If net OI change in last snapshot > +5% on calls → +1; on puts → -1."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        # Get the two most recent distinct timestamps
        cur = conn.execute(
            """SELECT DISTINCT timestamp FROM chain_snapshots
               WHERE symbol=? AND expiry=? AND date(timestamp)=?
               ORDER BY timestamp DESC LIMIT 2""",
            (symbol, expiry, today),
        )
        ts_rows = cur.fetchall()
        if len(ts_rows) < 2:
            return 0
        ts_new = ts_rows[0][0]
        ts_old = ts_rows[1][0]

        def get_oi(ts):
            cur2 = conn.execute(
                """SELECT option_type, SUM(oi) FROM chain_snapshots
                   WHERE symbol=? AND expiry=? AND timestamp=?
                   GROUP BY option_type""",
                (symbol, expiry, ts),
            )
            return {row[0]: row[1] for row in cur2.fetchall()}

        oi_new = get_oi(ts_new)
        oi_old = get_oi(ts_old)
    finally:
        conn.close()

    call_old = oi_old.get("CE", 0) or 0
    call_new = oi_new.get("CE", 0) or 0
    put_old = oi_old.get("PE", 0) or 0
    put_new = oi_new.get("PE", 0) or 0

    if call_old > 0:
        call_change_pct = (call_new - call_old) / call_old * 100
        if call_change_pct > 5:
            return 1
    if put_old > 0:
        put_change_pct = (put_new - put_old) / put_old * 100
        if put_change_pct > 5:
            return -1
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Component 5: Basis (Spot vs Near-Futures)
# ──────────────────────────────────────────────────────────────────────────────

def _score_basis(spot: float, futures_price: Optional[float]) -> int:
    """Futures > spot → contango → +1; backwardation → -1; unavailable → 0."""
    if futures_price is None:
        return 0
    if futures_price > spot:
        return 1
    if futures_price < spot:
        return -1
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Component 6: IV Term Structure Slope
# ──────────────────────────────────────────────────────────────────────────────

def _score_iv_term_structure(symbol: str, db_path: str) -> int:
    """Near IV > Far IV (inverted) → fear → -1; normal slope → +1."""
    today = _today_str()
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            """SELECT expiry, AVG(iv) as avg_iv
               FROM chain_snapshots
               WHERE symbol=? AND date(timestamp)=? AND iv IS NOT NULL AND iv > 0
               GROUP BY expiry
               ORDER BY expiry LIMIT 2""",
            (symbol, today),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        return 0

    near_iv = rows[0][1]
    far_iv = rows[1][1]

    if near_iv is None or far_iv is None:
        return 0

    if near_iv > far_iv:
        return -1  # inverted = fear
    return 1       # normal contango


# ──────────────────────────────────────────────────────────────────────────────
# Component 7: Delta-Weighted Put/Call Ratio
# ──────────────────────────────────────────────────────────────────────────────

def _score_delta_weighted_pcr(symbol: str, expiry: str, db_path: str) -> int:
    """Delta-weighted PCR > 1.1 → -1; < 0.9 → +1; else 0."""
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
            return 0
        latest_ts = row[0]

        cur = conn.execute(
            """SELECT option_type, ABS(delta), oi
               FROM chain_snapshots
               WHERE symbol=? AND expiry=? AND timestamp=?
                 AND delta IS NOT NULL AND oi > 0""",
            (symbol, expiry, latest_ts),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return 0

    sum_put_dw = 0.0
    sum_call_dw = 0.0
    for opt_type, abs_delta, oi in rows:
        if opt_type == "PE":
            sum_put_dw += abs_delta * oi
        elif opt_type == "CE":
            sum_call_dw += abs_delta * oi

    if sum_call_dw == 0:
        return 0

    ratio = sum_put_dw / sum_call_dw
    if ratio > 1.1:
        return -1
    if ratio < 0.9:
        return 1
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def compute_regime(
    symbol: str,
    expiry: str,
    spot: float,
    db_path: str = DEFAULT_DB_PATH,
    futures_price: Optional[float] = None,
) -> dict:
    """Compute 2-axis market regime for symbol+expiry at given spot.

    Args:
        symbol: underlying symbol (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
        expiry: expiry date string (YYYY-MM-DD)
        spot: current underlying spot price
        db_path: SQLite database path
        futures_price: near-month futures LTP (optional, used for basis component)

    Returns dict with keys:
        direction_score, direction_label, vol_regime, playbook,
        component_scores (dict of 7 named scores)
    """
    # Compute vol metrics for regime
    vol_metrics = compute_vol_metrics(symbol, expiry, db_path)
    vol_regime = vol_metrics.get("vol_regime", "UNKNOWN")

    # Compute each of the 7 direction components
    c1_vwap = _score_vwap(symbol, spot, db_path)
    c2_swing = _score_swing(symbol, db_path)
    c3_pcr = _score_pcr(symbol, expiry, db_path)
    c4_oi_buildup = _score_oi_buildup(symbol, expiry, db_path)
    c5_basis = _score_basis(spot, futures_price)
    c6_term_structure = _score_iv_term_structure(symbol, db_path)
    c7_dw_pcr = _score_delta_weighted_pcr(symbol, expiry, db_path)

    component_scores = {
        "vwap_position": c1_vwap,
        "swing_structure": c2_swing,
        "pcr_zscore": c3_pcr,
        "oi_buildup": c4_oi_buildup,
        "basis": c5_basis,
        "iv_term_structure": c6_term_structure,
        "delta_weighted_pcr": c7_dw_pcr,
    }

    direction_score = sum(component_scores.values())
    direction_label = score_to_direction(direction_score)
    playbook = get_playbook(direction_label, vol_regime)

    return {
        "direction_score": direction_score,
        "direction_label": direction_label,
        "vol_regime": vol_regime,
        "playbook": playbook,
        "component_scores": component_scores,
    }
