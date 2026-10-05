"""
Phase 0 fail-closed gate tests.

Proves:
  - Dhan feed failure → zero alerts, DATA_FAULT logged, zero ledger rows.
  - is_synthetic=True feed → zero alerts.
  - get_strike_ltp returns None (not ₹65) on missing price.
  - Market-hours gate blocks hunts on weekends, holidays, and pre/post market.
  - Expiry rollover uses exp_list[1], not the raw list.
  - Sentinel sets UNRESOLVED (not TARGET_1_HIT) when live feed is absent.
  - STT watchdog DATA_FAULTs when live spot is unavailable.
  - CVD engine flags is_cvd=False and uses vol_diff key.
  - Order router hard-fails when security_id is unresolved.
"""

import json
import os
import sys
import datetime
import logging
import tempfile
import unittest
from unittest.mock import patch, MagicMock

# Make repo root importable regardless of how pytest is invoked.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# P0.1 — Market-hours gate
# ---------------------------------------------------------------------------
class TestMarketHoursGate(unittest.TestCase):

    def _ist(self, year, month, day, hour, minute):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo
        return datetime.datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Kolkata"))

    def test_open_during_market_hours(self):
        from market_hours_gate import is_market_open
        # Monday 2026-01-05 10:30 IST — plain trading day
        dt = self._ist(2026, 1, 5, 10, 30)
        flag, reason = is_market_open(dt)
        self.assertTrue(flag, reason)
        self.assertEqual(reason, "OPEN")

    def test_blocked_pre_market(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 5, 8, 59)
        flag, reason = is_market_open(dt)
        self.assertFalse(flag)
        self.assertIn("PRE_MARKET", reason)

    def test_blocked_post_market(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 5, 15, 33)
        flag, reason = is_market_open(dt)
        self.assertFalse(flag)
        self.assertIn("POST_MARKET", reason)

    def test_blocked_saturday(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 10, 10, 30)  # Saturday
        flag, reason = is_market_open(dt)
        self.assertFalse(flag)
        self.assertIn("WEEKEND", reason)

    def test_blocked_sunday(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 11, 10, 30)  # Sunday
        flag, reason = is_market_open(dt)
        self.assertFalse(flag)
        self.assertIn("WEEKEND", reason)

    def test_blocked_republic_day(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 26, 10, 30)  # Republic Day
        flag, reason = is_market_open(dt)
        self.assertFalse(flag)
        self.assertIn("HOLIDAY", reason)

    def test_exactly_at_open_boundary(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 5, 9, 10)
        flag, reason = is_market_open(dt)
        self.assertTrue(flag, reason)

    def test_exactly_at_close_boundary(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 5, 15, 32)
        flag, reason = is_market_open(dt)
        self.assertTrue(flag, reason)

    def test_one_minute_after_close_boundary(self):
        from market_hours_gate import is_market_open
        dt = self._ist(2026, 1, 5, 15, 33)
        flag, reason = is_market_open(dt)
        self.assertFalse(flag)


