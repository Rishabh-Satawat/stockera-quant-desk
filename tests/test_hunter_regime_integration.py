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
        """Hunter must NOT emit a HEDGED condor when regime forbids range-bound playbooks."""
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
        assert len(trades) == 0, (
            f"Expected no hedged trade when regime forbids IRON_CONDOR; got {trades}"
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

        # Need a richer OC for condor legs (4 strikes: atm±100, atm±200 for NIFTY step=50 → actually ±100, ±200)
        spot = 22000.0
        step = 50
        atm = int(round(spot / step) * step)  # 22000
        s_ce = atm + 2 * step   # 22100
        b_ce = atm + 4 * step   # 22200
        s_pe = atm - 2 * step   # 21900
        b_pe = atm - 4 * step   # 21800

        oc = {
            str(float(s_ce)): {"ce": {"last_price": 80.0}, "pe": {"last_price": 0.0}},
            str(float(b_ce)): {"ce": {"last_price": 30.0}, "pe": {"last_price": 0.0}},
            str(float(s_pe)): {"ce": {"last_price": 0.0}, "pe": {"last_price": 75.0}},
            str(float(b_pe)): {"ce": {"last_price": 0.0}, "pe": {"last_price": 25.0}},
        }
        analysis = {
            "spot": spot,
            "pcr_oi": 1.00,
            "max_pain": spot,
            "call_wall": spot + 300,
            "put_wall": spot - 300,
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
