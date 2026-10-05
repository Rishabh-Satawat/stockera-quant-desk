"""Integration tests: auto_trade_hunter.py is regime-gated.

These tests exercise the hunter's actual code path, not regime_engine in isolation.
All tests run with NO credentials and NO live network calls.
"""

import os
import json
import sqlite3
import tempfile
import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

_IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> str:
    return datetime.datetime.now(tz=_IST).strftime("%Y-%m-%d")


def _make_db(tmp_path) -> str:
    db_path = str(tmp_path / "test.db")
    from db_init import init_db
    init_db(db_path)
    return db_path


def _base_analysis(sym, spot, regime_pcr, expiry="2026-10-30"):
    """Minimal analysis dict that analyze_option_chain_microstructure would return."""
    oc = {
        str(spot): {
            "ce": {"last_price": 100.0, "greeks": {}},
            "pe": {"last_price": 100.0, "greeks": {}},
        },
        str(spot - 100): {
            "ce": {"last_price": 50.0, "greeks": {}},
            "pe": {"last_price": 120.0, "greeks": {}},
        },
    }
    return {
        "spot": spot,
        "pcr_oi": regime_pcr,
        "max_pain": spot,
        "call_wall": spot + 200,
        "put_wall": spot - 200,
        "raw_oc": oc,
        "expiry": expiry,
        "is_synthetic": False,
    }