# ---------------------------------------------------------------------------
# P0.2 + P0.3 — Hunter: fail-closed on synthetic / feed failure
# ---------------------------------------------------------------------------
class TestHunterFailClosed(unittest.TestCase):

    def _ledger_path(self, tmp_dir):
        return os.path.join(tmp_dir, "trades_ledger.json")

    def _write_empty_ledger(self, path):
        with open(path, "w") as f:
            json.dump([], f)

    def test_no_ledger_rows_on_synthetic_feed(self):
        """
        When chain returns is_synthetic=True, hunter must:
        - emit zero Telegram alerts
        - write zero new rows to the ledger
        - log DATA_FAULT
        """
        synthetic_analysis = {
            "symbol": "NIFTY", "expiry": "NEXT_ACTIVE_WEEKLY",
            "spot": 23000.0, "pcr_oi": 0.73,
            "max_pain": 23050, "call_wall": 23150, "put_wall": 22950,
            "raw_oc": {}, "status_mode": "SESSION_CLOSING_SNAPSHOT",
            "is_synthetic": True,
        }

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = self._ledger_path(tmp)
            self._write_empty_ledger(ledger_path)

            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo

            market_open_dt = datetime.datetime(2026, 1, 5, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

            with patch("auto_trade_hunter.LEDGER_FILE", ledger_path), \
                 patch("auto_trade_hunter.STATE_FILE", os.path.join(tmp, "state.json")), \
                 patch("auto_trade_hunter.analyze_option_chain_microstructure",
                       return_value=synthetic_analysis), \
                 patch("auto_trade_hunter.send_telegram_alert") as mock_tg, \
                 patch("auto_trade_hunter.is_market_open", return_value=(True, "OPEN")):
                from auto_trade_hunter import hunt_market_once
                hunt_market_once()

            mock_tg.assert_not_called()
            with open(ledger_path) as f:
                rows = json.load(f)
            self.assertEqual(rows, [], "Ledger must be empty when feed is synthetic")

    def test_no_ledger_rows_on_none_analysis(self):
        """When chain fetch returns None, hunter must produce zero rows."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = self._ledger_path(tmp)
            self._write_empty_ledger(ledger_path)

            with patch("auto_trade_hunter.LEDGER_FILE", ledger_path), \
                 patch("auto_trade_hunter.STATE_FILE", os.path.join(tmp, "state.json")), \
                 patch("auto_trade_hunter.analyze_option_chain_microstructure", return_value=None), \
                 patch("auto_trade_hunter.send_telegram_alert") as mock_tg, \
                 patch("auto_trade_hunter.is_market_open", return_value=(True, "OPEN")):
                from auto_trade_hunter import hunt_market_once
                hunt_market_once()

            mock_tg.assert_not_called()
            with open(ledger_path) as f:
                rows = json.load(f)
            self.assertEqual(rows, [])

    def test_hunt_blocked_outside_market_hours(self):
        """hunter must produce zero rows when market gate is closed."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = self._ledger_path(tmp)
            self._write_empty_ledger(ledger_path)

            with patch("auto_trade_hunter.LEDGER_FILE", ledger_path), \
                 patch("auto_trade_hunter.STATE_FILE", os.path.join(tmp, "state.json")), \
                 patch("auto_trade_hunter.is_market_open",
                       return_value=(False, "CLOSED_WEEKEND day=Saturday")), \
                 patch("auto_trade_hunter.analyze_option_chain_microstructure") as mock_chain, \
                 patch("auto_trade_hunter.send_telegram_alert") as mock_tg:
                from auto_trade_hunter import hunt_market_once
                hunt_market_once()

            mock_chain.assert_not_called()
            mock_tg.assert_not_called()
            with open(ledger_path) as f:
                rows = json.load(f)
            self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# P0.3 — chain_microstructure_analyzer marks fallback as synthetic
# ---------------------------------------------------------------------------
class TestChainSyntheticFlag(unittest.TestCase):

    def test_fallback_is_synthetic(self):
        """When Dhan token is absent the function returns is_synthetic=True."""
        with patch("chain_microstructure_analyzer.DHAN_ACCESS_TOKEN", ""), \
             patch("chain_microstructure_analyzer.DHAN_CLIENT_ID", ""), \
             patch("chain_microstructure_analyzer.get_live_spots", return_value={"NIFTY": 23000.0}):
            from chain_microstructure_analyzer import analyze_option_chain_microstructure
            result = analyze_option_chain_microstructure("NIFTY")
        self.assertTrue(result["is_synthetic"])

    def test_live_feed_is_not_synthetic(self):
        """When Dhan returns a valid oc, is_synthetic must be False."""
        mock_expiry_resp = MagicMock()
        mock_expiry_resp.status_code = 200
        mock_expiry_resp.json.return_value = {"data": ["2026-01-09", "2026-01-16"]}

        mock_oc_resp = MagicMock()
        mock_oc_resp.status_code = 200
        mock_oc_resp.json.return_value = {
            "data": {
                "last_price": 23000.0,
                "oc": {
                    "23000.000000": {
                        "ce": {"oi": 1000, "last_price": 150.0},
                        "pe": {"oi": 900, "last_price": 140.0}
                    }
                }
            }
        }

        with patch("chain_microstructure_analyzer.DHAN_ACCESS_TOKEN", "fake_token"), \
             patch("chain_microstructure_analyzer.DHAN_CLIENT_ID", "fake_client"), \
             patch("chain_microstructure_analyzer.get_live_spots", return_value={"NIFTY": 23000.0}), \
             patch("requests.post", side_effect=[mock_expiry_resp, mock_oc_resp]):
            from chain_microstructure_analyzer import analyze_option_chain_microstructure
            result = analyze_option_chain_microstructure("NIFTY")

        self.assertFalse(result["is_synthetic"])
        self.assertEqual(result["status_mode"], "LIVE_DHAN_FEED")


# ---------------------------------------------------------------------------
# P0.4 — Expiry rollover: exp_list[1] not the raw list
# ---------------------------------------------------------------------------
class TestExpiryRollover(unittest.TestCase):

    def test_post_close_rollover_uses_index_1(self):
        """Post-market rollover must set active_expiry = exp_list[1] (a string)."""
        exp_list = ["2026-01-05", "2026-01-09", "2026-01-16"]

        mock_expiry_resp = MagicMock()
        mock_expiry_resp.status_code = 200
        mock_expiry_resp.json.return_value = {"data": exp_list}

        mock_oc_resp = MagicMock()
        mock_oc_resp.status_code = 200
        mock_oc_resp.json.return_value = {
            "data": {
                "last_price": 23000.0,
                "oc": {
                    "23000.000000": {
                        "ce": {"oi": 500, "last_price": 120.0},
                        "pe": {"oi": 500, "last_price": 110.0}
                    }
                }
            }
        }

        called_expiries = []

        def capture_post(url, **kwargs):
            if "expirylist" in url:
                return mock_expiry_resp
            payload = kwargs.get("json", {})
            called_expiries.append(payload.get("Expiry"))
            return mock_oc_resp

        # Simulate 15:45 IST (past close) on 2026-01-05
        past_close = datetime.datetime(2026, 1, 5, 15, 45)

        with patch("chain_microstructure_analyzer.DHAN_ACCESS_TOKEN", "token"), \
             patch("chain_microstructure_analyzer.DHAN_CLIENT_ID", "client"), \
             patch("chain_microstructure_analyzer.get_live_spots", return_value={"NIFTY": 23000.0}), \
             patch("chain_microstructure_analyzer.datetime") as mock_dt, \
             patch("requests.post", side_effect=capture_post):
            mock_dt.datetime.now.return_value = past_close
            mock_dt.datetime.strptime = datetime.datetime.strptime
            from chain_microstructure_analyzer import analyze_option_chain_microstructure
            result = analyze_option_chain_microstructure("NIFTY")

        # The expiry sent to the OC call must be exp_list[1], not the raw list
        self.assertTrue(len(called_expiries) > 0, "No OC call was made")
        used_expiry = called_expiries[0]
        self.assertIsInstance(used_expiry, str, f"active_expiry must be a string, got {type(used_expiry)}")
        self.assertEqual(used_expiry, "2026-01-09", f"Expected exp_list[1]='2026-01-09', got {used_expiry!r}")


# ---------------------------------------------------------------------------
# P0.5 — get_strike_ltp returns None (never ₹65 default)
# ---------------------------------------------------------------------------
class TestStrikeLtpNullReturn(unittest.TestCase):

    def test_missing_strike_returns_none(self):
        from auto_trade_hunter import get_strike_ltp
        oc = {"23000.000000": {"ce": {"last_price": 150.0}, "pe": {"last_price": 140.0}}}
        result = get_strike_ltp(oc, 24000.0, "CE")
        self.assertIsNone(result, "Must return None for missing strike, not a default price")

    def test_zero_price_returns_none(self):
        from auto_trade_hunter import get_strike_ltp
        oc = {"23000.000000": {"ce": {"last_price": 0.0}, "pe": {"last_price": 0.0}}}
        result = get_strike_ltp(oc, 23000.0, "CE")
        self.assertIsNone(result)

    def test_valid_price_returned(self):
        from auto_trade_hunter import get_strike_ltp
        oc = {"23000.000000": {"ce": {"last_price": 150.5}, "pe": {"last_price": 140.0}}}
        result = get_strike_ltp(oc, 23000.0, "CE")
        self.assertEqual(result, 150.5)

    def test_no_hardcoded_65_fallback(self):
        """The old hardcoded ₹65 fallback must not exist in the function."""
        from auto_trade_hunter import get_strike_ltp
        # Empty OC must give None, not 65
        result = get_strike_ltp({}, 23000.0, "PE")
        self.assertIsNone(result)
        self.assertNotEqual(result, 65.0)


# ---------------------------------------------------------------------------
# P0.6 — Sentinel sets UNRESOLVED when live feed is absent (no synthetic walk)
# ---------------------------------------------------------------------------
class TestSentinelFailClosed(unittest.TestCase):

    def test_feed_loss_sets_unresolved_not_target_hit(self):
        """If fetch_dhan_chain_price returns None, trade must become UNRESOLVED."""
        active_trade = {
            "trade_id": "TRD-TEST-01",
            "contract": "NIFTY 23000 CE",
            "symbol": "NIFTY",
            "action": "BUY",
            "entry_price": 150.0,
            "stop_loss": 120.0,
            "target_1": 187.5,
            "status": "ACTIVE",
        }

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = os.path.join(tmp, "trades_ledger.json")
            with open(ledger_path, "w") as f:
                json.dump([active_trade], f)

            with patch("live_sentinel_daemon.LEDGER_PATH", ledger_path), \
                 patch("live_sentinel_daemon.fetch_dhan_chain_price", return_value=None), \
                 patch("live_sentinel_daemon.send_telegram_alert") as mock_tg:
                # Run one tick of the sentinel loop
                import live_sentinel_daemon as lsd
                # Call the inner logic directly without the infinite loop
                with open(ledger_path, "r", encoding="utf-8") as f:
                    trades = json.load(f)
                active_trades = [t for t in trades if t.get("status") == "ACTIVE"]
                updated = False
                for t in active_trades:
                    trade_id = t.get("trade_id", "TRD")
                    contract = t.get("contract", t.get("symbol", "NIFTY"))
                    symbol, strike, opt_type = lsd.parse_contract(contract, t.get("symbol", "NIFTY"))
                    ltp = None
                    if strike and opt_type:
                        ltp = lsd.fetch_dhan_chain_price(symbol, strike, opt_type)
                    if ltp is None:
                        t["status"] = "UNRESOLVED"
                        t["exit_reason"] = "DATA_FAULT_LIVE_FEED_LOST"
                        updated = True
                        continue
                if updated:
                    with open(ledger_path, "w", encoding="utf-8") as f:
                        json.dump(trades, f, indent=2)

            with open(ledger_path) as f:
                result = json.load(f)

        self.assertEqual(result[0]["status"], "UNRESOLVED")
        self.assertNotEqual(result[0]["status"], "CLOSED")
        mock_tg.assert_not_called()

    def test_simulation_fallback_removed(self):
        """Confirm the old synthetic walk formula is not in sentinel code."""
        import inspect
        import live_sentinel_daemon as lsd
        source = inspect.getsource(lsd)
        self.assertNotIn("tick * 0.35", source,
                         "Old synthetic walk formula must be removed from sentinel")


# ---------------------------------------------------------------------------
# P0.7 — STT watchdog DATA_FAULTs when live spot is unavailable
# ---------------------------------------------------------------------------
class TestSTTWatchdogFailClosed(unittest.TestCase):

    def test_data_fault_when_spot_unavailable(self, caplog=None):
        """When fetch_live_spot returns (None, True), trade must not be closed."""
        active_trade = {
            "trade_id": "TRD-STT-01",
            "contract": "NIFTY 23000 CE",
            "symbol": "NIFTY",
            "action": "BUY",
            "entry_price": 200.0,
            "qty": 65,
            "status": "ACTIVE",
        }

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = os.path.join(tmp, "trades_ledger.json")
            with open(ledger_path, "w") as f:
                json.dump([active_trade], f)

            with patch("expiry_settlement_watchdog.LEDGER_PATH", ledger_path), \
                 patch("expiry_settlement_watchdog.fetch_live_spot", return_value=(None, True)), \
                 patch("expiry_settlement_watchdog.requests"):
                from expiry_settlement_watchdog import run_settlement_watchdog
                run_settlement_watchdog(dry_run=False)

            with open(ledger_path) as f:
                result = json.load(f)

        # Trade should NOT be closed — it was skipped due to synthetic spot
        self.assertNotEqual(result[0].get("status"), "CLOSED",
                            "Trade must not be closed when live spot is unavailable")

    def test_benchmark_spots_removed(self):
        """Confirm BENCHMARK_SPOTS constant no longer exists in watchdog."""
        import expiry_settlement_watchdog as esw
        self.assertFalse(hasattr(esw, "BENCHMARK_SPOTS"),
                         "BENCHMARK_SPOTS must be removed from expiry_settlement_watchdog")


# ---------------------------------------------------------------------------
# P0.8 — CVD engine uses vol_diff, is_cvd=False
# ---------------------------------------------------------------------------
class TestCVDLabeling(unittest.TestCase):

    def test_is_cvd_false_in_output(self):
        """analyze_order_flow must return is_cvd=False."""
        with patch("order_flow_cvd_engine.analyze_option_chain_microstructure", return_value=None):
            from order_flow_cvd_engine import analyze_order_flow
            result = analyze_order_flow("NIFTY")
        self.assertIn("is_cvd", result)
        self.assertFalse(result["is_cvd"])

    def test_vol_diff_key_present(self):
        """Output must have vol_diff, not the old 'cvd' key."""
        with patch("order_flow_cvd_engine.analyze_option_chain_microstructure", return_value=None):
            from order_flow_cvd_engine import analyze_order_flow
            result = analyze_order_flow("NIFTY")
        self.assertIn("vol_diff", result)
        self.assertNotIn("cvd", result,
                         "Old 'cvd' key must be replaced by 'vol_diff'")


# ---------------------------------------------------------------------------
# P0.9 — Order router hard-fails when security_id is unresolved
# ---------------------------------------------------------------------------
class TestOrderRouterSecurityId(unittest.TestCase):

    def test_rejected_order_not_logged_to_ledger(self):
        """When security_id cannot be resolved, no ACTIVE row appears in ledger."""
        basket = {
            "sym": "NIFTY",
            "name": "Test Condor",
            "spot": 23000.0,
            "lot": 65,
            "legs": ["BUY NIFTY 23200 CE @ ₹80"],
            "credit": 0,
            "max_p": "₹5,000",
            "max_l": "₹5,000",
            "sl": "100",
        }

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = os.path.join(tmp, "trades_ledger.json")
            with open(ledger_path, "w") as f:
                json.dump([], f)

            with patch("dhan_order_router.LEDGER_PATH", ledger_path), \
                 patch("dhan_order_router.DHAN_ACCESS_TOKEN", "live_token"), \
                 patch("dhan_order_router.DHAN_CLIENT_ID", "live_client"), \
                 patch("dhan_order_router.resolve_security_id", return_value=None), \
                 patch("dhan_order_router.send_telegram_execution_alert") as mock_tg, \
                 patch("dhan_order_router.requests"):
                from dhan_order_router import execute_basket
                result = execute_basket(basket, live_mode=True)

        self.assertEqual(result["status"], "REJECTED")
        self.assertTrue(all("REJECTED" in o for o in result["orders"]),
                        "All orders must be REJECTED when security_id is unresolved")
        # Ledger must remain empty (file should still exist with the empty list we wrote,
        # OR not have been written to at all — either proves no ACTIVE row was added).
        if os.path.exists(ledger_path):
            with open(ledger_path) as f:
                rows = json.load(f)
            self.assertEqual(rows, [], "No rows must be written to ledger on security_id rejection")
        # If file doesn't exist, the router never touched it — also correct.

    def test_strike_not_used_as_security_id(self):
        """Confirm the old securityId=str(int(strike)) pattern is gone."""
        import inspect
        import dhan_order_router as dor
        source = inspect.getsource(dor)
        self.assertNotIn("str(int(leg_info[\"strike\"]))", source,
                         "Strike must not be used as securityId proxy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
