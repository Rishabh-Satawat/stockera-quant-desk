"""Bar builder: aggregates chain_snapshots into 1m/5m/15m OHLCV bars.

Volume handling:
  Dhan `volume` is the cumulative day total. True bar volume is the delta:
    bar_volume = max(0, last_cumvol_in_bar - last_cumvol_in_prior_bar)
  Day-boundary reset at 09:15 IST: the first bar of the session has no
  prior bar, so bar_volume = last_cumvol_in_bar (treated as volume from open).

Gap filling:
  If a bar window has no snapshots, the prior close is propagated as
  O/H/L/C with volume=0 and is_gap_fill=1.
"""

import datetime
import sqlite3
from zoneinfo import ZoneInfo
from typing import Optional

from db_init import get_connection, DEFAULT_DB_PATH

_IST = ZoneInfo("Asia/Kolkata")
_SESSION_OPEN_HOUR = 9
_SESSION_OPEN_MINUTE = 15

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15}


def _floor_to_bar(ts: datetime.datetime, tf_minutes: int) -> datetime.datetime:
    """Round down to the nearest bar boundary."""
    total_minutes = ts.hour * 60 + ts.minute
    bar_start_minutes = (total_minutes // tf_minutes) * tf_minutes
    return ts.replace(
        hour=bar_start_minutes // 60,
        minute=bar_start_minutes % 60,
        second=0,
        microsecond=0,
    )


def _session_open(date: datetime.date) -> datetime.datetime:
    return datetime.datetime(
        date.year, date.month, date.day,
        _SESSION_OPEN_HOUR, _SESSION_OPEN_MINUTE, 0,
        tzinfo=_IST,
    )


def build_option_bars(
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
    tf: str,
    db_path: str = DEFAULT_DB_PATH,
    since: Optional[datetime.datetime] = None,
) -> int:
    """Build/update option_bars for one (symbol, expiry, strike, option_type, tf).

    Returns the number of bar rows upserted.
    """
    if tf not in _TF_MINUTES:
        raise ValueError(f"Unsupported tf {tf!r}, must be one of {list(_TF_MINUTES)}")
    tf_min = _TF_MINUTES[tf]

    conn = get_connection(db_path)
    try:
        since_clause = ""
        params: list = [symbol, expiry, strike, option_type]
        if since:
            since_clause = "AND timestamp >= ?"
            params.append(since.isoformat())

        rows = conn.execute(
            f"""SELECT timestamp, ltp, volume
                FROM chain_snapshots
                WHERE symbol=? AND expiry=? AND strike=? AND option_type=?
                {since_clause}
                ORDER BY timestamp ASC""",
            params,
        ).fetchall()

        if not rows:
            return 0

        return _aggregate_and_upsert_option_bars(
            conn, rows, symbol, expiry, strike, option_type, tf, tf_min
        )
    finally:
        conn.close()


def build_underlying_bars(
    symbol: str,
    tf: str,
    db_path: str = DEFAULT_DB_PATH,
    since: Optional[datetime.datetime] = None,
) -> int:
    """Build/update underlying_bars from chain_snapshots spot (ltp of ATM CE+PE avg).

    In Phase 1A the underlying spot is not stored in chain_snapshots directly —
    that table stores option legs. This function aggregates the ATM CE delta-based
    proxy or is called by the snapshotter with spot rows once underlying_spots table
    exists. For now it processes any available spot data keyed by option_type='SPOT'
    if present, or skips gracefully.

    Returns rows upserted.
    """
    if tf not in _TF_MINUTES:
        raise ValueError(f"Unsupported tf {tf!r}")
    tf_min = _TF_MINUTES[tf]

    conn = get_connection(db_path)
    try:
        since_clause = ""
        params: list = [symbol, "SPOT"]
        if since:
            since_clause = "AND timestamp >= ?"
            params.append(since.isoformat())

        rows = conn.execute(
            f"""SELECT timestamp, ltp, volume
                FROM chain_snapshots
                WHERE symbol=? AND option_type=?
                {since_clause}
                ORDER BY timestamp ASC""",
            params,
        ).fetchall()

        if not rows:
            return 0

        return _aggregate_and_upsert_underlying_bars(conn, rows, symbol, tf, tf_min)
    finally:
        conn.close()


def _parse_ist(ts_str: str) -> datetime.datetime:
    dt = datetime.datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_IST)
    return dt


