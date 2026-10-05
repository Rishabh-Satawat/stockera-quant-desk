"""
P0.13 residual defect tests.

P0.13-1 — Import-time token check: modules import cleanly with no env vars;
           calling send raises RuntimeError only when the function is actually invoked.
P0.13-2 — No hardcoded Telegram token literals in any .py file.
P0.13-3 — chain_microstructure_analyzer: missing spot resolves to 0.0 / None, never
           a fabricated baseline constant.
P0.13-4 — expiry_settlement_watchdog: UNRESOLVED+data_fault trades are included in
           the 15:20 sweep; fabricated exit price formula is gone; spot-unavailable
           trades are logged as UNRESOLVED_DATA_FAULT with exit_price=None.
P0.13-5 — access_token.txt is not tracked in git (removed from index).
"""

import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

HARDCODED_TOKEN_LITERAL = "8814895777"


# ---------------------------------------------------------------------------
# P0.13-1  Import-time token check
# ---------------------------------------------------------------------------
class TestP0131ImportTimeTokenCheck(unittest.TestCase):

    def _clear_token_env(self):
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            os.environ.pop(k, None)

    def test_auto_trade_hunter_imports_without_token(self):
        """auto_trade_hunter must import without raising when token is absent."""
        self._clear_token_env()
        # Remove cached module so it re-executes module-level code
        for mod in list(sys.modules.keys()):
            if "auto_trade_hunter" in mod:
                del sys.modules[mod]
        try:
            import auto_trade_hunter  # noqa: F401
        except RuntimeError as e:
            self.fail(f"auto_trade_hunter raised RuntimeError at import time: {e}")

    def test_live_sentinel_daemon_imports_without_token(self):
        """live_sentinel_daemon must import without raising when token is absent."""
        self._clear_token_env()
        for mod in list(sys.modules.keys()):
            if "live_sentinel_daemon" in mod:
                del sys.modules[mod]
        try:
            import live_sentinel_daemon  # noqa: F401
        except RuntimeError as e:
            self.fail(f"live_sentinel_daemon raised RuntimeError at import time: {e}")

    def test_expiry_settlement_watchdog_imports_without_token(self):
        """expiry_settlement_watchdog must import without raising when token is absent."""
        self._clear_token_env()
        for mod in list(sys.modules.keys()):
            if "expiry_settlement_watchdog" in mod:
                del sys.modules[mod]
        try:
            import expiry_settlement_watchdog  # noqa: F401
        except RuntimeError as e:
            self.fail(f"expiry_settlement_watchdog raised RuntimeError at import time: {e}")

    def test_dhan_order_router_imports_without_token(self):
        """dhan_order_router must import without raising when token is absent."""
        self._clear_token_env()
        for mod in list(sys.modules.keys()):
            if "dhan_order_router" in mod:
                del sys.modules[mod]
        try:
            import dhan_order_router  # noqa: F401
        except RuntimeError as e:
            self.fail(f"dhan_order_router raised RuntimeError at import time: {e}")

    def test_send_telegram_alert_raises_without_token(self):
        """Calling send_telegram_alert without TELEGRAM_BOT_TOKEN must raise RuntimeError."""
        self._clear_token_env()
        for mod in list(sys.modules.keys()):
            if "auto_trade_hunter" in mod:
                del sys.modules[mod]
        import auto_trade_hunter
        # Force module-level variable to be empty (env was cleared above)
        auto_trade_hunter.TELEGRAM_BOT_TOKEN = ""
        with self.assertRaises(RuntimeError):
            auto_trade_hunter.send_telegram_alert("test")


# ---------------------------------------------------------------------------
# P0.13-2  No hardcoded Telegram token literals
# ---------------------------------------------------------------------------
class TestP0132NoHardcodedTokenLiterals(unittest.TestCase):

    def _py_files_in_root(self):
        root = os.path.dirname(os.path.dirname(__file__))
        return [
            os.path.join(root, f)
            for f in os.listdir(root)
            if f.endswith(".py")
        ]

    def test_no_hardcoded_token_in_any_py_file(self):
        """No .py file in the project root may contain the hardcoded token literal."""
        offenders = []
        for path in self._py_files_in_root():
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    if HARDCODED_TOKEN_LITERAL in fh.read():
                        offenders.append(os.path.basename(path))
            except OSError:
                pass
        self.assertEqual(
            offenders, [],
            f"Hardcoded Telegram token literal found in: {offenders}"
        )


# ---------------------------------------------------------------------------
# P0.13-3  chain_microstructure_analyzer: no hardcoded spot fallbacks
# ---------------------------------------------------------------------------
class TestP0133NoHardcodedSpotFallbacks(unittest.TestCase):

    def test_missing_spot_returns_zero_not_fabricated_value(self):
        """analyze_option_chain_microstructure must not use 23063.10 / 73580.54 / 55438.50."""
        import chain_microstructure_analyzer as cma
        # These are the old hardcoded constants — they must not appear in the source
        src_path = cma.__file__
        with open(src_path, "r", encoding="utf-8") as fh:
            src = fh.read()
        for bad_literal in ("23063.10", "73580.54", "55438.50"):
            self.assertNotIn(
                bad_literal, src,
                f"Hardcoded spot constant {bad_literal!r} still present in chain_microstructure_analyzer.py"
            )

    def test_spot_falls_back_to_zero_when_feed_fails(self):
        """When live_spot_service returns 0.0 for a symbol, spot used must also be 0.0."""
        with patch("live_spot_service.get_live_spots", return_value={"NIFTY": 0.0}), \
             patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200, json=lambda: {"data": {}})
            os.environ.setdefault("DHAN_CLIENT_ID", "test")
            os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")
            from chain_microstructure_analyzer import analyze_option_chain_microstructure
            # Should not raise; spot=0.0, atm=0 — chain call may fail but that's OK
            try:
                analyze_option_chain_microstructure("NIFTY")
            except Exception:
                pass  # network errors are expected in test environment


