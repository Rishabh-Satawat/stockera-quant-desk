"""Phase 2 Alpha Expansion — unit tests.

Test A: GEX zone routing — positive zone boosts PB2/PB6, negative zone boosts PB1/PB4.
Test B: No-Chase filter blocks PB1 when spot is > 1.2×ATR from VWAP.
Test C: Daily loss circuit breaker halts trade generation after 2 consecutive stop-losses.
Test D: PB4 triggers only on 0DTE after 13:00 IST when Gamma Flip is breached.
"""

from __future__ import annotations

import datetime
import pytest
from playbook_triggers import PlaybookSignal, evaluate_pb4_gamma_blast
from scoring_engine import score_candidate, _score_gex_zone
from auto_trade_hunter import _is_chasing_move, _is_low_quality_chop, _is_circuit_breaker_active


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_signal(
    playbook_id="PB1",
    symbol="NIFTY",
    direction="BULL",
    vol_regime="NORMAL_VOL",
    vol_provisional=False,
    direction_score=5,
    spot=22000.0,
    call_wall=22500.0,
    put_wall=21500.0,
    pcr=1.1,
    max_pain=22000.0,
    step=50,
    gex_zone="UNKNOWN",
    gamma_flip_level=None,
    volume_accelerating=False,
    sub_scores=None,
):
    return PlaybookSignal(
        playbook_id=playbook_id,
        symbol=symbol,
        direction=direction,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type="ATM_CALL" if playbook_id in ("PB1", "PB4") else "IRON_CONDOR",
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        max_pain=max_pain,
        direction_score=direction_score,
        step=step,
        gex_zone=gex_zone,
        gamma_flip_level=gamma_flip_level,
        volume_accelerating=volume_accelerating,
        sub_scores=sub_scores or {},
        reason="test",
    )


def _make_analysis(
    spot=22000.0,
    call_wall=22500.0,
    put_wall=21500.0,
    max_pain=22000.0,
    pcr=1.1,
    expiry="2026-10-06",
):
    return {
        "symbol": "NIFTY",
        "expiry": expiry,
        "spot": spot,
        "pcr_oi": pcr,
        "max_pain": max_pain,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "raw_oc": {},
        "is_synthetic": False,
    }


def _make_regime(direction_score=3, vol_regime="NORMAL_VOL"):
    direction_map = {
        range(5, 8): "STRONG_BULL",
        range(2, 5): "BULL",
        range(-1, 2): "NEUTRAL",
        range(-4, -1): "BEAR",
    }
    if direction_score >= 5:
        label = "STRONG_BULL"
    elif direction_score >= 2:
        label = "BULL"
    elif direction_score >= -1:
        label = "NEUTRAL"
    elif direction_score >= -4:
        label = "BEAR"
    else:
        label = "STRONG_BEAR"
    return {
        "direction_label": label,
        "direction_score": direction_score,
        "vol_regime": vol_regime,
        "vol_provisional": False,
        "playbook": "BULL_CALL_SPREAD",
    }