def _aggregate_and_upsert_option_bars(
    conn: sqlite3.Connection,
    rows: list,
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
    tf: str,
    tf_min: int,
) -> int:
    # Group snapshots by bar window
    bar_map: dict[datetime.datetime, list] = {}
    for ts_str, ltp, volume in rows:
        dt = _parse_ist(ts_str)
        bar_start = _floor_to_bar(dt, tf_min)
        bar_map.setdefault(bar_start, []).append((dt, float(ltp), int(volume or 0)))

    if not bar_map:
        return 0

    sorted_bars = sorted(bar_map.keys())

    # Resolve prior bar cumulative volume for delta calculation
    # First, get the last snapshot's volume from the prior bar in DB if it exists
    prior_cumvol = _get_prior_bar_last_cumvol(
        conn, symbol, expiry, strike, option_type, tf, sorted_bars[0]
    )

    upserted = 0
    last_close: Optional[float] = None
    last_bar_close_cumvol = prior_cumvol

    # Also fill gaps between existing bars
    prev_bar_start: Optional[datetime.datetime] = None

    for bar_start in sorted_bars:
        snaps = bar_map[bar_start]
        snaps_sorted = sorted(snaps, key=lambda x: x[0])

        first_ltp = snaps_sorted[0][1]
        last_ltp = snaps_sorted[-1][1]
        last_cumvol = snaps_sorted[-1][2]

        bar_open = first_ltp
        bar_close = last_ltp
        bar_high = max(s[1] for s in snaps_sorted)
        bar_low = min(s[1] for s in snaps_sorted)

        # Delta volume; reset at session open
        day = bar_start.date()
        sess_open = _session_open(day)
        if bar_start <= sess_open or last_bar_close_cumvol is None:
            # First bar of session — entire cumvol is the bar's volume
            bar_volume = max(0, last_cumvol)
        else:
            bar_volume = max(0, last_cumvol - last_bar_close_cumvol)

        # Gap fill between prev bar and this one
        if prev_bar_start is not None and last_close is not None:
            gap_start = prev_bar_start + datetime.timedelta(minutes=tf_min)
            while gap_start < bar_start:
                _upsert_option_bar(
                    conn, symbol, expiry, strike, option_type, tf,
                    gap_start, last_close, last_close, last_close, last_close,
                    0, is_gap_fill=1,
                )
                gap_start += datetime.timedelta(minutes=tf_min)
                upserted += 1

        _upsert_option_bar(
            conn, symbol, expiry, strike, option_type, tf,
            bar_start, bar_open, bar_high, bar_low, bar_close,
            bar_volume, is_gap_fill=0,
        )
        upserted += 1

        prev_bar_start = bar_start
        last_close = bar_close
        last_bar_close_cumvol = last_cumvol

    conn.commit()
    return upserted


def _aggregate_and_upsert_underlying_bars(
    conn: sqlite3.Connection,
    rows: list,
    symbol: str,
    tf: str,
    tf_min: int,
) -> int:
    bar_map: dict[datetime.datetime, list] = {}
    for ts_str, ltp, volume in rows:
        dt = _parse_ist(ts_str)
        bar_start = _floor_to_bar(dt, tf_min)
        bar_map.setdefault(bar_start, []).append((dt, float(ltp), int(volume or 0)))

    if not bar_map:
        return 0

    sorted_bars = sorted(bar_map.keys())
    upserted = 0
    last_close: Optional[float] = None
    last_bar_close_cumvol: Optional[int] = None
    prev_bar_start: Optional[datetime.datetime] = None

    for bar_start in sorted_bars:
        snaps = sorted(bar_map[bar_start], key=lambda x: x[0])
        first_ltp = snaps[0][1]
        last_ltp = snaps[-1][1]
        last_cumvol = snaps[-1][2]

        bar_open = first_ltp
        bar_close = last_ltp
        bar_high = max(s[1] for s in snaps)
        bar_low = min(s[1] for s in snaps)

        day = bar_start.date()
        sess_open = _session_open(day)
        if bar_start <= sess_open or last_bar_close_cumvol is None:
            bar_volume = max(0, last_cumvol)
        else:
            bar_volume = max(0, last_cumvol - last_bar_close_cumvol)

        if prev_bar_start is not None and last_close is not None:
            gap_start = prev_bar_start + datetime.timedelta(minutes=tf_min)
            while gap_start < bar_start:
                _upsert_underlying_bar(
                    conn, symbol, tf, gap_start,
                    last_close, last_close, last_close, last_close,
                    0, is_gap_fill=1,
                )
                gap_start += datetime.timedelta(minutes=tf_min)
                upserted += 1

        _upsert_underlying_bar(
            conn, symbol, tf, bar_start,
            bar_open, bar_high, bar_low, bar_close,
            bar_volume, is_gap_fill=0,
        )
        upserted += 1

        prev_bar_start = bar_start
        last_close = bar_close
        last_bar_close_cumvol = last_cumvol

    conn.commit()
    return upserted


