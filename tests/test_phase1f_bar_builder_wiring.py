"""Phase 1F: bar-builder wiring, FINNIFTY spot fix, Telegram HTML parse_mode.

Tests run without live credentials — all broker/API calls are mocked.
"""

import datetime
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from db_init import init_db, get_connection
from bar_builder import build_bars, build_underlying_bars, build_option_bars

_IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    init_db(f.name)
    return f.name


def _ts(h: int, m: int, s: int = 0) -> str:
    return datetime.datetime(2026, 10, 6, h, m, s, tzinfo=_IST).isoformat()


def _insert_spot(conn, symbol: str, ltp: float, ts: str):
    conn.execute(
        """INSERT OR REPLACE INTO chain_snapshots
           (symbol, expiry, strike, option_type, timestamp,
            ltp, oi, volume, iv, delta, theta, gamma, vega,
            security_id, is_synthetic)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol, "2026-10-07", 0.0, "SPOT", ts, ltp, 0, 0,
         None, None, None, None, None, 13, 0),
    )


def _insert_option(conn, symbol: str, strike: float, opt_type: str,
                   ltp: float, volume: int, ts: str):
    conn.execute(
        """INSERT OR REPLACE INTO chain_snapshots
           (symbol, expiry, strike, option_type, timestamp,
            ltp, oi, volume, iv, delta, theta, gamma, vega,
            security_id, is_synthetic)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol, "2026-10-07", strike, opt_type, ts, ltp, 100, volume,
         None, 0.5, -1.0, 0.001, 0.3, 40697, 0),
    )


# ---------------------------------------------------------------------------
# Fix 1: build_bars() API
# ---------------------------------------------------------------------------