class TestHunterRegimeGate:
    """Hunter must consult regime_engine before emitting any trade signal."""

    def _run_hunt(
        self,
        tmp_path,
        analysis_map,  # sym → analysis dict
        regime_result,  # the dict compute_regime returns
        ledger_file=None,
        state_file=None,
    ):
        """Run hunt_market_once with the given mocked analysis + regime."""
        if ledger_file is None:
            ledger_file = str(tmp_path / "ledger.json")
        if state_file is None:
            state_file = str(tmp_path / "state.json")

        with (
            patch("auto_trade_hunter.is_market_open", return_value=(True, "OPEN")),
            patch("auto_trade_hunter.analyze_option_chain_microstructure") as mock_analyze,
            patch("auto_trade_hunter.compute_regime", return_value=regime_result),
            patch("auto_trade_hunter.send_telegram_alert"),
            patch("auto_trade_hunter.LEDGER_FILE", ledger_file),
            patch("auto_trade_hunter.STATE_FILE", state_file),
        ):
            mock_analyze.side_effect = lambda sym: analysis_map.get(sym, None)
            from auto_trade_hunter import hunt_market_once
            hunt_market_once()

        trades = []
        if os.path.exists(ledger_file):
            with open(ledger_file) as f:
                trades = json.load(f)
        return trades

    def test_hunter_does_not_emit_when_regime_forbids_bearish(self, tmp_path):
        """Hunter must NOT emit a NAKED bearish trade when regime says BULL/NORMAL_VOL."""
        # PCR < 0.85 → BEARISH_EXPANSION candidate
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=0.70)

        # Regime says BULL: playbook = BULL_CALL_SPREAD, not in _BEARISH_PLAYBOOKS
        regime = {
            "direction_score": 3,
            "direction_label": "BULL",
            "vol_regime": "NORMAL_VOL",
            "playbook": "BULL_CALL_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 0, (
            f"Expected no trades when regime forbids playbook; got {trades}"
        )

    def test_hunter_does_not_emit_when_regime_forbids_bullish(self, tmp_path):
        """Hunter must NOT emit a NAKED bullish trade when regime says BEAR."""
        # PCR > 1.15 → BULLISH_EXPANSION candidate
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=1.30)

        # Regime says BEAR: not in _BULLISH_PLAYBOOKS
        regime = {
            "direction_score": -3,
            "direction_label": "BEAR",
            "vol_regime": "NORMAL_VOL",
            "playbook": "BEAR_PUT_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 0, (
            f"Expected no trades when bullish candidate is in bearish regime; got {trades}"
        )

    def test_hunter_does_not_emit_hedged_when_regime_forbids_range(self, tmp_path):
        """Hunter must NOT emit a HEDGED condor when regime says STRONG_BULL.

        STRONG_BULL can still generate a directional NAKED trade via PB1;
        the key invariant is that no HEDGED condor fires.
        """
        # PCR ~1.0 → RANGE_BOUND candidate
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=1.00)

        # Regime says STRONG_BULL: playbook = LONG_CALL_SPREAD, not in _RANGE_PLAYBOOKS
        regime = {
            "direction_score": 6,
            "direction_label": "STRONG_BULL",
            "vol_regime": "LOW_VOL",
            "playbook": "LONG_CALL_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)
        hedged = [t for t in trades if t.get("book") == "HEDGED"]
        assert len(hedged) == 0, (
            f"Expected no HEDGED condor when regime is STRONG_BULL; got {hedged}"
        )

    def test_hunter_emits_when_regime_permits_bearish(self, tmp_path):
        """Hunter DOES emit a NAKED bearish trade when regime is BEAR/NORMAL_VOL."""
        # PCR < 0.85 → BEARISH_EXPANSION
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=0.70)

        # Regime says BEAR/NORMAL_VOL → BEAR_PUT_SPREAD is in _BEARISH_PLAYBOOKS
        regime = {
            "direction_score": -3,
            "direction_label": "BEAR",
            "vol_regime": "NORMAL_VOL",
            "playbook": "BEAR_PUT_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 1, (
            f"Expected 1 trade when regime permits bearish; got {trades}"
        )
        assert trades[0]["book"] == "NAKED"

    def test_hunter_emits_when_regime_permits_bullish(self, tmp_path):
        """Hunter DOES emit a NAKED bullish trade when regime is BULL/NORMAL_VOL."""
        # PCR > 1.15 → BULLISH_EXPANSION
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=1.30)

        # Regime says BULL/NORMAL_VOL → BULL_CALL_SPREAD is in _BULLISH_PLAYBOOKS
        regime = {
            "direction_score": 3,
            "direction_label": "BULL",
            "vol_regime": "NORMAL_VOL",
            "playbook": "BULL_CALL_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 1, (
            f"Expected 1 trade when regime permits bullish; got {trades}"
        )
        assert trades[0]["book"] == "NAKED"

    def test_hunter_emits_when_regime_permits_range(self, tmp_path):
        """Hunter DOES emit a HEDGED condor when regime is NEUTRAL/NORMAL_VOL."""
        # PCR ~1.0 → RANGE_BOUND
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=1.00)

        # Regime says NEUTRAL/NORMAL_VOL → IRON_CONDOR is in _RANGE_PLAYBOOKS
        regime = {
            "direction_score": 0,
            "direction_label": "NEUTRAL",
            "vol_regime": "NORMAL_VOL",
            "playbook": "IRON_CONDOR",
            "component_scores": {},
        }

        # PB6 uses wall-based strikes: short at walls, long 2 steps beyond
        spot = 22000.0
        step = 50
        call_wall = spot + 300   # 22300
        put_wall  = spot - 300   # 21700
        s_ce = 22300.0   # _atm(call_wall, step)
        b_ce = 22400.0   # s_ce + 2*step
        s_pe = 21700.0   # _atm(put_wall, step)
        b_pe = 21600.0   # s_pe - 2*step

        oc = {
            str(s_ce): {"ce": {"last_price": 80.0}, "pe": {"last_price": 0.0}},
            str(b_ce): {"ce": {"last_price": 30.0}, "pe": {"last_price": 0.0}},
            str(s_pe): {"ce": {"last_price": 0.0}, "pe": {"last_price": 75.0}},
            str(b_pe): {"ce": {"last_price": 0.0}, "pe": {"last_price": 25.0}},
        }
        analysis = {
            "spot": spot,
            "pcr_oi": 1.00,
            "max_pain": spot,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "raw_oc": oc,
            "expiry": "2026-10-30",
            "is_synthetic": False,
        }

        trades = self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 1, (
            f"Expected 1 hedged trade when regime permits iron condor; got {trades}"
        )
        assert trades[0]["book"] == "HEDGED"

    def test_regime_gate_logs_gated_reason(self, tmp_path, caplog):
        """Gated signals are logged with REGIME_GATED: prefix."""
        import logging

        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=0.70)
        regime = {
            "direction_score": 3,
            "direction_label": "BULL",
            "vol_regime": "NORMAL_VOL",
            "playbook": "BULL_CALL_SPREAD",
            "component_scores": {},
        }

        with caplog.at_level(logging.INFO, logger="auto_trade_hunter"):
            self._run_hunt(tmp_path, {"NIFTY": analysis}, regime)

        gated_logs = [r for r in caplog.records if "REGIME_GATED" in r.message]
        assert len(gated_logs) >= 1, "Expected at least one REGIME_GATED log entry"
        assert "BULL" in gated_logs[0].message or "BULL_CALL_SPREAD" in gated_logs[0].message


