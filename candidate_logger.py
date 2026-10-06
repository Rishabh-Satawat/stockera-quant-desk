"""Candidate Logger — Phase 1D.

Synchronously appends one row to the `candidates` table for every evaluated
PlaybookSignal, regardless of whether it was dispatched, watchlisted, or
dropped.  Dropped rows serve as the statistical control group for the
calibration reporter.

Rules:
  - NULL for any metric that was unavailable at evaluation time — never 0.0.
  - Rows are immutable after insert; outcome fields are added by outcome_labeller.
  - Thread-safe: uses a per-process sqlite connection opened on each call.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from db_init import DEFAULT_DB_PATH, init_db
from playbook_triggers import PlaybookSignal

logger = logging.getLogger(__name__)


def _null_if_zero(v: Optional[float]) -> Optional[float]:
    """Return None when a metric was unavailable (stored as 0.0 sentinel)."""
    if v is None:
        return None
    return None if v == 0.0 else v


def log_candidate(
    signal: PlaybookSignal,
    score_result: dict,
    dispatched: bool,
    skip_reason: Optional[str] = None,
    *,
    db_path: str = DEFAULT_DB_PATH,
    ts_override: Optional[str] = None,
) -> str:
    """Append a candidate row and return its candidate_id.

    Parameters
    ----------
    signal:       The evaluated PlaybookSignal.
    score_result: Dict returned by scoring_engine.score_candidate().
    dispatched:   True if the trade was actually sent to the broker.
    skip_reason:  Human-readable reason for Tier 2 watchlist or Tier 0 drop.
    db_path:      SQLite path (defaults to the shared timeseries DB).
    ts_override:  ISO-8601 UTC string for the signal timestamp (tests only).

    Returns the candidate_id string inserted.
    """
    init_db(db_path)

    ts = ts_override or datetime.now(timezone.utc).isoformat()
    candidate_id = str(uuid.uuid4())

    breakdown = score_result.get("breakdown", {})
    score_breakdown_json = json.dumps(breakdown)

    # GEX fields come from the signal sub_scores if populated by the hunter
    sub = signal.sub_scores or {}
    gamma_flip = _null_if_zero(sub.get("gamma_flip"))
    net_gex = _null_if_zero(sub.get("net_gex"))
    ivr = _null_if_zero(sub.get("ivr"))
    ivp = _null_if_zero(sub.get("ivp"))
    vrp = _null_if_zero(sub.get("vrp"))
    or_high = _null_if_zero(sub.get("or_high"))
    or_low = _null_if_zero(sub.get("or_low"))
    vwap = _null_if_zero(sub.get("vwap"))

    # Core microstructure: use None (not 0.0) when unavailable
    pcr = signal.pcr if signal.pcr != 0.0 else None
    max_pain = signal.max_pain if signal.max_pain != 0.0 else None
    call_wall = signal.call_wall if signal.call_wall != 0.0 else None
    put_wall = signal.put_wall if signal.put_wall != 0.0 else None
    pin_score = signal.pin_score if signal.pin_score != 0.0 else None

    row = (
        candidate_id,
        ts,
        signal.symbol,
        signal.expiry,
        signal.playbook_id,
        score_result["tier"],
        float(score_result["score"]),
        score_breakdown_json,
        signal.vol_regime,
        int(signal.vol_provisional),
        signal.direction,
        int(signal.direction_score),
        float(signal.spot),
        vwap,
        pcr,
        max_pain,
        call_wall,
        put_wall,
        gamma_flip,
        net_gex,
        pin_score,
        ivr,
        ivp,
        vrp,
        or_high,
        or_low,
        int(dispatched),
        skip_reason,
    )

    sql = """
        INSERT INTO candidates (
            candidate_id, ts_signal, symbol, expiry, playbook_id,
            tier, score, score_breakdown,
            vol_regime, vol_provisional,
            direction_label, direction_score,
            spot, vwap, pcr, max_pain, call_wall, put_wall,
            gamma_flip, net_gex, pin_score,
            ivr, ivp, vrp, or_high, or_low,
            dispatched, skip_reason
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?
        )
    """

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            conn.execute(sql, row)
            conn.commit()
            logger.debug("candidate_logger: logged %s %s tier=%d score=%d",
                         signal.symbol, signal.playbook_id,
                         score_result["tier"], score_result["score"])
        finally:
            conn.close()
    except Exception as exc:
        logger.error("candidate_logger: insert failed for %s — %s", signal.symbol, exc)

    return candidate_id


def load_candidates(
    db_path: str = DEFAULT_DB_PATH,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load candidates rows into a DataFrame.

    Parameters
    ----------
    db_path:    Path to chain_timeseries.db.
    start_date: Inclusive ISO date string (YYYY-MM-DD) in UTC.
    end_date:   Inclusive ISO date string (YYYY-MM-DD) in UTC.

    Returns an empty DataFrame when the table does not exist or has no rows.
    """
    init_db(db_path)

    conditions = []
    params: list = []

    if start_date:
        conditions.append("date(ts_signal) >= date(?)")
        params.append(start_date)
    if end_date:
        conditions.append("date(ts_signal) <= date(?)")
        params.append(end_date)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM candidates {where_clause} ORDER BY ts_signal"

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            df = pd.read_sql_query(sql, conn, params=params)
        finally:
            conn.close()
    except Exception as exc:
        logger.error("load_candidates: query failed — %s", exc)
        return pd.DataFrame()

    if not df.empty:
        df["score_breakdown"] = df["score_breakdown"].apply(
            lambda v: json.loads(v) if isinstance(v, str) else v
        )

    return df
