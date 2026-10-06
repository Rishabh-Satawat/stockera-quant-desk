"""Candidate Logger — Phase 1D/1G.

Logs every evaluated PlaybookSignal to the `candidates` table with deduplication
(Phase 1G): repeated scans of the same setup key are collapsed into one row via
UPSERT rather than creating a new row every 60-second scan.

Setup key: symbol|playbook_id|expiry|direction_vol_regime
UPSERT logic:
  - First observation  → INSERT with first_seen=last_seen=ts, occurrences=1.
  - Repeat (same key)  → UPDATE last_seen, occurrences+=1, keep peak score.
  - Regime shift       → Close old row (setup_closed_at), INSERT new row.

Rules:
  - NULL for any metric unavailable at evaluation time — never 0.0.
  - outcome fields are added by outcome_labeller — not touched here.
  - Thread-safe: opens a fresh SQLite connection on each call.
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


def _build_setup_key(signal: PlaybookSignal) -> str:
    """Return the dedup key for this signal."""
    regime_bucket = f"{signal.direction}_{signal.vol_regime}"
    return f"{signal.symbol}|{signal.playbook_id}|{signal.expiry}|{regime_bucket}"


def log_candidate(
    signal: PlaybookSignal,
    score_result: dict,
    dispatched: bool,
    skip_reason: Optional[str] = None,
    *,
    db_path: str = DEFAULT_DB_PATH,
    ts_override: Optional[str] = None,
) -> str:
    """Upsert a candidate row and return its candidate_id.

    Parameters
    ----------
    signal:       The evaluated PlaybookSignal.
    score_result: Dict returned by scoring_engine.score_candidate().
    dispatched:   True if the trade was actually sent to the broker.
    skip_reason:  Human-readable reason for Tier 2 watchlist or Tier 0 drop.
    db_path:      SQLite path (defaults to the shared timeseries DB).
    ts_override:  ISO-8601 UTC string for the signal timestamp (tests only).

    Returns the candidate_id of the inserted or updated row.
    """
    init_db(db_path)

    ts = ts_override or datetime.now(timezone.utc).isoformat()
    setup_key = _build_setup_key(signal)

    breakdown = score_result.get("breakdown", {})
    score_breakdown_json = json.dumps(breakdown)

    sub = signal.sub_scores or {}
    gamma_flip = _null_if_zero(sub.get("gamma_flip"))
    net_gex = _null_if_zero(sub.get("net_gex"))
    ivr = _null_if_zero(sub.get("ivr"))
    ivp = _null_if_zero(sub.get("ivp"))
    vrp = _null_if_zero(sub.get("vrp"))
    or_high = _null_if_zero(sub.get("or_high"))
    or_low = _null_if_zero(sub.get("or_low"))
    vwap = _null_if_zero(sub.get("vwap"))

    pcr = signal.pcr if signal.pcr != 0.0 else None
    max_pain = signal.max_pain if signal.max_pain != 0.0 else None
    call_wall = signal.call_wall if signal.call_wall != 0.0 else None
    put_wall = signal.put_wall if signal.put_wall != 0.0 else None
    pin_score = signal.pin_score if signal.pin_score != 0.0 else None

    new_score = float(score_result["score"])
    new_raw = float(score_result.get("raw_score", new_score))

    try:
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            # Look for an open row with the same setup key
            existing = conn.execute(
                "SELECT candidate_id, score, raw_score, occurrences FROM candidates "
                "WHERE setup_key = ? AND setup_closed_at IS NULL",
                (setup_key,),
            ).fetchone()

            if existing is not None:
                # Same setup, same regime — update in place
                ex_id, ex_score, ex_raw_score, ex_occ = existing
                peak_score = max(new_score, ex_score or 0.0)
                peak_raw = max(new_raw, ex_raw_score or 0.0)
                new_occ = (ex_occ or 0) + 1
                dispatched_update = 1 if dispatched else None  # only set True, never clear

                if dispatched_update:
                    conn.execute(
                        """UPDATE candidates
                           SET last_seen = ?, occurrences = ?, score = ?, raw_score = ?,
                               dispatched = 1, skip_reason = COALESCE(skip_reason, ?)
                           WHERE candidate_id = ?""",
                        (ts, new_occ, peak_score, peak_raw, skip_reason, ex_id),
                    )
                else:
                    conn.execute(
                        """UPDATE candidates
                           SET last_seen = ?, occurrences = ?, score = ?, raw_score = ?
                           WHERE candidate_id = ?""",
                        (ts, new_occ, peak_score, peak_raw, ex_id),
                    )
                conn.commit()
                logger.debug(
                    "candidate_logger: updated %s %s occ=%d score=%d",
                    signal.symbol, signal.playbook_id, new_occ, int(peak_score),
                )
                return ex_id
            else:
                # No open row for this exact key.
                # If there is an open row for (symbol, playbook_id, expiry) with a
                # different regime — that's a regime shift; close the old one first.
                conn.execute(
                    """UPDATE candidates
                       SET setup_closed_at = ?
                       WHERE symbol = ? AND playbook_id = ? AND expiry = ?
                         AND setup_closed_at IS NULL AND setup_key != ?""",
                    (ts, signal.symbol, signal.playbook_id, signal.expiry, setup_key),
                )

                candidate_id = str(uuid.uuid4())
                row = (
                    candidate_id,
                    ts,
                    signal.symbol,
                    signal.expiry,
                    signal.playbook_id,
                    score_result["tier"],
                    new_score,
                    new_raw,
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
                    setup_key,
                    ts,   # first_seen
                    ts,   # last_seen
                    1,    # occurrences
                )

                conn.execute(
                    """
                    INSERT INTO candidates (
                        candidate_id, ts_signal, symbol, expiry, playbook_id,
                        tier, score, raw_score, score_breakdown,
                        vol_regime, vol_provisional,
                        direction_label, direction_score,
                        spot, vwap, pcr, max_pain, call_wall, put_wall,
                        gamma_flip, net_gex, pin_score,
                        ivr, ivp, vrp, or_high, or_low,
                        dispatched, skip_reason,
                        setup_key, first_seen, last_seen, occurrences
                    ) VALUES (
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    row,
                )
                conn.commit()
                logger.debug(
                    "candidate_logger: inserted %s %s tier=%d score=%d",
                    signal.symbol, signal.playbook_id,
                    score_result["tier"], int(new_score),
                )
                return candidate_id
        finally:
            conn.close()
    except Exception as exc:
        logger.error("candidate_logger: upsert failed for %s — %s", signal.symbol, exc)
        return ""


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