class TestColdStartVolProvisional:
    """With empty iv_history (< 20 sessions), hunter must still trade in vol_provisional mode."""

    def _run_hunt_with_regime(
        self,
        tmp_path,
        analysis_map,
        regime_result,
        ledger_file=None,
        state_file=None,
    ):
        if ledger_file is None:
            ledger_file = str(tmp_path / "ledger.json")
        if state_file is None:
            state_file = str(tmp_path / "state.json")

        with (
            patch("auto_trade_hunter.is_market_open", return_value=(True, "OPEN")),
            patch("auto_trade_hunter.analyze_option_chain_microstructure") as mock_analyze,
            patch("auto_trade_hunter.compute_regime", return_value=regime_result),
            patch("auto_trade_hunter.send_telegram_alert"),
            patch("auto_trade_hunter.LEDGER_FILE", ledger_file),
            patch("auto_trade_hunter.STATE_FILE", state_file),
        ):
            mock_analyze.side_effect = lambda sym: analysis_map.get(sym, None)
            from auto_trade_hunter import hunt_market_once
            hunt_market_once()

        trades = []
        if os.path.exists(ledger_file):
            with open(ledger_file) as f:
                trades = json.load(f)
        return trades

    def test_cold_start_bull_emits_trade_in_provisional_mode(self, tmp_path):
        """Empty iv_history: BULL direction with vol_provisional=True still produces a trade."""
        # PCR > 1.15 → BULLISH_EXPANSION candidate
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=1.30)

        # regime_engine now returns NORMAL_VOL with vol_provisional=True instead of UNKNOWN/NO_TRADE
        regime = {
            "direction_score": 3,
            "direction_label": "BULL",
            "vol_regime": "NORMAL_VOL",
            "vol_provisional": True,
            "playbook": "BULL_CALL_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt_with_regime(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 1, (
            f"Expected 1 trade in vol_provisional mode; got {trades}"
        )
        assert trades[0]["book"] == "NAKED"

    def test_cold_start_bear_emits_trade_in_provisional_mode(self, tmp_path):
        """Empty iv_history: BEAR direction with vol_provisional=True still produces a trade."""
        analysis = _base_analysis("NIFTY", 22000.0, regime_pcr=0.70)

        regime = {
            "direction_score": -3,
            "direction_label": "BEAR",
            "vol_regime": "NORMAL_VOL",
            "vol_provisional": True,
            "playbook": "BEAR_PUT_SPREAD",
            "component_scores": {},
        }

        trades = self._run_hunt_with_regime(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 1, (
            f"Expected 1 trade in vol_provisional mode; got {trades}"
        )
        assert trades[0]["book"] == "NAKED"

    def test_cold_start_neutral_emits_condor_in_provisional_mode(self, tmp_path):
        """Empty iv_history: NEUTRAL direction with vol_provisional=True emits a hedged condor."""
        spot = 22000.0
        # PB6 uses wall-based strikes: short at walls, long 2 steps beyond
        call_wall = spot + 300   # 22300
        put_wall  = spot - 300   # 21700
        s_ce = 22300.0
        b_ce = 22400.0
        s_pe = 21700.0
        b_pe = 21600.0

        oc = {
            str(s_ce): {"ce": {"last_price": 80.0}, "pe": {"last_price": 0.0}},
            str(b_ce): {"ce": {"last_price": 30.0}, "pe": {"last_price": 0.0}},
            str(s_pe): {"ce": {"last_price": 0.0}, "pe": {"last_price": 75.0}},
            str(b_pe): {"ce": {"last_price": 0.0}, "pe": {"last_price": 25.0}},
        }
        analysis = {
            "spot": spot,
            "pcr_oi": 1.00,
            "max_pain": spot,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "raw_oc": oc,
            "expiry": "2026-10-30",
            "is_synthetic": False,
        }

        regime = {
            "direction_score": 0,
            "direction_label": "NEUTRAL",
            "vol_regime": "NORMAL_VOL",
            "vol_provisional": True,
            "playbook": "IRON_CONDOR",
            "component_scores": {},
        }

        trades = self._run_hunt_with_regime(tmp_path, {"NIFTY": analysis}, regime)
        assert len(trades) == 1, (
            f"Expected 1 hedged condor in vol_provisional mode; got {trades}"
        )
        assert trades[0]["book"] == "HEDGED"

    def test_regime_engine_maps_unknown_to_normal_vol_provisional(self):
        """compute_regime returns vol_regime=NORMAL_VOL, vol_provisional=True when IVR=None."""
        import tempfile
        from db_init import init_db
        from regime_engine import compute_regime

        with tempfile.TemporaryDirectory() as td:
            db_path = td + "/test.db"
            init_db(db_path)
            # Empty db → IVR = None → vol_regime should map to NORMAL_VOL provisional
            result = compute_regime("NIFTY", "2026-10-30", 22000.0, db_path=db_path)

        assert result["vol_regime"] == "NORMAL_VOL", (
            f"Expected NORMAL_VOL for empty iv_history; got {result['vol_regime']}"
        )
        assert result["vol_provisional"] is True, (
            f"Expected vol_provisional=True for empty iv_history; got {result.get('vol_provisional')}"
        )
        assert result["playbook"] != "NO_TRADE", (
            f"Expected no NO_TRADE result in cold-start; got {result['playbook']}"
        )
