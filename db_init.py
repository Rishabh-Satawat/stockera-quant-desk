"""Database initialisation for Phase 1A time-series store.

Creates chain_snapshots, underlying_bars, and option_bars tables in WAL mode.
Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = str(Path(__file__).parent / "data" / "chain_timeseries.db")

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS chain_snapshots (
    symbol       TEXT    NOT NULL,
    expiry       TEXT    NOT NULL,
    strike       REAL    NOT NULL,
    option_type  TEXT    NOT NULL,
    timestamp    TEXT    NOT NULL,
    ltp          REAL    NOT NULL,
    oi           INTEGER NOT NULL DEFAULT 0,
    volume       INTEGER NOT NULL DEFAULT 0,
    iv           REAL,
    delta        REAL,
    theta        REAL,
    gamma        REAL,
    vega         REAL,
    security_id  INTEGER NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, expiry, strike, option_type, timestamp)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON chain_snapshots (symbol, expiry, option_type, timestamp);

CREATE TABLE IF NOT EXISTS underlying_bars (
    symbol      TEXT    NOT NULL,
    bar_tf      TEXT    NOT NULL,
    bar_open_ts TEXT    NOT NULL,
    open        REAL    NOT NULL,
    high        REAL    NOT NULL,
    low         REAL    NOT NULL,
    close       REAL    NOT NULL,
    volume      INTEGER NOT NULL DEFAULT 0,
    is_gap_fill INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, bar_tf, bar_open_ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_ubars_lookup
    ON underlying_bars (symbol, bar_tf, bar_open_ts);

CREATE TABLE IF NOT EXISTS option_bars (
    symbol       TEXT    NOT NULL,
    expiry       TEXT    NOT NULL,
    strike       REAL    NOT NULL,
    option_type  TEXT    NOT NULL,
    bar_tf       TEXT    NOT NULL,
    bar_open_ts  TEXT    NOT NULL,
    open         REAL    NOT NULL,
    high         REAL    NOT NULL,
    low          REAL    NOT NULL,
    close        REAL    NOT NULL,
    volume       INTEGER NOT NULL DEFAULT 0,
    is_gap_fill  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, expiry, strike, option_type, bar_tf, bar_open_ts)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_obars_lookup
    ON option_bars (symbol, expiry, option_type, bar_tf, bar_open_ts);

CREATE TABLE IF NOT EXISTS iv_history (
    symbol       TEXT NOT NULL,
    trade_date   TEXT NOT NULL,   -- ISO date YYYY-MM-DD IST
    expiry       TEXT NOT NULL,
    atm_iv       REAL,
    iv_25d_put   REAL,
    iv_25d_call  REAL,
    spot         REAL,
    source       TEXT DEFAULT 'EOD_SNAPSHOT',
    PRIMARY KEY (symbol, trade_date)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_iv_history_lookup
    ON iv_history (symbol, trade_date);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id      TEXT PRIMARY KEY,
    ts_signal         TEXT NOT NULL,        -- ISO-8601 UTC timestamp of signal
    symbol            TEXT NOT NULL,
    expiry            TEXT NOT NULL,
    playbook_id       TEXT NOT NULL,
    tier              INTEGER NOT NULL,     -- 1, 2, or 0
    score             REAL NOT NULL,
    score_breakdown   JSON NOT NULL,
    vol_regime        TEXT NOT NULL,
    vol_provisional   INTEGER NOT NULL,     -- 0 or 1
    direction_label   TEXT NOT NULL,
    direction_score   INTEGER NOT NULL,
    spot              REAL NOT NULL,
    vwap              REAL,
    pcr               REAL,
    max_pain          REAL,
    call_wall         REAL,
    put_wall          REAL,
    gamma_flip        REAL,
    net_gex           REAL,
    pin_score         REAL,
    ivr               REAL,
    ivp               REAL,
    vrp               REAL,
    or_high           REAL,
    or_low            REAL,
    dispatched        INTEGER NOT NULL,     -- 1 if trade was sent to broker, 0 otherwise
    skip_reason       TEXT,
    -- outcome fields populated by outcome_labeller.py (after the session)
    outcome_label     TEXT,                 -- WINNER / LOSER / EXPIRED / NULL
    pnl_points        REAL,
    option_pnl_pct    REAL,
    mae_points        REAL,
    labelled_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_ts
    ON candidates (ts_signal);

CREATE INDEX IF NOT EXISTS idx_candidates_symbol
    ON candidates (symbol, playbook_id);
"""


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


if __name__ == "__main__":
    init_db()
    print(f"DB initialised at {DEFAULT_DB_PATH}")
