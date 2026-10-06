"""Unit tests for playbook_triggers.py — PB1, PB2, PB6 gate logic."""

from __future__ import annotations

import pytest
from datetime import date
from playbook_triggers import (
    PlaybookSignal,
    evaluate_pb1,
    evaluate_pb2,
    evaluate_pb6,
    evaluate_all_playbooks,
    _atm,
    _compute_pin_score,
    _compute_dte,
)

# Reference date that makes "2026-10-30" exactly 7 DTE (within gate)
_REF_DATE = date(2026, 10, 23)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _regime(direction="BULL", vol="NORMAL_VOL", direction_score=3, provisional=False):
    return {
        "direction_label": direction,
        "vol_regime": vol,
        "direction_score": direction_score,
        "vol_provisional": provisional,
        "playbook": "BULL_CALL_SPREAD",
        "component_scores": {},
    }


def _analysis(spot=22000.0, max_pain=22000.0, call_wall=22500.0, put_wall=21500.0,
              pcr=1.0, expiry="2026-10-30"):
    return {
        "spot": spot,
        "max_pain": max_pain,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "pcr_oi": pcr,
        "expiry": expiry,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestAtm:
    def test_rounds_to_step(self):
        assert _atm(22010.0, 50) == 22000.0
        # 22025 / 50 = 440.5 → banker's round to 440 (even) → 22000
        assert _atm(22025.0, 50) == 22000.0
        assert _atm(22050.0, 50) == 22050.0

    def test_sensex_step_100(self):
        # 74050 / 100 = 740.5 → banker's round to 740 (even) → 74000
        assert _atm(74050.0, 100) == 74000.0

    def test_non_half_rounds_up(self):
        assert _atm(22060.0, 50) == 22050.0
        assert _atm(22076.0, 50) == 22100.0


class TestPinScore:
    def test_spot_at_max_pain_gives_1(self):
        score = _compute_pin_score(22000.0, 22000.0, 22500.0, 21500.0)
        assert score == 1.0

    def test_spot_at_call_wall_gives_0(self):
        score = _compute_pin_score(22500.0, 22000.0, 22500.0, 21500.0)
        assert score == 0.0

    def test_midpoint(self):
        score = _compute_pin_score(22250.0, 22000.0, 22500.0, 21500.0)
        assert 0.4 < score < 0.6

    def test_inverted_walls_uses_fallback_half_range(self):
        # call_wall < put_wall → half_range = 1.0 fallback
        # spot == max_pain → distance = 0 → score = 1.0 (not 0)
        score = _compute_pin_score(22000.0, 22000.0, 21000.0, 22000.0)
        assert score == 1.0  # spot == max_pain always gives 1.0


# ──────────────────────────────────────────────────────────────────────────────
# PB1: Directional Trend Continuation
# ──────────────────────────────────────────────────────────────────────────────

class TestPB1:
    def test_bull_returns_signal(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22100.0), _regime("BULL"), step=50,
                           or_high=22050.0, or_low=21950.0, vwap=22000.0)
        assert sig is not None
        assert sig.playbook_id == "PB1"
        assert sig.direction == "BULL"
        assert sig.instrument_type == "ATM_CALL"

    def test_bear_returns_signal(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=21900.0), _regime("BEAR", direction_score=-3),
                           step=50, or_high=22000.0, or_low=21950.0, vwap=22000.0)
        assert sig is not None
        assert sig.direction == "BEAR"
        assert sig.instrument_type == "ATM_PUT"

    def test_neutral_returns_none(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22000.0), _regime("NEUTRAL", direction_score=0),
                           step=50, or_high=22050.0, or_low=21950.0, vwap=22000.0)
        assert sig is None

    def test_or_gate_fails_bull(self):
        # spot below or_high → gate fails
        sig = evaluate_pb1("NIFTY", _analysis(spot=22000.0), _regime("BULL"), step=50,
                           or_high=22100.0, vwap=22000.0)
        assert sig is None

    def test_or_gate_fails_bear(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22000.0), _regime("BEAR", direction_score=-3),
                           step=50, or_low=21900.0, vwap=22100.0)
        assert sig is None

    def test_vwap_gate_fails_bull(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22100.0), _regime("BULL"), step=50,
                           or_high=22050.0, vwap=22200.0)  # spot below vwap
        assert sig is None

    def test_vwap_gate_fails_bear(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=21900.0), _regime("BEAR", direction_score=-3),
                           step=50, or_low=21950.0, vwap=21800.0)  # spot above vwap
        assert sig is None

    def test_or_unavailable_partial_credit(self):
        # No or_high/or_low: gate passes with partial sub_score
        sig = evaluate_pb1("NIFTY", _analysis(spot=22100.0), _regime("BULL"), step=50,
                           vwap=22000.0)  # no or_high
        assert sig is not None
        assert sig.sub_scores.get("or_break") == 0.5

    def test_vwap_unavailable_partial_credit(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22100.0), _regime("BULL"), step=50,
                           or_high=22050.0)  # no vwap
        assert sig is not None
        assert sig.sub_scores.get("vwap_alignment") == 0.5

    def test_strong_bull_normalises_to_bull(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22100.0), _regime("STRONG_BULL", direction_score=6),
                           step=50, or_high=22050.0, vwap=22000.0)
        assert sig is not None
        assert sig.direction == "BULL"

    def test_strong_bear_normalises_to_bear(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=21900.0), _regime("STRONG_BEAR", direction_score=-6),
                           step=50, or_low=21950.0, vwap=22000.0)
        assert sig is not None
        assert sig.direction == "BEAR"

    def test_atm_strike_assigned(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22075.0), _regime("BULL"), step=50,
                           or_high=22050.0, vwap=22000.0)
        assert sig is not None
        assert sig.atm_strike == 22100.0  # rounded to nearest 50

    def test_vol_provisional_propagated(self):
        sig = evaluate_pb1("NIFTY", _analysis(spot=22100.0),
                           _regime("BULL", provisional=True), step=50,
                           or_high=22050.0, vwap=22000.0)
        assert sig is not None
        assert sig.vol_provisional is True


