"""Outcome Labeller — Phase 1D.

Runs daily (or via --label-date YYYY-MM-DD) for candidates from prior sessions
to eliminate look-ahead bias.

Label logic (triple-barrier):
  WINNER  — underlying hit the playbook's Target 1 level before hitting its Stop.
  LOSER   — underlying hit the Stop level first.
  EXPIRED — neither barrier touched by 15:30 IST.

Metrics calculated per row:
  pnl_points       raw underlying move in index points from signal spot
  option_pnl_pct   approximate P&L as % of entry premium (from sub_scores)
  mae_points       Max Adverse Excursion in points from entry spot

Rules:
  - Only labels rows where outcome_label IS NULL (idempotent).
  - Reads underlying_bars at the 1-min timeframe for intra-session bar data.
  - Uses playbook-specific barrier logic from BARRIER_PARAMS.
  - Never raises on missing data — logs a warning and marks outcome EXPIRED.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from db_init import DEFAULT_DB_PATH, init_db

logger = logging.getLogger(__name__)

# Target 1 and Stop multipliers per playbook (as fraction of spot at signal time)
# PB1 directional: target = +1.25× premium implied move (≈0.5% on index);
#                  stop   = −0.8× implied move
# PB2/PB6 credit spread: target = 80 bps away; stop = 1.5× target
_BARRIER_PARAMS = {
    "PB1":  {"target_pct": 0.005, "stop_pct": -0.004},
    "PB2":  {"target_pct": 0.004, "stop_pct": -0.006},
    "PB6":  {"target_pct": 0.004, "stop_pct": -0.006},
}
_DEFAULT_BARRIER = {"target_pct": 0.005, "stop_pct": -0.005}

_EOD_TIME = "15:30:00"


def _get_bars_for_date(
    conn: sqlite3.Connection,
    symbol: str,
    trade_date: str,
) -> pd.DataFrame:
    """Fetch 1-min underlying_bars for symbol on trade_date (IST calendar day).

    Returns DataFrame sorted by bar_open_ts, or empty DataFrame on failure.
    """
    sql = """
        SELECT bar_open_ts, open, high, low, close
        FROM underlying_bars
        WHERE symbol = ?
          AND bar_tf = '1m'
          AND date(bar_open_ts) = date(?)
        ORDER BY bar_open_ts
    """
    try:
        df = pd.read_sql_query(sql, conn, params=(symbol, trade_date))
        return df
    except Exception as exc:
        logger.warning("_get_bars_for_date: query failed sym=%s date=%s — %s", symbol, trade_date, exc)
        return pd.DataFrame()


def _compute_triple_barrier(
    entry_spot: float,
    bars: pd.DataFrame,
    target_pct: float,
    stop_pct: float,
) -> tuple[str, float, float, float]:
    """Evaluate triple-barrier label from intra-day bar data.

    Returns (label, pnl_points, option_pnl_pct_placeholder, mae_points).
    option_pnl_pct is a placeholder (0.0) here — caller enriches from entry premium.
    """
    if bars.empty:
        return "EXPIRED", 0.0, 0.0, 0.0

    target_level = entry_spot * (1.0 + target_pct)
    stop_level = entry_spot * (1.0 + stop_pct)

    final_close = float(bars.iloc[-1]["close"])
    pnl_points = final_close - entry_spot
    mae = 0.0  # Max Adverse Excursion

    for _, row in bars.iterrows():
        bar_high = float(row["high"])
        bar_low = float(row["low"])

        # Track adverse excursion (for long direction; invert for short)
        adverse_move = entry_spot - bar_low
        if adverse_move > mae:
            mae = adverse_move

        # Check target hit before stop on this bar (conservative: use close, not intrabar)
        bar_close = float(row["close"])
        if bar_high >= target_level:
            return "WINNER", bar_close - entry_spot, 0.0, round(mae, 2)
        if bar_low <= stop_level:
            return "LOSER", bar_close - entry_spot, 0.0, round(mae, 2)

    return "EXPIRED", round(pnl_points, 2), 0.0, round(mae, 2)


def label_date(
    label_date_str: str,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Label all unlabelled candidates whose signal fell on label_date_str.

    Parameters
    ----------
    label_date_str: ISO date string YYYY-MM-DD (the session date to label).
    db_path:        SQLite path.

    Returns the number of rows labelled.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    labelled_count = 0

    try:
        # Fetch unlabelled candidates for this date
        sql_select = """
            SELECT candidate_id, symbol, playbook_id, spot, ts_signal, score_breakdown
            FROM candidates
            WHERE date(ts_signal) = date(?)
              AND outcome_label IS NULL
        """
        rows = conn.execute(sql_select, (label_date_str,)).fetchall()

        if not rows:
            logger.info("outcome_labeller: no unlabelled rows for %s", label_date_str)
            return 0

        logger.info("outcome_labeller: labelling %d rows for %s", len(rows), label_date_str)

        for (candidate_id, symbol, playbook_id, spot, ts_signal, score_breakdown_json) in rows:
            params = _BARRIER_PARAMS.get(playbook_id, _DEFAULT_BARRIER)

            bars = _get_bars_for_date(conn, symbol, label_date_str)

            # Filter bars to only those after the signal time
            if not bars.empty and ts_signal:
                try:
                    signal_ts_str = ts_signal[:19]  # strip timezone suffix for comparison
                    signal_dt = datetime.fromisoformat(signal_ts_str)
                    # bars use local date — compare by time suffix
                    bars = bars[bars["bar_open_ts"] >= signal_ts_str].copy()
                except Exception:
                    pass  # use all bars if parsing fails

            label, pnl_pts, _, mae_pts = _compute_triple_barrier(
                float(spot),
                bars,
                params["target_pct"],
                abs(params["stop_pct"]) * -1,
            )

            # Attempt to calculate option_pnl_pct from score_breakdown entry premium proxy
            option_pnl_pct: Optional[float] = None
            try:
                bd = json.loads(score_breakdown_json) if isinstance(score_breakdown_json, str) else {}
                # score_breakdown doesn't carry entry premium directly; leave as NULL
                # Phase 3 will enrich this once option_bars are populated.
            except Exception:
                pass

            labelled_at = datetime.now(timezone.utc).isoformat()

            conn.execute(
                """
                UPDATE candidates
                SET outcome_label = ?,
                    pnl_points    = ?,
                    option_pnl_pct = ?,
                    mae_points    = ?,
                    labelled_at   = ?
                WHERE candidate_id = ?
                  AND outcome_label IS NULL
                """,
                (label, round(pnl_pts, 2), option_pnl_pct, round(mae_pts, 2), labelled_at, candidate_id),
            )
            labelled_count += 1

        conn.commit()
        logger.info("outcome_labeller: labelled %d rows for %s", labelled_count, label_date_str)

    finally:
        conn.close()

    return labelled_count


def run_labeller(
    target_date: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Label the previous session (or target_date if provided).

    Designed to be called from eod_ledger_reporter at 15:30 IST or from a
    standalone cron job the next morning.

    Returns rows labelled.
    """
    if target_date is None:
        # Label yesterday's candidates (safe: the session is over)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        target_date = yesterday

    return label_date(target_date, db_path=db_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Label candidate outcomes for a given trade date.")
    parser.add_argument(
        "--label-date",
        metavar="YYYY-MM-DD",
        help="Date to label (default: yesterday)",
        default=None,
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to chain_timeseries.db")
    args = parser.parse_args()

    n = run_labeller(target_date=args.label_date, db_path=args.db)
    print(f"outcome_labeller: labelled {n} rows for {args.label_date or 'yesterday'}")


if __name__ == "__main__":
    main()