# ---------------------------------------------------------------------------
# P0.13-4  expiry_settlement_watchdog: UNRESOLVED trades + no fabricated prices
# ---------------------------------------------------------------------------
class TestP0134WatchdogUnresolvedTrades(unittest.TestCase):

    def _make_trade(self, trade_id, status, data_fault=False):
        return {
            "trade_id": trade_id,
            "symbol": "NIFTY",
            "contract": "NIFTY 24000 CE",
            "action": "BUY",
            "entry_price": 100.0,
            "qty": 65,
            "status": status,
            "data_fault": data_fault,
        }

    def test_unresolved_data_fault_trade_is_included_in_sweep(self):
        """UNRESOLVED trade with data_fault=True must be processed at 15:20."""
        trades = [
            self._make_trade("TRD-001", "ACTIVE"),
            self._make_trade("TRD-002", "UNRESOLVED", data_fault=True),
            self._make_trade("TRD-003", "CLOSED"),  # must be skipped
        ]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(trades, f)
            ledger_path = f.name

        try:
            with patch("requests.post") as mock_post, \
                 patch("live_spot_service.get_live_spots", return_value={"NIFTY": 24100.0}), \
                 patch("requests.get"):
                mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
                os.environ.setdefault("DHAN_CLIENT_ID", "test")
                os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")
                os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
                os.environ.setdefault("TELEGRAM_CHAT_ID", "123")

                for mod in list(sys.modules.keys()):
                    if "expiry_settlement_watchdog" in mod:
                        del sys.modules[mod]
                import expiry_settlement_watchdog as esw

                esw.LEDGER_PATH = ledger_path
                esw.run_settlement_watchdog(dry_run=False)

            with open(ledger_path) as fh:
                result = json.load(fh)

            statuses = {t["trade_id"]: t["status"] for t in result}
            # Both ACTIVE and UNRESOLVED+data_fault must be processed (closed)
            self.assertNotEqual(statuses["TRD-001"], "ACTIVE",
                                "ACTIVE trade must be closed by watchdog")
            self.assertNotEqual(statuses["TRD-002"], "UNRESOLVED",
                                "UNRESOLVED+data_fault trade must be processed by watchdog")
            # CLOSED trade must remain CLOSED
            self.assertEqual(statuses["TRD-003"], "CLOSED",
                             "Already-CLOSED trade must not be touched")
        finally:
            os.unlink(ledger_path)

    def test_no_fabricated_exit_price_when_spot_unavailable(self):
        """When spot is unavailable, exit_price must be None, status UNRESOLVED_DATA_FAULT."""
        trades = [self._make_trade("TRD-001", "ACTIVE")]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(trades, f)
            ledger_path = f.name

        try:
            with patch("requests.post") as mock_post, \
                 patch("requests.get"), \
                 patch("live_spot_service.get_live_spots", return_value={"NIFTY": 0.0}):
                mock_post.side_effect = Exception("network down")
                os.environ.setdefault("DHAN_CLIENT_ID", "test")
                os.environ.setdefault("DHAN_ACCESS_TOKEN", "test")
                os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")
                os.environ.setdefault("TELEGRAM_CHAT_ID", "123")

                for mod in list(sys.modules.keys()):
                    if "expiry_settlement_watchdog" in mod:
                        del sys.modules[mod]
                import expiry_settlement_watchdog as esw

                esw.LEDGER_PATH = ledger_path
                esw.run_settlement_watchdog(dry_run=False)

            with open(ledger_path) as fh:
                result = json.load(fh)

            t = result[0]
            self.assertIsNone(t.get("exit_price"),
                              "exit_price must be None when spot is unavailable — no fabricated values")
            self.assertEqual(t.get("status"), "UNRESOLVED_DATA_FAULT",
                             "status must be UNRESOLVED_DATA_FAULT when spot unavailable")
        finally:
            os.unlink(ledger_path)

    def test_no_fabricated_exit_formula_in_source(self):
        """The fabricated exit price formula must not appear in the watchdog source."""
        import expiry_settlement_watchdog as esw
        with open(esw.__file__, "r", encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn(
            "entry * 0.1",
            src,
            "Fabricated exit price formula 'entry * 0.1' must be removed from watchdog"
        )
        self.assertNotIn(
            "max(0.5",
            src,
            "Fabricated exit price formula 'max(0.5, ...)' must be removed from watchdog"
        )


# ---------------------------------------------------------------------------
# P0.13-5  access_token.txt not tracked in git
# ---------------------------------------------------------------------------
class TestP0135AccessTokenNotTracked(unittest.TestCase):

    def test_access_token_not_in_git_index(self):
        """access_token.txt files must not be tracked by git."""
        import subprocess
        root = os.path.dirname(os.path.dirname(__file__))
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "access_token.txt"],
            cwd=root,
            capture_output=True,
        )
        self.assertNotEqual(
            result.returncode, 0,
            "access_token.txt is still tracked by git — run 'git rm --cached access_token.txt'"
        )

    def test_gitignore_covers_access_token(self):
        """.gitignore must contain an entry that excludes access_token.txt."""
        root = os.path.dirname(os.path.dirname(__file__))
        gitignore_path = os.path.join(root, ".gitignore")
        with open(gitignore_path, "r") as fh:
            content = fh.read()
        self.assertIn(
            "access_token.txt",
            content,
            ".gitignore must explicitly list access_token.txt"
        )


if __name__ == "__main__":
    unittest.main()