class TestBuildBarsAPI:
    def test_returns_dict_with_all_symbols(self):
        db = _tmp_db()
        try:
            result = build_bars(db)
            assert set(result.keys()) == {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"}
        finally:
            os.unlink(db)

    def test_returns_underlying_and_option_keys(self):
        db = _tmp_db()
        try:
            result = build_bars(db)
            for sym in result:
                assert "underlying" in result[sym]
                assert "option" in result[sym]
        finally:
            os.unlink(db)

    def test_empty_db_returns_zeros(self):
        db = _tmp_db()
        try:
            result = build_bars(db)
            for sym in result:
                assert result[sym]["underlying"] == 0
                assert result[sym]["option"] == 0
        finally:
            os.unlink(db)

    def test_custom_symbols_subset(self):
        db = _tmp_db()
        try:
            result = build_bars(db, symbols=["NIFTY", "SENSEX"])
            assert set(result.keys()) == {"NIFTY", "SENSEX"}
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Fix 1: underlying_bars populated from SPOT rows
# ---------------------------------------------------------------------------

class TestUnderlyingBarsFromSpotRows:
    def test_spot_row_produces_underlying_bar(self):
        db = _tmp_db()
        conn = get_connection(db)
        try:
            _insert_spot(conn, "NIFTY", 25000.0, _ts(9, 16))
            _insert_spot(conn, "NIFTY", 25010.0, _ts(9, 16, 30))
            conn.commit()
        finally:
            conn.close()

        try:
            n = build_underlying_bars("NIFTY", "1m", db)
            assert n >= 1, f"Expected >=1 underlying bar row, got {n}"

            conn2 = get_connection(db)
            try:
                rows = conn2.execute(
                    "SELECT COUNT(*) FROM underlying_bars WHERE symbol='NIFTY'"
                ).fetchone()
            finally:
                conn2.close()
            assert rows[0] >= 1
        finally:
            os.unlink(db)

    def test_no_spot_rows_returns_zero(self):
        db = _tmp_db()
        try:
            n = build_underlying_bars("NIFTY", "1m", db)
            assert n == 0
        finally:
            os.unlink(db)

    def test_multiple_timeframes_produce_bars(self):
        db = _tmp_db()
        conn = get_connection(db)
        try:
            # Insert SPOT rows spanning 16 minutes to cover 1m, 5m, 15m
            for minute in range(15, 31):
                _insert_spot(conn, "BANKNIFTY", 52000.0 + minute, _ts(9, minute))
            conn.commit()
        finally:
            conn.close()

        try:
            result = build_bars(db, symbols=["BANKNIFTY"])
            assert result["BANKNIFTY"]["underlying"] > 0
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Fix 1: option_bars populated from CE/PE rows
# ---------------------------------------------------------------------------

class TestOptionBarsFromChainRows:
    def test_option_rows_produce_option_bars(self):
        db = _tmp_db()
        conn = get_connection(db)
        try:
            _insert_option(conn, "NIFTY", 25000, "CE", 100.0, 1000, _ts(9, 16))
            _insert_option(conn, "NIFTY", 25000, "CE", 102.0, 1050, _ts(9, 16, 45))
            _insert_option(conn, "NIFTY", 25000, "PE", 98.0, 900, _ts(9, 16))
            conn.commit()
        finally:
            conn.close()

        try:
            result = build_bars(db, symbols=["NIFTY"])
            assert result["NIFTY"]["option"] >= 1, (
                f"Expected >=1 option bar row, got {result['NIFTY']['option']}"
            )

            conn2 = get_connection(db)
            try:
                n = conn2.execute(
                    "SELECT COUNT(*) FROM option_bars WHERE symbol='NIFTY'"
                ).fetchone()[0]
            finally:
                conn2.close()
            assert n >= 1
        finally:
            os.unlink(db)

    def test_build_bars_excludes_spot_from_option_bars(self):
        """build_bars must not include SPOT sentinel rows in option_bars aggregation."""
        db = _tmp_db()
        conn = get_connection(db)
        try:
            # Only SPOT rows — no CE/PE option rows
            _insert_spot(conn, "NIFTY", 25000.0, _ts(9, 16))
            conn.commit()
        finally:
            conn.close()

        try:
            result = build_bars(db, symbols=["NIFTY"])
            # option count should be 0 (SPOT rows are excluded in build_bars)
            assert result["NIFTY"]["option"] == 0, (
                f"build_bars must skip SPOT rows for option_bars, got {result['NIFTY']['option']}"
            )
        finally:
            os.unlink(db)

    def test_build_bars_triggers_both_tables(self):
        db = _tmp_db()
        conn = get_connection(db)
        try:
            _insert_spot(conn, "NIFTY", 25000.0, _ts(9, 16))
            _insert_option(conn, "NIFTY", 25000, "CE", 100.0, 1000, _ts(9, 16))
            conn.commit()
        finally:
            conn.close()

        try:
            result = build_bars(db, symbols=["NIFTY"])
            assert result["NIFTY"]["underlying"] >= 1
            assert result["NIFTY"]["option"] >= 1
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Fix 1: chain_snapshotter SPOT row injection + _kick_bar_builder
# ---------------------------------------------------------------------------

class TestSnapshotterSpotRow:
    def test_fetch_and_persist_writes_spot_row_when_underlying_ltp_present(self):
        """When Dhan chain response contains last_price, a SPOT sentinel is written."""
        db = _tmp_db()
        try:
            mock_chain_resp = {
                "data": {
                    "last_price": 25000.0,
                    "oc": {
                        "25000": {
                            "ce": {"last_price": 100.0, "oi": 1000, "volume": 500,
                                   "implied_volatility": 0.18, "security_id": 40697,
                                   "greeks": {"delta": 0.5, "theta": -1.0,
                                              "gamma": 0.001, "vega": 0.3}},
                            "pe": {"last_price": 98.0, "oi": 900, "volume": 400,
                                   "implied_volatility": 0.19, "security_id": 40698,
                                   "greeks": {"delta": -0.5, "theta": -1.0,
                                              "gamma": 0.001, "vega": 0.3}},
                        }
                    },
                }
            }
            mock_exp_resp = {"data": ["2026-10-07"]}

            with patch("chain_snapshotter._throttled_post") as mock_post:
                mock_post.side_effect = [mock_exp_resp, mock_chain_resp]
                from chain_snapshotter import _fetch_and_persist
                rows = _fetch_and_persist("NIFTY", db)

            conn = get_connection(db)
            try:
                spot_rows = conn.execute(
                    "SELECT ltp FROM chain_snapshots WHERE symbol='NIFTY' AND option_type='SPOT'"
                ).fetchall()
            finally:
                conn.close()

            assert len(spot_rows) == 1, "Expected exactly one SPOT sentinel row"
            assert spot_rows[0][0] == 25000.0
        finally:
            os.unlink(db)

    def test_fetch_and_persist_no_spot_row_when_last_price_absent(self):
        """If chain response has no last_price, no SPOT row is written."""
        db = _tmp_db()
        try:
            mock_chain_resp = {
                "data": {
                    "oc": {
                        "25000": {
                            "ce": {"last_price": 100.0, "oi": 1000, "volume": 500,
                                   "implied_volatility": 0.18, "security_id": 40697,
                                   "greeks": {"delta": 0.5, "theta": -1.0,
                                              "gamma": 0.001, "vega": 0.3}},
                        }
                    },
                }
            }
            mock_exp_resp = {"data": ["2026-10-07"]}

            with patch("chain_snapshotter._throttled_post") as mock_post:
                mock_post.side_effect = [mock_exp_resp, mock_chain_resp]
                from chain_snapshotter import _fetch_and_persist
                _fetch_and_persist("NIFTY", db)

            conn = get_connection(db)
            try:
                spot_rows = conn.execute(
                    "SELECT COUNT(*) FROM chain_snapshots WHERE symbol='NIFTY' AND option_type='SPOT'"
                ).fetchone()[0]
            finally:
                conn.close()
            assert spot_rows == 0
        finally:
            os.unlink(db)

    def test_kick_bar_builder_non_blocking(self):
        """_kick_bar_builder must return without blocking (daemon thread)."""
        import threading
        import time
        db = _tmp_db()
        try:
            from chain_snapshotter import _kick_bar_builder
            started = threading.Event()
            original_build = __import__("bar_builder").build_bars

            def slow_build(*args, **kwargs):
                started.set()
                time.sleep(0.2)  # simulate slow build
                return original_build(*args, **kwargs)

            with patch("bar_builder.build_bars", side_effect=slow_build):
                t0 = time.monotonic()
                _kick_bar_builder(db)
                elapsed = time.monotonic() - t0

            # The call should return in well under 0.1 s (the build takes 0.2 s)
            assert elapsed < 0.1, f"_kick_bar_builder blocked for {elapsed:.3f}s"
            # Give the daemon thread time to start
            started.wait(timeout=1.0)
            assert started.is_set()
        finally:
            os.unlink(db)


# ---------------------------------------------------------------------------
# Fix 2: FINNIFTY spot feed — None when unavailable
# ---------------------------------------------------------------------------

class TestFinniftySpotFeed:
    def test_finnifty_returns_none_when_dhan_returns_zero(self):
        """FINNIFTY spot must be None, not 0.0, when Dhan LTP is 0."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "IDX_I": {
                    "13": {"last_price": 25000.0},   # NIFTY OK
                    "25": {"last_price": 52000.0},   # BANKNIFTY OK
                    "27": {"last_price": 0.0},        # FINNIFTY returns 0
                    "51": {"last_price": 80000.0},   # SENSEX OK
                }
            }
        }
        with patch("live_spot_service.requests.post", return_value=mock_response), \
             patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": "tok", "DHAN_CLIENT_ID": "cli"}):
            # Reload to pick up patched env
            import importlib, live_spot_service as lss
            importlib.reload(lss)
            with patch("live_spot_service.DHAN_ACCESS_TOKEN", "tok"), \
                 patch("live_spot_service.DHAN_CLIENT_ID", "cli"), \
                 patch("live_spot_service.requests.post", return_value=mock_response):
                spots = lss.get_live_spots()

        assert spots["FINNIFTY"] is None, (
            f"FINNIFTY should be None when Dhan returns 0, got {spots['FINNIFTY']}"
        )

    def test_finnifty_returns_value_when_dhan_ok(self):
        """FINNIFTY spot is populated correctly from Dhan IDX_I[27]."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "IDX_I": {
                    "13": {"last_price": 25000.0},
                    "25": {"last_price": 52000.0},
                    "27": {"last_price": 24320.5},   # FINNIFTY live
                    "51": {"last_price": 80000.0},
                }
            }
        }
        import importlib, live_spot_service as lss
        importlib.reload(lss)
        with patch("live_spot_service.DHAN_ACCESS_TOKEN", "tok"), \
             patch("live_spot_service.DHAN_CLIENT_ID", "cli"), \
             patch("live_spot_service.requests.post", return_value=mock_response):
            spots = lss.get_live_spots()

        assert spots["FINNIFTY"] == 24320.5

    def test_all_spots_none_when_dhan_unavailable(self):
        """If Dhan request fails, all spots that have no fallback return None."""
        with patch("live_spot_service.DHAN_ACCESS_TOKEN", ""), \
             patch("live_spot_service.DHAN_CLIENT_ID", ""), \
             patch("live_spot_service.requests.post", side_effect=Exception("no conn")), \
             patch("live_spot_service.requests.get", side_effect=Exception("no conn")):
            import live_spot_service as lss
            spots = lss.get_live_spots()

        # FINNIFTY has no Yahoo/BSE fallback — must be None
        assert spots["FINNIFTY"] is None

    def test_default_spots_dict_has_no_zero_defaults(self):
        """Verify the spots dict initialises with None, not 0.0."""
        import inspect, live_spot_service as lss
        src = inspect.getsource(lss.get_live_spots)
        assert '"FINNIFTY": 0.0' not in src, "Should not initialise FINNIFTY to 0.0"
        assert '"FINNIFTY": None' in src or "None" in src

    def test_finnifty_none_when_key_missing_from_dhan_response(self):
        """FINNIFTY must be None when Dhan IDX_I response omits key 27."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "IDX_I": {
                    "13": {"last_price": 25000.0},
                    # "27" deliberately absent
                    "51": {"last_price": 80000.0},
                }
            }
        }
        import live_spot_service as lss
        with patch("live_spot_service.DHAN_ACCESS_TOKEN", "tok"), \
             patch("live_spot_service.DHAN_CLIENT_ID", "cli"), \
             patch("live_spot_service.requests.post", return_value=mock_response):
            spots = lss.get_live_spots()

        assert spots["FINNIFTY"] is None


# ---------------------------------------------------------------------------
# Fix 3: Telegram parse_mode = HTML
# ---------------------------------------------------------------------------

class TestTelegramParseMode:
    def test_send_telegram_alert_uses_html(self):
        """send_telegram_alert must use parse_mode='HTML' to avoid Markdown
        delimiter errors when vol_provisional field contains underscores."""
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["json"] = json
            return MagicMock(status_code=200)

        from auto_trade_hunter import send_telegram_alert
        with patch("auto_trade_hunter.requests.post", side_effect=mock_post), \
             patch("auto_trade_hunter.TELEGRAM_BOT_TOKEN", "fake_token"), \
             patch("auto_trade_hunter.TELEGRAM_CHAT_ID", "123"):
            send_telegram_alert("🔥 NIFTY_PB1_vol_provisional=True entry signal")

        assert captured.get("json", {}).get("parse_mode") == "HTML", (
            f"Expected parse_mode='HTML', got {captured.get('json', {}).get('parse_mode')!r}"
        )

    def test_send_telegram_alert_text_passed_through(self):
        """The message text must be forwarded unchanged."""
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["json"] = json
            return MagicMock(status_code=200)

        msg = "NIFTY long entry vol_provisional=True"
        from auto_trade_hunter import send_telegram_alert
        with patch("auto_trade_hunter.requests.post", side_effect=mock_post), \
             patch("auto_trade_hunter.TELEGRAM_BOT_TOKEN", "fake_token"), \
             patch("auto_trade_hunter.TELEGRAM_CHAT_ID", "123"):
            send_telegram_alert(msg)

        assert captured["json"]["text"] == msg

    def test_send_telegram_alert_no_markdown_parse_mode(self):
        """parse_mode must NOT be 'Markdown' (the old broken value)."""
        captured = {}

        def mock_post(url, json=None, timeout=None):
            captured["json"] = json
            return MagicMock(status_code=200)

        from auto_trade_hunter import send_telegram_alert
        with patch("auto_trade_hunter.requests.post", side_effect=mock_post), \
             patch("auto_trade_hunter.TELEGRAM_BOT_TOKEN", "fake_token"), \
             patch("auto_trade_hunter.TELEGRAM_CHAT_ID", "123"):
            send_telegram_alert("test")

        pm = captured.get("json", {}).get("parse_mode", "")
        assert pm != "Markdown", "parse_mode must not be 'Markdown'"