def _make_gex_data(
    total_net_gex=-1_000_000.0,
    gamma_flip_level=22000.0,
):
    return {
        "total_net_gex": total_net_gex,
        "gamma_flip_level": gamma_flip_level,
        "max_pain": 21950.0,
        "pin_score": 0.0,
        "per_strike_gex": [],
        "gex_dealer_assumption": "long_call_short_put",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Test A: GEX zone routing
# ──────────────────────────────────────────────────────────────────────────────

class TestGexZoneRouting:
    """GEX zone should boost PB2/PB6 in POSITIVE zone and PB1/PB4 in NEGATIVE zone."""

    def test_positive_gex_boosts_pb6(self):
        """PB6 Iron Condor in POSITIVE GEX zone earns full GEX bonus."""
        sig = _make_signal(playbook_id="PB6", direction="NEUTRAL", gex_zone="POSITIVE")
        bonus = _score_gex_zone(sig)
        assert bonus == 8.0

    def test_positive_gex_boosts_pb2(self):
        """PB2 Mean Reversion in POSITIVE GEX zone earns full GEX bonus."""
        sig = _make_signal(playbook_id="PB2", direction="NEUTRAL", gex_zone="POSITIVE")
        bonus = _score_gex_zone(sig)
        assert bonus == 8.0

    def test_negative_gex_boosts_pb1(self):
        """PB1 Directional in NEGATIVE GEX zone earns full GEX bonus."""
        sig = _make_signal(playbook_id="PB1", direction="BULL", gex_zone="NEGATIVE")
        bonus = _score_gex_zone(sig)
        assert bonus == 8.0

    def test_negative_gex_boosts_pb4(self):
        """PB4 Gamma Blast in NEGATIVE GEX zone earns full GEX bonus."""
        sig = _make_signal(
            playbook_id="PB4", direction="BULL", gex_zone="NEGATIVE",
            sub_scores={"rr": 3.0},
        )
        bonus = _score_gex_zone(sig)
        assert bonus == 8.0

    def test_near_flip_earns_partial_bonus(self):
        """NEAR_FLIP zone earns partial bonus for any playbook."""
        sig = _make_signal(playbook_id="PB1", direction="BULL", gex_zone="NEAR_FLIP")
        bonus = _score_gex_zone(sig)
        assert bonus == 3.0

    def test_unknown_gex_earns_zero(self):
        """UNKNOWN GEX zone adds no bonus (preserves backward compatibility)."""
        sig = _make_signal(playbook_id="PB1", direction="BULL", gex_zone="UNKNOWN")
        bonus = _score_gex_zone(sig)
        assert bonus == 0.0

    def test_misaligned_gex_earns_zero(self):
        """POSITIVE zone gives no bonus to PB1 (misaligned: dealers dampen, not amplify)."""
        sig = _make_signal(playbook_id="PB1", direction="BULL", gex_zone="POSITIVE")
        bonus = _score_gex_zone(sig)
        assert bonus == 0.0

    def test_gex_bonus_boosts_total_score(self):
        """Total score_candidate score is higher with aligned GEX zone than UNKNOWN.
        Use a deliberately weak signal (direction_score=1, far from walls) so neither
        version is capped at 100 and the 8-pt GEX bonus is visible.
        """
        sig_aligned = _make_signal(
            playbook_id="PB1", direction="BULL", gex_zone="NEGATIVE",
            direction_score=1, pcr=0.9, spot=22000.0,
            call_wall=23000.0, put_wall=21000.0,
        )
        sig_unknown = _make_signal(
            playbook_id="PB1", direction="BULL", gex_zone="UNKNOWN",
            direction_score=1, pcr=0.9, spot=22000.0,
            call_wall=23000.0, put_wall=21000.0,
        )
        result_aligned = score_candidate(sig_aligned)
        result_unknown = score_candidate(sig_unknown)
        assert result_aligned["score"] > result_unknown["score"]

    def test_gex_dealer_assumption_in_breakdown(self):
        """score_candidate breakdown includes gex_dealer_assumption."""
        sig = _make_signal(playbook_id="PB1", direction="BULL")
        result = score_candidate(sig)
        assert result["breakdown"]["gex_dealer_assumption"] == "long_call_short_put"

    def test_gex_zone_capped_at_25_max(self):
        """Pillar 2 cannot exceed 25 even with GEX bonus added."""
        sig = _make_signal(
            playbook_id="PB1", direction="BULL", gex_zone="NEGATIVE",
            pcr=1.3, spot=22400.0, call_wall=22500.0, put_wall=21500.0,
        )
        result = score_candidate(sig)
        assert result["breakdown"]["microstructure"] <= 25.0


# ──────────────────────────────────────────────────────────────────────────────
# Test B: No-Chase filter
# ──────────────────────────────────────────────────────────────────────────────

class TestNoChasFilter:
    """No-Chase Rule blocks PB1 when spot is > 1.2×ATR(15m) away from VWAP."""

    def test_chase_detected_when_extended(self):
        """spot = 22200, vwap = 22000, atr = 100 → distance = 200 > 1.2×100 = 120."""
        assert _is_chasing_move(spot=22200.0, vwap=22000.0, atr_15m=100.0) is True

    def test_no_chase_within_threshold(self):
        """spot = 22100, vwap = 22000, atr = 100 → distance = 100 ≤ 120."""
        assert _is_chasing_move(spot=22100.0, vwap=22000.0, atr_15m=100.0) is False

    def test_exact_boundary_no_chase(self):
        """Exactly at 1.2× threshold is not a chase (uses strictly-greater-than)."""
        assert _is_chasing_move(spot=22120.0, vwap=22000.0, atr_15m=100.0) is False

    def test_chase_from_below(self):
        """Negative side: spot much below vwap also triggers chase gate."""
        assert _is_chasing_move(spot=21700.0, vwap=22000.0, atr_15m=100.0) is True

    def test_fail_open_zero_vwap(self):
        """Zero VWAP → data unavailable → fail-open (return False)."""
        assert _is_chasing_move(spot=22200.0, vwap=0.0, atr_15m=100.0) is False

    def test_fail_open_zero_atr(self):
        """Zero ATR → data unavailable → fail-open (return False)."""
        assert _is_chasing_move(spot=22200.0, vwap=22000.0, atr_15m=0.0) is False

    def test_chop_filter_blocks_naked_in_tight_range(self):
        """Tight range < 0.3× expected + declining volume → block naked buying."""
        block_naked, block_condor = _is_low_quality_chop(
            range_15m=10.0,
            expected_daily_range=100.0,
            volume_declining=True,
            bollinger_squeeze=False,
        )
        assert block_naked is True
        assert block_condor is False

    def test_chop_filter_no_block_when_volume_rising(self):
        """Tight range but volume is rising → no block (momentum may be building)."""
        block_naked, _block_condor = _is_low_quality_chop(
            range_15m=10.0,
            expected_daily_range=100.0,
            volume_declining=False,
            bollinger_squeeze=False,
        )
        assert block_naked is False

    def test_squeeze_filter_blocks_iron_condor(self):
        """Bollinger squeeze → block Iron Condor (risk of explosive expansion)."""
        _block_naked, block_condor = _is_low_quality_chop(
            range_15m=50.0,
            expected_daily_range=100.0,
            volume_declining=False,
            bollinger_squeeze=True,
        )
        assert block_condor is True


# ──────────────────────────────────────────────────────────────────────────────
# Test C: Daily loss circuit breaker
# ──────────────────────────────────────────────────────────────────────────────

class TestCircuitBreaker:
    """Circuit breaker halts all signals after 2 consecutive stop-losses today."""

    TODAY_TAG = "TRD-20261006"

    def _closed_trade(self, trade_id, exit_reason, exit_time="15:00:00"):
        return {
            "trade_id": f"{self.TODAY_TAG}-{trade_id}",
            "status": "CLOSED",
            "exit_reason": exit_reason,
            "exit_time": exit_time,
            "source": "LIVE",
        }

    def test_two_consecutive_sl_hits_activates_breaker(self):
        trades = [
            self._closed_trade("NAKED-01", "SL_HIT", "12:00:00"),
            self._closed_trade("NAKED-02", "SL_HIT", "13:30:00"),
        ]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is True

    def test_one_sl_no_breaker(self):
        trades = [self._closed_trade("NAKED-01", "SL_HIT")]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is False

    def test_two_profitable_exits_no_breaker(self):
        trades = [
            self._closed_trade("NAKED-01", "TARGET_1", "12:00:00"),
            self._closed_trade("NAKED-02", "TARGET_2", "13:30:00"),
        ]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is False

    def test_one_sl_one_target_no_breaker(self):
        """Only the 2 most-recent closes matter; mixed result = no breaker."""
        trades = [
            self._closed_trade("NAKED-01", "TARGET_1", "12:00:00"),
            self._closed_trade("NAKED-02", "SL_HIT", "13:30:00"),
        ]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is False

    def test_simulated_trades_ignored(self):
        """SIMULATED source trades should not count toward the circuit breaker."""
        trades = [
            {
                "trade_id": f"{self.TODAY_TAG}-SIM-01",
                "status": "CLOSED",
                "exit_reason": "SL_HIT",
                "exit_time": "12:00:00",
                "source": "SIMULATED",
            },
            {
                "trade_id": f"{self.TODAY_TAG}-SIM-02",
                "status": "CLOSED",
                "exit_reason": "SL_HIT",
                "exit_time": "13:00:00",
                "source": "SIMULATED",
            },
        ]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is False

    def test_empty_trades_no_breaker(self):
        assert _is_circuit_breaker_active([], self.TODAY_TAG) is False

    def test_yesterday_sl_hits_not_counted(self):
        """Yesterday's stop-losses should not activate today's circuit breaker."""
        trades = [
            {
                "trade_id": "TRD-20261005-NAKED-01",
                "status": "CLOSED",
                "exit_reason": "SL_HIT",
                "exit_time": "13:00:00",
                "source": "LIVE",
            },
            {
                "trade_id": "TRD-20261005-NAKED-02",
                "status": "CLOSED",
                "exit_reason": "SL_HIT",
                "exit_time": "14:00:00",
                "source": "LIVE",
            },
        ]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is False

    def test_stop_keyword_variants(self):
        """exit_reason containing 'STOP' (not just 'SL') also triggers breaker."""
        trades = [
            self._closed_trade("NAKED-01", "STOP_LOSS", "12:00:00"),
            self._closed_trade("NAKED-02", "STOP_LOSS", "13:30:00"),
        ]
        assert _is_circuit_breaker_active(trades, self.TODAY_TAG) is True


# ──────────────────────────────────────────────────────────────────────────────
# Test D: PB4 Gamma Blast trigger conditions
# ──────────────────────────────────────────────────────────────────────────────

class TestPB4GammaBlast:
    """PB4 must trigger ONLY on 0DTE after 13:00 IST when Gamma Flip is breached."""

    _EXPIRY_TODAY = "2026-10-06"   # matches today_tag in session

    def _base_analysis(self, spot=22010.0):
        return _make_analysis(
            spot=spot,
            call_wall=22500.0,
            put_wall=21500.0,
            expiry=self._EXPIRY_TODAY,
        )

    def _base_regime(self, direction_score=3):
        return _make_regime(direction_score=direction_score)

    def _base_gex(self, total_net_gex=-2_000_000.0, gamma_flip_level=22000.0):
        return _make_gex_data(
            total_net_gex=total_net_gex,
            gamma_flip_level=gamma_flip_level,
        )

    def _time(self, hour, minute=0):
        return datetime.time(hour, minute)

    def test_pb4_triggers_on_expiry_day_after_13h(self):
        """All gates pass: 0DTE, after 13:00, negative GEX, spot near flip, vol_acc=True."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=22010.0),
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(13, 30),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is not None
        assert sig.playbook_id == "PB4"
        assert sig.direction in ("BULL", "BEAR")
        assert sig.dte == 0

    def test_pb4_blocked_before_13h(self):
        """Time gate: before 13:00 IST → PB4 should not fire."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=22010.0),
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(12, 59),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is None

    def test_pb4_blocked_non_expiry_day(self):
        """DTE gate: non-expiry day (DTE=3) → PB4 must not fire."""
        analysis = _make_analysis(
            spot=22010.0,
            call_wall=22500.0,
            put_wall=21500.0,
            expiry="2026-10-09",  # 3 days from today
        )
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=analysis,
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(13, 30),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is None

    def test_pb4_blocked_positive_gex(self):
        """GEX gate: positive net GEX → market makers dampen moves → PB4 blocked."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=22010.0),
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(total_net_gex=+500_000.0, gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(14, 0),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is None

    def test_pb4_blocked_without_volume_acceleration(self):
        """Volume gate: no volume acceleration → PB4 blocked (no conviction for blast)."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=22010.0),
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=False,        # <-- blocked here
            current_time_ist=self._time(13, 30),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is None

    def test_pb4_blocked_spot_far_from_flip(self):
        """Proximity gate: spot far from flip level (>0.5%) → PB4 blocked."""
        # flip = 22000, spot = 23000 → distance = 1000 > 0.5% of 23000 (115 pts)
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=23000.0),
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(13, 30),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is None

    def test_pb4_direction_bull_when_positive_score(self):
        """Positive direction_score → PB4 fires a BULL ATM Call."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=22010.0),
            regime=self._base_regime(direction_score=4),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(14, 0),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is not None
        assert sig.direction == "BULL"
        assert sig.instrument_type == "ATM_CALL"

    def test_pb4_direction_bear_when_negative_score(self):
        """Negative direction_score → PB4 fires a BEAR ATM Put."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=21990.0),
            regime=self._base_regime(direction_score=-3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(14, 0),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is not None
        assert sig.direction == "BEAR"
        assert sig.instrument_type == "ATM_PUT"

    def test_pb4_rr_gate_blocks_poor_rr(self):
        """R:R gate: when call_wall is close to spot, R:R < 2.5 → PB4 blocked."""
        # spot=22010, flip=22000, call_wall=22050 → target_dist=40, stop_dist≈10, rr=4 (passes)
        # but with call_wall=22025 → target_dist=15, stop_dist≈10, rr=1.5 < 2.5 → blocked
        analysis = _make_analysis(
            spot=22010.0,
            call_wall=22025.0,  # very close → tiny target distance
            put_wall=21500.0,
            expiry=self._EXPIRY_TODAY,
        )
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=analysis,
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(14, 0),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is None

    def test_pb4_gex_zone_negative_in_signal(self):
        """Triggered PB4 signal carries gex_zone='NEGATIVE' or 'NEAR_FLIP'."""
        sig = evaluate_pb4_gamma_blast(
            symbol="NIFTY",
            analysis=self._base_analysis(spot=22010.0),
            regime=self._base_regime(direction_score=3),
            step=50,
            gex_data=self._base_gex(gamma_flip_level=22000.0),
            volume_accelerating=True,
            current_time_ist=self._time(13, 30),
            _reference_date=datetime.date(2026, 10, 6),
        )
        assert sig is not None
        assert sig.gex_zone in ("NEGATIVE", "NEAR_FLIP")