# ──────────────────────────────────────────────────────────────────────────────
# PB2: Mean Reversion / Max Pain Pinning
# ──────────────────────────────────────────────────────────────────────────────

class TestPB2:
    def test_neutral_near_max_pain_triggers(self):
        sig = evaluate_pb2("NIFTY", _analysis(spot=22000.0, max_pain=22020.0),
                           _regime("NEUTRAL", direction_score=0), step=50)
        assert sig is not None
        assert sig.playbook_id == "PB2"
        assert sig.direction == "NEUTRAL"
        assert sig.instrument_type == "IRON_BUTTERFLY"

    def test_non_neutral_returns_none(self):
        sig = evaluate_pb2("NIFTY", _analysis(spot=22000.0, max_pain=22000.0),
                           _regime("BULL"), step=50)
        assert sig is None

    def test_distance_gate_fails(self):
        # spot 200 pts from max_pain > default 100
        sig = evaluate_pb2("NIFTY", _analysis(spot=22200.0, max_pain=22000.0),
                           _regime("NEUTRAL", direction_score=0), step=50)
        assert sig is None

    def test_pin_score_gate_fails(self):
        # spot exactly at call_wall → pin_score = 0 < 0.5
        sig = evaluate_pb2("NIFTY",
                           _analysis(spot=22500.0, max_pain=21000.0,
                                     call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", direction_score=0), step=50)
        assert sig is None

    def test_strike_structure(self):
        sig = evaluate_pb2("NIFTY", _analysis(spot=22000.0, max_pain=22000.0),
                           _regime("NEUTRAL", direction_score=0), step=50)
        assert sig is not None
        # center = 22000; short 1 step out, long 3 steps out
        assert sig.short_strike_ce == 22050.0
        assert sig.short_strike_pe == 21950.0
        assert sig.long_strike_ce == 22150.0
        assert sig.long_strike_pe == 21850.0

    def test_reason_contains_max_pain(self):
        sig = evaluate_pb2("NIFTY", _analysis(spot=22000.0, max_pain=22000.0),
                           _regime("NEUTRAL", direction_score=0), step=50)
        assert "max_pain" in sig.reason

    def test_custom_min_pin_score(self):
        # With a very high threshold: should fail
        sig = evaluate_pb2("NIFTY", _analysis(spot=22000.0, max_pain=22000.0),
                           _regime("NEUTRAL", direction_score=0), step=50,
                           min_pin_score=0.99)
        # spot == max_pain → pin_score = 1.0 → passes even at 0.99
        assert sig is not None

    def test_custom_max_distance(self):
        # 200 pt distance but 300 allowed
        sig = evaluate_pb2("NIFTY", _analysis(spot=22200.0, max_pain=22000.0),
                           _regime("NEUTRAL", direction_score=0), step=50,
                           max_distance_pts=300.0, min_pin_score=0.0)
        assert sig is not None


# ──────────────────────────────────────────────────────────────────────────────
# PB6: Steady-State 0DTE Theta Condor
# ──────────────────────────────────────────────────────────────────────────────

class TestPB6:
    def test_normal_vol_in_corridor_triggers(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is not None
        assert sig.playbook_id == "PB6"
        assert sig.instrument_type == "IRON_CONDOR"

    def test_low_vol_triggers(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="LOW_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is not None

    def test_elevated_vol_returns_none(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="ELEVATED_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is None

    def test_high_vol_returns_none(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="HIGH_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is None

    def test_spot_outside_corridor_returns_none(self):
        # spot above call_wall
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22600.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is None

    def test_spot_at_call_wall_returns_none(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22500.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is None

    def test_strike_structure(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert sig is not None
        assert sig.short_strike_ce == 22500.0
        assert sig.short_strike_pe == 21500.0
        assert sig.long_strike_ce == 22600.0
        assert sig.long_strike_pe == 21400.0

    def test_reason_contains_corridor(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0), step=50,
                           _reference_date=_REF_DATE)
        assert "corridor" in sig.reason.lower()

    def test_vol_provisional_propagated(self):
        sig = evaluate_pb6("NIFTY",
                           _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0),
                           _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0, provisional=True),
                           step=50, _reference_date=_REF_DATE)
        assert sig is not None
        assert sig.vol_provisional is True


# ──────────────────────────────────────────────────────────────────────────────
# evaluate_all_playbooks
# ──────────────────────────────────────────────────────────────────────────────

class TestEvaluateAllPlaybooks:
    def test_returns_list(self):
        result = evaluate_all_playbooks(
            "NIFTY",
            _analysis(spot=22000.0),
            _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0),
            step=50,
        )
        assert isinstance(result, list)

    def test_bull_regime_can_trigger_pb1(self):
        result = evaluate_all_playbooks(
            "NIFTY",
            _analysis(spot=22100.0),
            _regime("BULL", direction_score=3),
            step=50,
            or_high=22050.0,
            vwap=22000.0,
        )
        pb_ids = [s.playbook_id for s in result]
        assert "PB1" in pb_ids

    def test_neutral_can_trigger_pb2_and_pb6(self):
        result = evaluate_all_playbooks(
            "NIFTY",
            _analysis(spot=22000.0, max_pain=22000.0, call_wall=22500.0, put_wall=21500.0),
            _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0),
            step=50,
            _reference_date=_REF_DATE,
        )
        pb_ids = [s.playbook_id for s in result]
        assert "PB2" in pb_ids
        assert "PB6" in pb_ids

    def test_no_triggers_returns_empty_list(self):
        # Elevated vol (kills PB6), BULL kills PB2, OR gate fails kills PB1
        result = evaluate_all_playbooks(
            "NIFTY",
            _analysis(spot=22000.0),
            _regime("BULL", vol="ELEVATED_VOL", direction_score=3),
            step=50,
            or_high=22100.0,  # spot < or_high
            vwap=21000.0,
        )
        assert result == []

    def test_symbol_propagated_to_signals(self):
        result = evaluate_all_playbooks(
            "SENSEX",
            _analysis(spot=74000.0, call_wall=75000.0, put_wall=73000.0),
            _regime("NEUTRAL", vol="NORMAL_VOL", direction_score=0),
            step=100,
        )
        for sig in result:
            assert sig.symbol == "SENSEX"
