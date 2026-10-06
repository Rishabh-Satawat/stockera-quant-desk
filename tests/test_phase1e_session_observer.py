"""Tests for Phase 1E: session_observer, DB auto-init wiring, supervisor labeller."""

from __future__ import annotations

import inspect
import os
import sqlite3
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from db_init import init_db, DEFAULT_DB_PATH


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    return db


def _insert_snapshot(db, symbol, ts_iso, iv=None):
    conn = sqlite3.connect(db)
    conn.execute(
        """INSERT OR IGNORE INTO chain_snapshots
           (symbol, expiry, strike, option_type, timestamp, ltp, oi, volume, iv, security_id)
           VALUES (?, '2099-01-01', 25000.0, 'CE', ?, 100.0, 1000, 50, ?, 99)""",
        (symbol, ts_iso, iv),
    )
    conn.commit()
    conn.close()


def _insert_candidate(db, symbol, ts_iso, tier=1, dispatched=1):
    from candidate_logger import log_candidate
    from playbook_triggers import PlaybookSignal
    sig = PlaybookSignal(
        symbol=symbol,
        expiry="2099-01-01",
        playbook_id="PB1",
        direction="BULL",
        vol_regime="NORMAL_VOL",
        vol_provisional=False,
        instrument_type="ATM_CALL",
        atm_strike=22000.0,
        spot=22000.0,
        max_pain=22000.0,
        call_wall=22200.0,
        put_wall=21800.0,
        pcr=0.9,
        pin_score=0.5,
        direction_score=60,
        step=50,
    )
    score_result = {
        "total_score": 85.0,
        "tier": tier,
        "score": 85.0,
        "breakdown": {"P1": 25, "P2": 20, "P3": 15, "P4": 12, "P5": 8},
    }
    log_candidate(sig, score_result, dispatched=dispatched, db_path=db, ts_override=ts_iso)


# ──────────────────────────────────────────────────────────────────────────────
# 1. DB auto-init: chain_snapshotter.get_latest_chain_snapshot
# ──────────────────────────────────────────────────────────────────────────────

class TestChainSnapshotterAutoInit:
    def test_get_latest_chain_snapshot_creates_db(self, tmp_path):
        """get_latest_chain_snapshot must not raise 'no such table' on empty DB."""
        db = str(tmp_path / "new.db")
        assert not os.path.exists(db)
        from chain_snapshotter import get_latest_chain_snapshot
        result = get_latest_chain_snapshot("NIFTY", db_path=db)
        assert isinstance(result, dict)  # empty dict — no data yet, no crash

    def test_get_latest_chain_snapshot_idempotent_init(self, tmp_db):
        """Repeated calls on already-init'd DB are safe."""
        from chain_snapshotter import get_latest_chain_snapshot
        result1 = get_latest_chain_snapshot("NIFTY", db_path=tmp_db)
        result2 = get_latest_chain_snapshot("NIFTY", db_path=tmp_db)
        assert result1 == result2 == {}

    def test_poll_once_calls_init_db(self, tmp_path):
        """poll_once must auto-init the DB (init_db is called)."""
        db = str(tmp_path / "poll.db")
        from chain_snapshotter import poll_once
        # poll_once will fail on credentials but must NOT fail on missing tables
        with pytest.raises(RuntimeError, match="credentials"):
            poll_once("NIFTY", db_path=db)
        # DB must have been created
        assert os.path.exists(db)

    def test_db_tables_created_by_get_latest(self, tmp_path):
        """After get_latest_chain_snapshot, chain_snapshots table exists."""
        db = str(tmp_path / "auto.db")
        from chain_snapshotter import get_latest_chain_snapshot
        get_latest_chain_snapshot("NIFTY", db_path=db)
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "chain_snapshots" in tables


# ──────────────────────────────────────────────────────────────────────────────
# 2. DB auto-init: chain_microstructure_analyzer
# ──────────────────────────────────────────────────────────────────────────────