def _get_prior_bar_last_cumvol(
    conn: sqlite3.Connection,
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
    tf: str,
    first_bar_start: datetime.datetime,
) -> Optional[int]:
    """Get the cumulative volume of the last snapshot in the bar before first_bar_start."""
    row = conn.execute(
        """SELECT volume FROM chain_snapshots
           WHERE symbol=? AND expiry=? AND strike=? AND option_type=?
             AND timestamp < ?
           ORDER BY timestamp DESC LIMIT 1""",
        (symbol, expiry, strike, option_type, first_bar_start.isoformat()),
    ).fetchone()
    return int(row[0]) if row else None


def _upsert_option_bar(
    conn, symbol, expiry, strike, option_type, tf,
    bar_start, open_, high, low, close, volume, is_gap_fill
):
    conn.execute(
        """INSERT OR REPLACE INTO option_bars
           (symbol, expiry, strike, option_type, bar_tf, bar_open_ts,
            open, high, low, close, volume, is_gap_fill)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol, expiry, strike, option_type, tf,
         bar_start.isoformat(), open_, high, low, close, volume, is_gap_fill),
    )


def _upsert_underlying_bar(
    conn, symbol, tf, bar_start,
    open_, high, low, close, volume, is_gap_fill
):
    conn.execute(
        """INSERT OR REPLACE INTO underlying_bars
           (symbol, bar_tf, bar_open_ts, open, high, low, close, volume, is_gap_fill)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (symbol, tf, bar_start.isoformat(), open_, high, low, close, volume, is_gap_fill),
    )


def build_bars(
    db_path: str = DEFAULT_DB_PATH,
    symbols: Optional[list] = None,
) -> dict:
    """Aggregate all recent chain_snapshots into 1m/5m/15m OHLCV bars.

    Builds both underlying_bars (from option_type='SPOT' rows written by the
    snapshotter) and option_bars (from CE/PE rows) for every distinct
    (symbol, expiry, strike, option_type) combination present in the DB.

    Returns a summary dict: {symbol: {"underlying": n, "option": n}}.
    This is the entry point called by chain_snapshotter after each full cycle.
    """
    if symbols is None:
        symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

    summary: dict = {}
    for sym in symbols:
        u_total = 0
        for tf in ("1m", "5m", "15m"):
            u_total += build_underlying_bars(sym, tf, db_path)

        # Discover all distinct (expiry, strike, option_type) combos with
        # recent snapshots so we can build option bars for each.
        conn = get_connection(db_path)
        try:
            combos = conn.execute(
                """SELECT DISTINCT expiry, strike, option_type
                   FROM chain_snapshots
                   WHERE symbol=? AND option_type != 'SPOT'""",
                (sym,),
            ).fetchall()
        finally:
            conn.close()

        o_total = 0
        for expiry, strike, opt_type in combos:
            for tf in ("1m", "5m", "15m"):
                o_total += build_option_bars(sym, expiry, strike, opt_type, tf, db_path)

        summary[sym] = {"underlying": u_total, "option": o_total}

    return summary


def get_option_bars(
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,
    tf: str,
    db_path: str = DEFAULT_DB_PATH,
    n: int = 20,
) -> list[dict]:
    """Return the n most recent completed option bars, newest last."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT bar_open_ts, open, high, low, close, volume, is_gap_fill
               FROM option_bars
               WHERE symbol=? AND expiry=? AND strike=? AND option_type=? AND bar_tf=?
               ORDER BY bar_open_ts DESC LIMIT ?""",
            (symbol, expiry, strike, option_type, tf, n),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "bar_open_ts": r[0], "open": r[1], "high": r[2],
            "low": r[3], "close": r[4], "volume": r[5], "is_gap_fill": bool(r[6]),
        }
        for r in reversed(rows)
    ]
