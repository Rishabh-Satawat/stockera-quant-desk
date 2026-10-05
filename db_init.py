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