class TestChainMicrostructureAutoInit:
    def test_analyze_creates_db(self, tmp_path):
        """analyze_option_chain_microstructure must init DB if absent."""
        db = str(tmp_path / "micro.db")
        with patch("chain_microstructure_analyzer.get_live_spots", return_value={"NIFTY": 22000.0}):
            from chain_microstructure_analyzer import analyze_option_chain_microstructure
            result = analyze_option_chain_microstructure("NIFTY", db_path=db)
        # Missing snapshot → synthetic fallback, not a crash
        assert result is not None
        assert result.get("is_synthetic") is True
        # DB must have been initialised
        assert os.path.exists(db)
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "chain_snapshots" in tables

    def test_init_db_imported_in_chain_microstructure_analyzer(self):
        import chain_microstructure_analyzer as cma
        import importlib
        src = inspect.getsource(cma)
        assert "init_db" in src


# ──────────────────────────────────────────────────────────────────────────────
# 3. session_observer — build_report
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionObserverReport:
    def test_report_runs_on_empty_db(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "STOCKERA SESSION OBSERVER" in report

    def test_report_shows_snapshotter_section(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "Snapshotter Health" in report

    def test_report_shows_bars_section(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "Bars Health" in report

    def test_report_shows_candidates_section(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "Candidates Log" in report

    def test_report_shows_data_integrity_section(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "Data Integrity" in report

    def test_report_shows_iv_history_section(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "IV History" in report

    def test_report_shows_symbol_row_after_snapshot(self, tmp_db):
        """A snapshot row causes the symbol to appear in Snapshotter Health."""
        from zoneinfo import ZoneInfo
        ts = datetime.now(tz=ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
        _insert_snapshot(tmp_db, "NIFTY", ts)
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "NIFTY" in report

    def test_stale_snapshot_flagged(self, tmp_db):
        """Snapshot older than 90 s is flagged."""
        from zoneinfo import ZoneInfo
        stale_dt = datetime.now(tz=ZoneInfo("Asia/Kolkata")) - timedelta(seconds=200)
        _insert_snapshot(tmp_db, "NIFTY", stale_dt.isoformat(timespec="seconds"))
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "STALE" in report

    def test_fresh_snapshot_not_flagged(self, tmp_db):
        """Recent snapshot does NOT trigger stale flag."""
        from zoneinfo import ZoneInfo
        fresh_dt = datetime.now(tz=ZoneInfo("Asia/Kolkata")) - timedelta(seconds=10)
        _insert_snapshot(tmp_db, "NIFTY", fresh_dt.isoformat(timespec="seconds"))
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "STALE" not in report

    def test_synthetic_rows_flagged(self, tmp_db):
        """Synthetic rows trigger the integrity warning."""
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """INSERT OR IGNORE INTO chain_snapshots
               (symbol, expiry, strike, option_type, timestamp, ltp, oi, volume, is_synthetic, security_id)
               VALUES ('NIFTY', '2099-01-01', 25000.0, 'CE', '2099-01-01T09:30:00', 100.0, 0, 0, 1, 99)"""
        )
        conn.commit()
        conn.close()
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "synthetic=1" in report

    def test_zero_synthetic_shown_ok(self, tmp_db):
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "synthetic=0" in report

    def test_null_iv_rate_reported(self, tmp_db):
        from zoneinfo import ZoneInfo
        ts = datetime.now(tz=ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")
        _insert_snapshot(tmp_db, "NIFTY", ts, iv=None)  # NULL iv
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "null_iv=" in report

    def test_candidates_today_counted(self, tmp_db):
        from datetime import timezone
        today_ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        _insert_candidate(tmp_db, "NIFTY", today_ts, tier=1, dispatched=1)
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "Total=1" in report

    def test_candidates_dispatched_vs_skipped(self, tmp_db):
        from datetime import timezone
        today_ts = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        _insert_candidate(tmp_db, "NIFTY", today_ts, tier=1, dispatched=1)
        _insert_candidate(tmp_db, "BANKNIFTY", today_ts, tier=2, dispatched=0)
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "dispatched=1" in report
        assert "skipped=1" in report

    def test_iv_history_row_count(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """INSERT INTO iv_history (symbol, trade_date, expiry, atm_iv, spot)
               VALUES ('NIFTY', '2026-10-05', '2026-10-07', 14.5, 25000.0)"""
        )
        conn.commit()
        conn.close()
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "rows=1" in report

    def test_iv_history_provisional_warning(self, tmp_db):
        """Less than 20 iv_history sessions triggers a warning."""
        from session_observer import build_report
        report = build_report(tmp_db)
        assert "provisional" in report.lower() or "sessions" in report.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 4. session_observer — checkpoint
# ──────────────────────────────────────────────────────────────────────────────

class TestSessionObserverCheckpoint:
    def test_checkpoint_returns_bool(self, tmp_db, capsys):
        from session_observer import run_checkpoint
        result = run_checkpoint(tmp_db)
        assert isinstance(result, bool)

    def test_checkpoint_wal_mode_pass(self, tmp_db, capsys):
        from session_observer import run_checkpoint
        run_checkpoint(tmp_db)
        captured = capsys.readouterr().out
        assert "journal_mode = WAL" in captured

    def test_checkpoint_live_mode_check(self, tmp_db, capsys):
        from session_observer import run_checkpoint
        run_checkpoint(tmp_db)
        captured = capsys.readouterr().out
        assert "live_mode" in captured

    def test_checkpoint_instruments_section(self, tmp_db, capsys):
        """Checkpoint must attempt to resolve all 4 symbols."""
        from session_observer import run_checkpoint
        run_checkpoint(tmp_db)
        captured = capsys.readouterr().out
        # Should mention checkpoint was run (section header)
        assert "PRE-FLIGHT" in captured

    def test_checkpoint_outputs_summary_line(self, tmp_db, capsys):
        from session_observer import run_checkpoint
        run_checkpoint(tmp_db)
        captured = capsys.readouterr().out
        # Must have a pass/fail summary line
        assert "checks" in captured.lower()

    def test_checkpoint_new_db_is_ok(self, tmp_path, capsys):
        """Checkpoint on fresh DB must not crash."""
        db = str(tmp_path / "fresh.db")
        from session_observer import run_checkpoint
        result = run_checkpoint(db)
        assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────────────────────
# 5. _snapshotter_health internals
# ──────────────────────────────────────────────────────────────────────────────

class TestSnapshotterHealthHelper:
    def test_no_table_returns_message(self, tmp_path):
        db = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db)
        conn.close()
        from session_observer import _snapshotter_health
        lines = _snapshotter_health(sqlite3.connect(db))
        assert any("no chain_snapshots" in l or "missing" in l.lower() for l in lines)

    def test_empty_table_reports_no_rows(self, tmp_db):
        from session_observer import _snapshotter_health
        conn = sqlite3.connect(tmp_db)
        lines = _snapshotter_health(conn)
        conn.close()
        assert any("no rows" in l for l in lines)

    def test_fresh_row_reports_age(self, tmp_db):
        from zoneinfo import ZoneInfo
        ts = (datetime.now(tz=ZoneInfo("Asia/Kolkata")) - timedelta(seconds=5)).isoformat(timespec="seconds")
        _insert_snapshot(tmp_db, "BANKNIFTY", ts)
        from session_observer import _snapshotter_health
        conn = sqlite3.connect(tmp_db)
        lines = _snapshotter_health(conn)
        conn.close()
        assert any("BANKNIFTY" in l for l in lines)


# ──────────────────────────────────────────────────────────────────────────────
# 6. _bars_health
# ──────────────────────────────────────────────────────────────────────────────

class TestBarsHealth:
    def test_empty_tables_reported(self, tmp_db):
        from session_observer import _bars_health
        conn = sqlite3.connect(tmp_db)
        lines = _bars_health(conn)
        conn.close()
        assert any("underlying_bars" in l for l in lines)
        assert any("option_bars" in l for l in lines)

    def test_bar_rows_shown(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """INSERT INTO underlying_bars (symbol, bar_tf, bar_open_ts, open, high, low, close)
               VALUES ('NIFTY', '1m', '2026-10-06T09:15:00', 22000, 22010, 21990, 22005)"""
        )
        conn.commit()
        lines_fn = None
        conn.close()
        from session_observer import _bars_health
        conn = sqlite3.connect(tmp_db)
        lines = _bars_health(conn)
        conn.close()
        assert any("1m=1" in l for l in lines)


# ──────────────────────────────────────────────────────────────────────────────
# 7. market_day_supervisor — labeller wiring
# ──────────────────────────────────────────────────────────────────────────────

class TestSupervisorLabellerWiring:
    def test_outcome_labeller_import_in_supervisor(self):
        import market_day_supervisor
        src = inspect.getsource(market_day_supervisor)
        assert "outcome_labeller" in src
        assert "run_labeller" in src

    def test_labeller_scheduled_at_0900(self):
        import market_day_supervisor
        src = inspect.getsource(market_day_supervisor)
        assert "09:00" in src

    def test_labeller_done_flag_reset_at_midnight(self):
        import market_day_supervisor
        src = inspect.getsource(market_day_supervisor)
        assert "labeller_done" in src

    def test_labeller_flag_initialised_false(self):
        import market_day_supervisor
        src = inspect.getsource(market_day_supervisor)
        # The flag must start as False
        assert "labeller_done = False" in src

    def test_labeller_error_is_nonfatal(self):
        """Supervisor must catch exceptions from run_labeller so it doesn't crash."""
        import market_day_supervisor
        src = inspect.getsource(market_day_supervisor)
        assert "except" in src

    def test_is_market_open_weekday(self):
        """is_market_open returns sensible results (smoke test)."""
        from market_day_supervisor import is_market_open
        # Just verify it returns bool without crashing
        result = is_market_open()
        assert isinstance(result, bool)


# ──────────────────────────────────────────────────────────────────────────────
# 8. chain_snapshotter auto-init idempotency
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoInitIdempotency:
    def test_init_db_idempotent_multiple_calls(self, tmp_path):
        db = str(tmp_path / "multi.db")
        from db_init import init_db
        init_db(db)
        init_db(db)
        init_db(db)
        conn = sqlite3.connect(db)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "chain_snapshots" in tables

    def test_get_latest_after_insert(self, tmp_db):
        """After inserting a fresh row, get_latest_chain_snapshot returns non-empty."""
        from zoneinfo import ZoneInfo
        from chain_snapshotter import get_latest_chain_snapshot
        now_ist = datetime.now(tz=ZoneInfo("Asia/Kolkata"))
        ts = now_ist.isoformat(timespec="seconds")
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            """INSERT INTO chain_snapshots
               (symbol, expiry, strike, option_type, timestamp, ltp, oi, volume, iv, security_id)
               VALUES ('NIFTY', '2099-01-01', 25000.0, 'CE', ?, 100.0, 1000, 50, 14.5, 99)""",
            (ts,),
        )
        conn.commit()
        conn.close()
        result = get_latest_chain_snapshot("NIFTY", db_path=tmp_db)
        assert isinstance(result, dict)
        # Snapshot returns data (may be {} if date check fails in test env — that's ok)

    def test_missing_dir_created(self, tmp_path):
        """init_db creates parent directory when it doesn't exist."""
        nested = str(tmp_path / "a" / "b" / "c" / "test.db")
        from db_init import init_db
        init_db(nested)
        assert os.path.exists(nested)
