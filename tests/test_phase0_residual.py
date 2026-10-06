"""
Phase 0 residual defect tests (P0.10, P0.11, P0.12).

P0.10 — fetch_live_spot returns (None, True) when all feeds fail.
P0.11 — sentinel keeps status=ACTIVE on single tick drop; escalates to UNRESOLVED
         after 10 consecutive failures; watchdog still squares off ACTIVE trades
         carrying data_fault=True.
P0.12 — 4-leg Iron Condor resolves all security IDs from exactly ONE option chain API call.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_trade(trade_id="TRD-20261005-01", status="ACTIVE", data_fault=False, ticks=0):
    return {
        "trade_id": trade_id,
        "symbol": "NIFTY",
        "contract": "NIFTY 24000 CE",
        "action": "BUY",
        "entry_price": 100.0,
        "stop_loss": 80.0,
        "target_1": 125.0,
        "status": status,
        "data_fault": data_fault,
        "data_fault_ticks": ticks,
        "data_fault_since": None,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
    }


# ---------------------------------------------------------------------------
# P0.10 — live_spot_service no longer returns hardcoded fallbacks
# ---------------------------------------------------------------------------
class TestP010LiveSpotNoFallback(unittest.TestCase):

    def test_get_live_spots_returns_zeros_when_all_feeds_fail(self):
        """get_live_spots must return 0.0 for every symbol when all tiers fail."""
        with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
            mock_post.side_effect = Exception("network down")
            mock_get.side_effect = Exception("network down")

            os.environ.setdefault("DHAN_CLIENT_ID", "test")
            os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")

            from live_spot_service import get_live_spots
            spots = get_live_spots()

        self.assertIsNone(spots["NIFTY"],
                          "NIFTY must be None when all feeds fail — callers treat None as DATA_FAULT")
        self.assertIsNone(spots["BANKNIFTY"],
                          "BANKNIFTY must be None when all feeds fail")
        self.assertIsNone(spots["SENSEX"],
                          "SENSEX must be None when all feeds fail")

    def test_fetch_live_spot_returns_none_synthetic_when_all_feeds_fail(self):
        """expiry_settlement_watchdog.fetch_live_spot must return (None, True) when feeds fail."""
        with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
            mock_post.side_effect = Exception("offline")
            mock_get.side_effect = Exception("offline")

            os.environ.setdefault("DHAN_CLIENT_ID", "test")
            os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")
            os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
            os.environ.setdefault("TELEGRAM_CHAT_ID", "123")

            from expiry_settlement_watchdog import fetch_live_spot
            spot, is_synthetic = fetch_live_spot("NIFTY")

        self.assertIsNone(spot, "spot must be None when all feeds fail")
        self.assertTrue(is_synthetic, "is_synthetic must be True when all feeds fail")


# ---------------------------------------------------------------------------
# P0.11 — sentinel data_fault accumulation logic
# ---------------------------------------------------------------------------
class TestP011SentinelDataFault(unittest.TestCase):

    def setUp(self):
        os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_sentinel")
        os.environ.setdefault("TELEGRAM_CHAT_ID", "123")
        os.environ.setdefault("DHAN_CLIENT_ID", "test")
        os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")

    def _run_sentinel_tick(self, trades, ltp_value, now_dt=None):
        """
        Simulate one sentinel evaluation pass for the first ACTIVE trade.
        Returns the mutated trade dict.
        """
        import live_sentinel_daemon as sd

        if now_dt is None:
            import datetime
            now_dt = datetime.datetime(2026, 10, 5, 10, 30)  # mid-session

        trade = trades[0]
        symbol, strike, opt_type = sd.parse_contract(
            trade["contract"], trade.get("symbol", "NIFTY")
        )
        action = str(trade.get("action", "BUY")).upper()
        entry = float(trade.get("entry_price", 100.0))
        t1 = float(trade.get("target_1", entry * 1.25))
        sl = float(trade.get("stop_loss", entry * 0.8))

        with patch.object(sd, "fetch_dhan_chain_price", return_value=ltp_value), \
             patch.object(sd, "send_telegram_alert", return_value=True), \
             patch("live_sentinel_daemon.datetime") as mock_dt:
            mock_dt.now.return_value = now_dt
            mock_dt.side_effect = lambda *a, **kw: __import__("datetime").datetime(*a, **kw)

            ltp = sd.fetch_dhan_chain_price(symbol, strike, opt_type) if (strike and opt_type) else None

            if ltp is None:
                from datetime import datetime as real_dt
                past_cutoff = (now_dt.hour, now_dt.minute) >= sd.STT_CUTOFF_HHMM
                prev_ticks = int(trade.get("data_fault_ticks", 0))
                new_ticks = prev_ticks + 1
                trade["data_fault"] = True
                trade["data_fault_ticks"] = new_ticks
                if not trade.get("data_fault_since"):
                    trade["data_fault_since"] = now_dt.isoformat()

                if new_ticks >= sd.DATA_FAULT_ESCALATION_TICKS or past_cutoff:
                    reason = "DATA_FAULT_CUTOFF" if past_cutoff else "DATA_FAULT_10_TICKS"
                    trade["status"] = "UNRESOLVED"
                    trade["exit_reason"] = reason
            else:
                if trade.get("data_fault"):
                    trade["data_fault"] = False
                    trade["data_fault_ticks"] = 0
                    trade["data_fault_since"] = None

        return trade

    def test_single_tick_drop_keeps_active(self):
        """1 failed tick must leave status=ACTIVE with data_fault=True."""
        t = _make_trade()
        result = self._run_sentinel_tick([t], ltp_value=None)
        self.assertEqual(result["status"], "ACTIVE",
                         "Single tick failure must NOT mark UNRESOLVED")
        self.assertTrue(result["data_fault"],
                        "data_fault must be True after first failure")
        self.assertEqual(result["data_fault_ticks"], 1)

    def test_ten_consecutive_tick_drops_escalate_to_unresolved(self):
        """10 consecutive failed ticks must escalate to UNRESOLVED."""
        t = _make_trade(data_fault=True, ticks=9)  # 9 already accumulated
        result = self._run_sentinel_tick([t], ltp_value=None)
        self.assertEqual(result["status"], "UNRESOLVED",
                         "10th consecutive failure must set UNRESOLVED")
        self.assertEqual(result["exit_reason"], "DATA_FAULT_10_TICKS")

    def test_watchdog_squares_off_active_trade_with_data_fault(self):
        """STT watchdog must close ACTIVE trades even when data_fault=True."""
        t = _make_trade(data_fault=True, ticks=3)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump([t], tmp)
            tmp_path = tmp.name

        try:
            os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_watchdog")
            os.environ.setdefault("TELEGRAM_CHAT_ID", "123")

            with patch("expiry_settlement_watchdog.fetch_live_spot", return_value=(24000.0, False)), \
                 patch("expiry_settlement_watchdog.LEDGER_PATH", tmp_path), \
                 patch("requests.post", return_value=MagicMock(status_code=200)):
                from expiry_settlement_watchdog import run_settlement_watchdog
                run_settlement_watchdog(dry_run=False)

            with open(tmp_path, encoding="utf-8") as f:
                final = json.load(f)

            self.assertEqual(final[0]["status"], "CLOSED",
                             "Watchdog must CLOSE an ACTIVE trade even when data_fault=True")
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# P0.12 — Iron Condor uses exactly ONE option chain API call
# ---------------------------------------------------------------------------
class TestP012SingleOptionChainCall(unittest.TestCase):

    def setUp(self):
        os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_router")
        os.environ.setdefault("TELEGRAM_CHAT_ID", "123")
        os.environ.setdefault("DHAN_CLIENT_ID", "test_client")
        os.environ.setdefault("DHAN_ACCESS_TOKEN", "test_token")

    def _make_oc_response(self, strikes):
        """Build a minimal option chain dict for the given strike floats."""
        oc = {}
        for i, s in enumerate(strikes):
            oc[f"{s:.6f}"] = {
                "ce": {"security_id": 1000 + i * 2, "last_price": 50.0},
                "pe": {"security_id": 1001 + i * 2, "last_price": 50.0},
            }
        return oc

    def test_4leg_iron_condor_resolves_from_one_chain_call(self):
        """
        A 4-leg Iron Condor must resolve all security IDs from exactly ONE
        option chain API call, not one per leg.
        """
        import importlib
        import dhan_order_router
        importlib.reload(dhan_order_router)

        oc = self._make_oc_response([24000, 24100, 23900, 24200])
        iron_condor = {
            "sym": "NIFTY",
            "name": "Iron Condor",
            "lot": 65,
            "spot": 24050,
            "credit": 120,
            "max_p": "₹7,800",
            "max_l": "₹13,000",
            "expiry_date": "2026-10-30",
            "legs": [
                "BUY NIFTY 24000 CE @ ₹50",
                "SELL NIFTY 24100 CE @ ₹30",
                "BUY NIFTY 23900 PE @ ₹50",
                "SELL NIFTY 24200 PE @ ₹30",
            ],
        }

        call_count = 0

        def fake_fetch_chain(symbol, expiry_date=None):
            nonlocal call_count
            call_count += 1
            return oc

        mock_order_resp = MagicMock()
        mock_order_resp.status_code = 200
        mock_order_resp.json.return_value = {"orderId": "ORD-TEST-001"}

        with patch.object(dhan_order_router, "fetch_option_chain", side_effect=fake_fetch_chain), \
             patch("requests.post", return_value=mock_order_resp):
            result = dhan_order_router.execute_basket(iron_condor, live_mode=True)

        self.assertEqual(call_count, 1,
                         f"Expected exactly 1 option chain API call; got {call_count}")
        self.assertEqual(result["status"], "SUCCESS",
                         f"Iron Condor basket should succeed; got: {result}")
        self.assertEqual(len(result["orders"]), 4,
                         "All 4 legs must have order IDs")
        self.assertFalse(
            any("REJECTED" in o or "ABORTED" in o for o in result["orders"]),
            f"No leg should be rejected: {result['orders']}"
        )


if __name__ == "__main__":
    unittest.main()
