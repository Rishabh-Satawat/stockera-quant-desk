"""Phase 1A time-series engine — unit tests.

All tests run without live Dhan credentials; broker calls are mocked.
"""

import datetime
import math
import sqlite3
import tempfile
import threading
import time
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from iv_solver import solve_iv, black76_price
from db_init import init_db, get_connection
from bar_builder import (
    build_option_bars,
    get_option_bars,
    _floor_to_bar,
    _session_open,
)
from expiry_calendar import get_dte_minutes

_IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return f.name


def _insert_snapshot(conn, symbol, expiry, strike, opt_type, ts_ist, ltp, volume,
                     iv=None, security_id=40697, is_synthetic=0, oi=0,
                     delta=None, theta=None, gamma=None, vega=None):
    conn.execute(
        """INSERT OR REPLACE INTO chain_snapshots
           (symbol, expiry, strike, option_type, timestamp,
            ltp, oi, volume, iv, delta, theta, gamma, vega,
            security_id, is_synthetic)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol, expiry, str(strike), opt_type, ts_ist, ltp, oi, volume,
         iv, delta, theta, gamma, vega, security_id, is_synthetic),
    )


# ---------------------------------------------------------------------------
# DB initialisation
# ---------------------------------------------------------------------------

class TestDBInit:
    def test_wal_mode(self):
        db = _tmp_db()
        try:
            init_db(db)
            conn = sqlite3.connect(db)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
            assert mode == "wal"
        finally:
            os.unlink(db)

    def test_tables_exist(self):
        db = _tmp_db()
        try:
            init_db(db)
            conn = sqlite3.connect(db)
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            conn.close()
            assert "chain_snapshots" in tables
            assert "option_bars" in tables
            assert "underlying_bars" in tables
        finally:
            os.unlink(db)

    def test_idempotent(self):
        db = _tmp_db()
        try:
            init_db(db)
            init_db(db)  # second call must not raise
        finally:
            os.unlink(db)

    def test_iv_null_constraint(self):
        """iv column must accept NULL."""
        db = _tmp_db()
        try:
            init_db(db)
            conn = get_connection(db)
            _insert_snapshot(conn, "NIFTY", "2026-10-06", 22500, "CE",
                              "2026-10-06T09:16:00+05:30", 107.0, 1000, iv=None)
            conn.commit()
            row = conn.execute("SELECT iv FROM chain_snapshots WHERE symbol='NIFTY'").fetchone()
            conn.close()
            assert row[0] is None
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# IV Solver — Black-76
# ---------------------------------------------------------------------------

class TestIVSolver:
    """Round-trip and boundary tests for the Black-76 bisection solver."""

    _RATE = 0.065

    def _tte(self, minutes: float = 375.0) -> float:
        return minutes / (375 * 252)

    def _forward(self, spot=22500, r=0.065, tte=None):
        if tte is None:
            tte = self._tte()
        return spot * math.exp(r * tte)

    def test_atm_round_trip(self):
        """solve_iv(black76_price(..., σ), ...) ≈ σ for ATM."""
        sigma = 0.15
        F = self._forward()
        K = F  # ATM
        tte = self._tte()
        price = black76_price("CE", F, K, tte, self._RATE, sigma)
        recovered = solve_iv("CE", F, K, tte, self._RATE, price)
        assert recovered is not None
        assert abs(recovered - sigma) < 1e-4

    def test_deep_itm_ce(self):
        # Use 1-week tte so deep ITM has real vol content (0DTE tte is degenerate
        # for 20% moneyness — near-intrinsic prices have two IV roots near 0 and +inf)
        F = self._forward()
        K = F * 0.94  # ~6% ITM call — enough intrinsic + meaningful theta
        tte = self._tte(minutes=375 * 5)  # 5 sessions (~1 week)
        price = black76_price("CE", F, K, tte, self._RATE, 0.20)
        iv = solve_iv("CE", F, K, tte, self._RATE, price)
        assert iv is not None
        assert 0.18 < iv < 0.22

    def test_deep_otm_pe(self):
        # Same: use 1-week tte so OTM put has real vol content
        F = self._forward()
        K = F * 1.06  # ~6% OTM put
        tte = self._tte(minutes=375 * 5)
        price = black76_price("PE", F, K, tte, self._RATE, 0.25)
        iv = solve_iv("PE", F, K, tte, self._RATE, price)
        assert iv is not None
        assert 0.23 < iv < 0.27

    def test_zero_price_returns_none(self):
        F = self._forward()
        result = solve_iv("CE", F, F, self._tte(), self._RATE, 0.0)
        assert result is None

    def test_none_price_returns_none(self):
        F = self._forward()
        result = solve_iv("CE", F, F, self._tte(), self._RATE, None)
        assert result is None

    def test_negative_price_raises_value_error(self):
        F = self._forward()
        with pytest.raises(ValueError):
            solve_iv("CE", F, F, self._tte(), self._RATE, -1.0)

    def test_zero_tte_raises_value_error(self):
        F = self._forward()
        with pytest.raises(ValueError):
            solve_iv("CE", F, F, 0.0, self._RATE, 10.0)

    def test_invalid_option_type_raises(self):
        F = self._forward()
        with pytest.raises(ValueError):
            solve_iv("XX", F, F, self._tte(), self._RATE, 10.0)

    def test_nonpositive_forward_raises(self):
        with pytest.raises(ValueError):
            solve_iv("CE", 0, 22500, self._tte(), self._RATE, 10.0)

    def test_pe_round_trip(self):
        sigma = 0.20
        F = self._forward()
        K = F * 0.97
        tte = self._tte()
        price = black76_price("PE", F, K, tte, self._RATE, sigma)
        recovered = solve_iv("PE", F, K, tte, self._RATE, price)
        assert recovered is not None
        assert abs(recovered - sigma) < 1e-4


# ---------------------------------------------------------------------------
# IV null storage (Dhan IV trap)
# ---------------------------------------------------------------------------

class TestIVNullStorage:
    def test_iv_zero_stored_as_null(self):
        from chain_snapshotter import _iv_guard
        assert _iv_guard(0) is None
        assert _iv_guard(0.0) is None

    def test_iv_none_stored_as_null(self):
        from chain_snapshotter import _iv_guard
        assert _iv_guard(None) is None

    def test_valid_iv_passes_through(self):
        from chain_snapshotter import _iv_guard
        assert abs(_iv_guard(13.7) - 13.7) < 1e-9

    def test_negative_iv_stored_as_null(self):
        from chain_snapshotter import _iv_guard
        assert _iv_guard(-0.5) is None


# ---------------------------------------------------------------------------
# Bar builder — delta volume & gap fill
# ---------------------------------------------------------------------------

class TestBarBuilder:
    def _make_db_with_snapshots(self, snapshots: list) -> str:
        db = _tmp_db()
        init_db(db)
        conn = get_connection(db)
        for snap in snapshots:
            _insert_snapshot(conn, **snap)
        conn.commit()
        conn.close()
        return db

    def test_single_bar_volume(self):
        """Volume within one bar = last cumvol in bar (first bar of session)."""
        db = self._make_db_with_snapshots([
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:00+05:30", ltp=100.0, volume=1000),
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:30+05:30", ltp=101.0, volume=1500),
        ])
        try:
            build_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            bars = get_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            assert len(bars) == 1
            # First bar of session: volume = last cumvol in bar
            assert bars[0]["volume"] == 1500
        finally:
            os.unlink(db)

    def test_two_bar_delta_volume(self):
        """Volume of second bar = last cumvol of bar2 - last cumvol of bar1."""
        db = self._make_db_with_snapshots([
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:00+05:30", ltp=100.0, volume=1000),
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:17:00+05:30", ltp=102.0, volume=2500),
        ])
        try:
            build_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            bars = get_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            assert len(bars) == 2  # one bar per minute, plus gap fill handled
            assert bars[0]["volume"] == 1000  # first bar: full cumvol
            # Second bar delta = 2500 - 1000 = 1500
            # bars[1] may be at 09:17, check volume
            second = next(b for b in bars if "09:17" in b["bar_open_ts"])
            assert second["volume"] == 1500
        finally:
            os.unlink(db)

    def test_gap_fill_produced(self):
        """A missing bar window produces is_gap_fill=True with prior close propagated."""
        db = self._make_db_with_snapshots([
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:00+05:30", ltp=100.0, volume=1000),
            # jump two minutes — 09:17 has no snapshot
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:18:00+05:30", ltp=103.0, volume=2000),
        ])
        try:
            build_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            bars = get_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db, n=10)
            gap_bars = [b for b in bars if b["is_gap_fill"]]
            assert len(gap_bars) == 1
            assert gap_bars[0]["close"] == 100.0  # prior close propagated
            assert gap_bars[0]["volume"] == 0
        finally:
            os.unlink(db)

    def test_day_boundary_reset(self):
        """First bar of session has volume = its own cumvol (no subtraction)."""
        db = self._make_db_with_snapshots([
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:15:00+05:30", ltp=100.0, volume=500000),
        ])
        try:
            build_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            bars = get_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            assert bars[0]["volume"] == 500000
        finally:
            os.unlink(db)

    def test_volume_never_negative(self):
        """If cumvol decreases (anomaly), volume is clamped to 0."""
        db = self._make_db_with_snapshots([
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:00+05:30", ltp=100.0, volume=2000),
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:17:00+05:30", ltp=101.0, volume=1000),  # decreases
        ])
        try:
            build_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            bars = get_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            second = next((b for b in bars if "09:17" in b["bar_open_ts"]), None)
            if second:
                assert second["volume"] == 0
        finally:
            os.unlink(db)

    def test_ohlc_correctness(self):
        """Bar open = first ltp, close = last ltp, high/low are correct."""
        db = self._make_db_with_snapshots([
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:00+05:30", ltp=100.0, volume=1000),
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:20+05:30", ltp=115.0, volume=1200),
            dict(symbol="NIFTY", expiry="2026-10-06", strike=22500, opt_type="CE",
                 ts_ist="2026-10-06T09:16:50+05:30", ltp=98.0, volume=1500),
        ])
        try:
            build_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            bars = get_option_bars("NIFTY", "2026-10-06", 22500, "CE", "1m", db)
            b = bars[0]
            assert b["open"] == 100.0
            assert b["close"] == 98.0
            assert b["high"] == 115.0
            assert b["low"] == 98.0
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_min_3s_between_requests(self):
        """Two consecutive throttled calls must be at least 3 s apart."""
        from chain_snapshotter import _throttled_post, _MIN_INTERVAL
        call_times = []

        def fake_post(url, headers=None, json=None, timeout=None):
            call_times.append(time.monotonic())
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {}
            return resp

        with patch("chain_snapshotter.requests.post", side_effect=fake_post):
            # Reset last request time so we don't wait for a prior test
            import chain_snapshotter
            chain_snapshotter._LAST_REQUEST_TS = 0.0

            _throttled_post("http://fake/1", {})
            _throttled_post("http://fake/2", {})

        assert len(call_times) == 2
        gap = call_times[1] - call_times[0]
        assert gap >= _MIN_INTERVAL - 0.1  # 100 ms tolerance

    def test_rate_limiter_thread_safe(self):
        """Concurrent callers respect the rate limit."""
        from chain_snapshotter import _throttled_post
        import chain_snapshotter
        chain_snapshotter._LAST_REQUEST_TS = 0.0

        call_times = []
        lock = threading.Lock()

        def fake_post(url, headers=None, json=None, timeout=None):
            with lock:
                call_times.append(time.monotonic())
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {}
            return resp

        def worker():
            _throttled_post("http://fake/t", {})

        with patch("chain_snapshotter.requests.post", side_effect=fake_post):
            chain_snapshotter._LAST_REQUEST_TS = 0.0
            threads = [threading.Thread(target=worker) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(call_times) == 3
        call_times.sort()
        for i in range(1, len(call_times)):
            assert call_times[i] - call_times[i - 1] >= chain_snapshotter._MIN_INTERVAL - 0.1


# ---------------------------------------------------------------------------
# Expiry calendar — DTE minutes
# ---------------------------------------------------------------------------

class TestExpiryCalendar:
    def test_dte_before_close(self):
        expiry = datetime.date(2026, 10, 6)
        as_of = datetime.datetime(2026, 10, 6, 9, 15, 0, tzinfo=_IST)
        dte = get_dte_minutes("NIFTY", expiry, as_of)
        expected = (15 * 60 + 30 - 9 * 60 - 15)  # 375 minutes
        assert abs(dte - expected) < 1.0

    def test_dte_at_close(self):
        expiry = datetime.date(2026, 10, 6)
        as_of = datetime.datetime(2026, 10, 6, 15, 30, 0, tzinfo=_IST)
        dte = get_dte_minutes("NIFTY", expiry, as_of)
        assert dte == 0.0

    def test_dte_after_close_clamps_to_zero(self):
        expiry = datetime.date(2026, 10, 6)
        as_of = datetime.datetime(2026, 10, 6, 16, 0, 0, tzinfo=_IST)
        dte = get_dte_minutes("NIFTY", expiry, as_of)
        assert dte == 0.0

    def test_dte_naive_datetime_assumed_ist(self):
        expiry = datetime.date(2026, 10, 6)
        as_of_naive = datetime.datetime(2026, 10, 6, 9, 15, 0)  # no tzinfo
        dte = get_dte_minutes("NIFTY", expiry, as_of_naive)
        assert dte > 0


# ---------------------------------------------------------------------------
# Fail-closed: synthetic snapshots must be flagged
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_is_synthetic_flag_persists(self):
        db = _tmp_db()
        try:
            init_db(db)
            conn = get_connection(db)
            _insert_snapshot(
                conn, "NIFTY", "2026-10-06", 22500, "CE",
                "2026-10-06T09:16:00+05:30", 100.0, 1000, is_synthetic=1
            )
            conn.commit()
            row = conn.execute(
                "SELECT is_synthetic FROM chain_snapshots WHERE symbol='NIFTY'"
            ).fetchone()
            conn.close()
            assert row[0] == 1
        finally:
            os.unlink(db)

    def test_live_snapshot_is_not_synthetic(self):
        db = _tmp_db()
        try:
            init_db(db)
            conn = get_connection(db)
            _insert_snapshot(
                conn, "NIFTY", "2026-10-06", 22500, "CE",
                "2026-10-06T09:16:00+05:30", 100.0, 1000, is_synthetic=0
            )
            conn.commit()
            row = conn.execute(
                "SELECT is_synthetic FROM chain_snapshots WHERE symbol='NIFTY'"
            ).fetchone()
            conn.close()
            assert row[0] == 0
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

class TestDBPersistence:
    def test_snapshot_survives_reconnect(self):
        db = _tmp_db()
        try:
            init_db(db)
            conn = get_connection(db)
            _insert_snapshot(
                conn, "BANKNIFTY", "2026-10-27", 54700, "PE",
                "2026-10-27T10:00:00+05:30", 711.0, 50000,
                iv=17.1, security_id=49428,
            )
            conn.commit()
            conn.close()

            # Reconnect and verify
            conn2 = get_connection(db)
            row = conn2.execute(
                "SELECT ltp, iv, security_id FROM chain_snapshots WHERE symbol='BANKNIFTY'"
            ).fetchone()
            conn2.close()
            assert row is not None
            assert row[0] == 711.0
            assert abs(row[1] - 17.1) < 0.01
            assert row[2] == 49428
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Staleness gate tests (Phase 1A.2)
# ---------------------------------------------------------------------------

class TestStalenessGate:
    """get_latest_chain_snapshot must reject stale or cross-day snapshots."""

    def _make_snapshot_db(self, ts_ist_str: str) -> str:
        """Create a temp DB with a single NIFTY snapshot at the given IST ISO timestamp."""
        db = _tmp_db()
        init_db(db)
        conn = get_connection(db)
        _insert_snapshot(
            conn, "NIFTY", "2026-10-06", 22500, "CE",
            ts_ist_str, 150.0, 5000,
            iv=12.5, security_id=40697,
        )
        conn.commit()
        conn.close()
        return db

    def test_A_stale_4h_snapshot_returns_empty(self):
        """Test A: A 4-hour-old snapshot returns {} → hunter blocks with DATA_FAULT."""
        from chain_snapshotter import get_latest_chain_snapshot

        # Freeze "now" to 14:00 IST today; snapshot is at 10:00 IST (4 hours old)
        fake_now = datetime.datetime(2026, 10, 6, 14, 0, 0, tzinfo=_IST)
        snap_ts = "2026-10-06T10:00:00+05:30"
        db = self._make_snapshot_db(snap_ts)
        try:
            with patch("chain_snapshotter.datetime") as mock_dt:
                mock_dt.datetime.now.return_value = fake_now
                mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
                result = get_latest_chain_snapshot("NIFTY", db, max_age_seconds=90)
            assert result == {}
        finally:
            os.unlink(db)

    def test_B_yesterday_snapshot_returns_empty(self):
        """Test B: A snapshot from yesterday is rejected and returns {}."""
        from chain_snapshotter import get_latest_chain_snapshot

        # "now" is today 09:20 IST; snapshot is from yesterday 14:00 IST
        fake_now = datetime.datetime(2026, 10, 6, 9, 20, 0, tzinfo=_IST)
        snap_ts = "2026-10-05T14:00:00+05:30"  # yesterday
        db = self._make_snapshot_db(snap_ts)
        try:
            with patch("chain_snapshotter.datetime") as mock_dt:
                mock_dt.datetime.now.return_value = fake_now
                mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
                result = get_latest_chain_snapshot("NIFTY", db, max_age_seconds=90)
            assert result == {}
        finally:
            os.unlink(db)

    def test_C_fresh_snapshot_returns_data_with_age(self):
        """Test C: A fresh snapshot (age ≤ 30s) returns full data with snapshot_age_seconds."""
        from chain_snapshotter import get_latest_chain_snapshot

        # "now" is 09:16:20 IST; snapshot at 09:16:00 IST — 20s old
        fake_now = datetime.datetime(2026, 10, 6, 9, 16, 20, tzinfo=_IST)
        snap_ts = "2026-10-06T09:16:00+05:30"
        db = self._make_snapshot_db(snap_ts)
        try:
            with patch("chain_snapshotter.datetime") as mock_dt:
                mock_dt.datetime.now.return_value = fake_now
                mock_dt.datetime.fromisoformat = datetime.datetime.fromisoformat
                result = get_latest_chain_snapshot("NIFTY", db, max_age_seconds=90)
            assert result != {}
            assert "oc" in result
            assert "snapshot_age_seconds" in result
            assert result["snapshot_age_seconds"] <= 30.0
        finally:
            os.unlink(db)

    def test_D_empty_db_returns_empty(self):
        """Test D: An empty DB returns {}."""
        from chain_snapshotter import get_latest_chain_snapshot

        db = _tmp_db()
        init_db(db)
        try:
            result = get_latest_chain_snapshot("NIFTY", db, max_age_seconds=90)
            assert result == {}
        finally:
            os.unlink(db)
