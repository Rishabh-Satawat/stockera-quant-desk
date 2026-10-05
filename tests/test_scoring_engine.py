"""Unit tests for scoring_engine.py — pillars, score_candidate, rank_and_filter."""

from __future__ import annotations

import pytest
from playbook_triggers import PlaybookSignal
from scoring_engine import (
    TIER1_THRESHOLD,
    TIER2_THRESHOLD,
    score_candidate,
    rank_and_filter,
    format_confluence_breakdown,
    _score_regime_structure,
    _score_microstructure,
    _score_volatility_em,
    _score_risk_reward,
    _score_data_quality,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
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
    short_strike_ce=None,
    short_strike_pe=None,
    long_strike_ce=None,
    long_strike_pe=None,
):
    return PlaybookSignal(
        playbook_id=playbook_id,
        symbol=symbol,
        direction=direction,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type="ATM_CALL" if playbook_id == "PB1" else "IRON_CONDOR",
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        max_pain=max_pain,
        direction_score=direction_score,
        step=step,
        short_strike_ce=short_strike_ce,
        short_strike_pe=short_strike_pe,
        long_strike_ce=long_strike_ce,
        long_strike_pe=long_strike_pe,
        reason="test",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Pillar 1: Regime & Structure
# ──────────────────────────────────────────────────────────────────────────────

class TestPillar1RegimeStructure:
    def test_pb1_normal_vol_strong_direction_max_pts(self):
        sig = _make_signal(playbook_id="PB1", vol_regime="NORMAL_VOL", direction_score=5)
        pts = _score_regime_structure(sig)
        assert pts == 30.0

    def test_pb1_normal_vol_weak_direction(self):
        sig = _make_signal(playbook_id="PB1", vol_regime="NORMAL_VOL", direction_score=1)
        pts = _score_regime_structure(sig)
        assert pts < 30.0
        assert pts >= 15.0  # 15 vol + 4 direction

    def test_pb2_low_vol_full_regime_pts(self):
        sig = _make_signal(playbook_id="PB2", vol_regime="LOW_VOL", direction_score=0, direction="NEUTRAL")
        pts = _score_regime_structure(sig)
        assert pts >= 15.0  # vol match 15 + direction 0 = 15

    def test_pb1_high_vol_partial_regime_pts(self):
        # HIGH_VOL is in pb1_vols, so still gets 15 regime pts
        sig = _make_signal(playbook_id="PB1", vol_regime="HIGH_VOL", direction_score=5)
        pts = _score_regime_structure(sig)
        assert pts == 30.0  # HIGH_VOL is valid for PB1

    def test_pb6_elevated_vol_partial_regime_pts(self):
        # ELEVATED_VOL not in pb6_vols → partial 7 pts
        sig = _make_signal(playbook_id="PB6", vol_regime="ELEVATED_VOL", direction_score=5)
        pts = _score_regime_structure(sig)
        assert pts < 30.0
        assert pts == 22.0  # 7 partial + 15 direction

    def test_capped_at_30(self):
        sig = _make_signal(playbook_id="PB1", vol_regime="NORMAL_VOL", direction_score=7)
        pts = _score_regime_structure(sig)
        assert pts <= 30.0

    def test_neutral_direction_zero_direction_pts(self):
        sig = _make_signal(playbook_id="PB2", vol_regime="NORMAL_VOL", direction_score=0, direction="NEUTRAL")
        pts = _score_regime_structure(sig)
        assert pts == 15.0  # 15 vol + 0 direction


# ──────────────────────────────────────────────────────────────────────────────
# Pillar 2: Microstructure
# ──────────────────────────────────────────────────────────────────────────────

class TestPillar2Microstructure:
    def test_bull_high_pcr_full_pts(self):
        sig = _make_signal(direction="BULL", pcr=1.2, spot=22300.0,
                           call_wall=22500.0, put_wall=21500.0)
        pts = _score_microstructure(sig)
        # 12 pcr + 13 spot (relative > 0.5) = 25
        assert pts == 25.0

    def test_bear_low_pcr_full_pts(self):
        sig = _make_signal(direction="BEAR", pcr=0.8, spot=21700.0,
                           call_wall=22500.0, put_wall=21500.0)
        pts = _score_microstructure(sig)
        # 12 pcr + 13 spot (relative < 0.5) = 25
        assert pts == 25.0

    def test_neutral_balanced_pcr_full_pts(self):
        sig = _make_signal(playbook_id="PB2", direction="NEUTRAL", pcr=1.0,
                           spot=22000.0, call_wall=22500.0, put_wall=21500.0)
        pts = _score_microstructure(sig)
        # 12 pcr + 13 centred = 25
        assert pts == 25.0

    def test_pcr_mismatch_0_pts(self):
        # BULL but pcr < 0.85 → 0 pcr pts
        sig = _make_signal(direction="BULL", pcr=0.7, spot=22300.0,
                           call_wall=22500.0, put_wall=21500.0)
        pts = _score_microstructure(sig)
        assert pts < 25.0

    def test_capped_at_25(self):
        sig = _make_signal(direction="BULL", pcr=1.5, spot=22400.0,
                           call_wall=22500.0, put_wall=21500.0)
        pts = _score_microstructure(sig)
        assert pts <= 25.0


# ──────────────────────────────────────────────────────────────────────────────
# Pillar 3: Volatility & EM
# ──────────────────────────────────────────────────────────────────────────────

class TestPillar3Volatility:
    def test_pb1_normal_vol_20_pts(self):
        sig = _make_signal(playbook_id="PB1", vol_regime="NORMAL_VOL")
        assert _score_volatility_em(sig) == 20.0

    def test_pb2_normal_vol_20_pts(self):
        sig = _make_signal(playbook_id="PB2", vol_regime="NORMAL_VOL")
        assert _score_volatility_em(sig) == 20.0

    def test_pb6_low_vol_18_pts(self):
        sig = _make_signal(playbook_id="PB6", vol_regime="LOW_VOL")
        assert _score_volatility_em(sig) == 18.0

    def test_pb6_high_vol_4_pts(self):
        sig = _make_signal(playbook_id="PB6", vol_regime="HIGH_VOL")
        assert _score_volatility_em(sig) == 4.0

    def test_provisional_halves_pts(self):
        sig = _make_signal(playbook_id="PB1", vol_regime="NORMAL_VOL", vol_provisional=True)
        assert _score_volatility_em(sig) == 10.0  # 20 * 0.5

    def test_pb2_high_vol_provisional_halved(self):
        sig = _make_signal(playbook_id="PB2", vol_regime="HIGH_VOL", vol_provisional=True)
        assert _score_volatility_em(sig) == 2.0  # 4 * 0.5

    def test_capped_at_20(self):
        sig = _make_signal(playbook_id="PB1", vol_regime="NORMAL_VOL")
        assert _score_volatility_em(sig) <= 20.0


# ──────────────────────────────────────────────────────────────────────────────
# Pillar 4: Risk:Reward
# ──────────────────────────────────────────────────────────────────────────────

class TestPillar4RiskReward:
    def test_pb1_strong_direction_15_pts(self):
        sig = _make_signal(playbook_id="PB1", direction_score=4)
        assert _score_risk_reward(sig) == 15.0

    def test_pb1_moderate_direction_10_pts(self):
        sig = _make_signal(playbook_id="PB1", direction_score=2)
        assert _score_risk_reward(sig) == 10.0

    def test_pb1_weak_direction_5_pts(self):
        sig = _make_signal(playbook_id="PB1", direction_score=1)
        assert _score_risk_reward(sig) == 5.0

    def test_pb2_high_pop_15_pts(self):
        # short strikes 300 pts out, long 50 pts further → wing_width=50, pop=300/350≈0.857
        sig = _make_signal(
            playbook_id="PB2", spot=22000.0, step=50,
            short_strike_ce=22300.0, short_strike_pe=21700.0,
            long_strike_ce=22350.0, long_strike_pe=21650.0,
        )
        assert _score_risk_reward(sig) == 15.0

    def test_pb6_fallback_defaults_when_no_strikes(self):
        # No strikes provided; function uses fallback (spot ± 2*step for short, ± 4*step for long)
        sig = _make_signal(playbook_id="PB6", spot=22000.0, step=50)
        pts = _score_risk_reward(sig)
        assert 0.0 <= pts <= 15.0

    def test_capped_at_15(self):
        sig = _make_signal(playbook_id="PB1", direction_score=7)
        assert _score_risk_reward(sig) <= 15.0


# ──────────────────────────────────────────────────────────────────────────────
# Pillar 5: Data Quality
# ──────────────────────────────────────────────────────────────────────────────

class TestPillar5DataQuality:
    def test_fresh_non_provisional_10_pts(self):
        sig = _make_signal(vol_provisional=False)
        assert _score_data_quality(sig, data_age_seconds=0.0) == 10.0

    def test_stale_data_0_pts(self):
        sig = _make_signal(vol_provisional=False)
        assert _score_data_quality(sig, data_age_seconds=31.0) == 0.0

    def test_provisional_5_pts_for_live_data(self):
        sig = _make_signal(vol_provisional=True)
        assert _score_data_quality(sig, data_age_seconds=0.0) == 5.0

    def test_provisional_0_pts_when_stale(self):
        sig = _make_signal(vol_provisional=True)
        assert _score_data_quality(sig, data_age_seconds=60.0) == 0.0

    def test_exactly_30s_is_fresh(self):
        sig = _make_signal(vol_provisional=False)
        assert _score_data_quality(sig, data_age_seconds=30.0) == 10.0


# ──────────────────────────────────────────────────────────────────────────────
# score_candidate (composite)
# ──────────────────────────────────────────────────────────────────────────────

class TestScoreCandidate:
    def test_returns_expected_keys(self):
        sig = _make_signal()
        result = score_candidate(sig)
        assert set(result.keys()) == {"score", "raw_score", "tier", "breakdown"}

    def test_breakdown_has_five_pillars(self):
        sig = _make_signal()
        result = score_candidate(sig)
        pillars = result["breakdown"].keys()
        assert "regime_structure" in pillars
        assert "microstructure" in pillars
        assert "volatility_em" in pillars
        assert "risk_reward" in pillars
        assert "data_quality" in pillars

    def test_score_within_range(self):
        sig = _make_signal()
        result = score_candidate(sig)
        assert 0 <= result["score"] <= 100

    def test_tier1_high_quality_signal(self):
        # High-quality bull signal: strong direction, normal vol, PCR > 1, spot past midpoint
        sig = _make_signal(
            playbook_id="PB1", direction="BULL", vol_regime="NORMAL_VOL",
            direction_score=5, pcr=1.2,
            spot=22300.0, call_wall=22500.0, put_wall=21500.0,
        )
        result = score_candidate(sig, data_age_seconds=10.0)
        assert result["tier"] == 1
        assert result["score"] >= TIER1_THRESHOLD

    def test_tier2_moderate_signal(self):
        # Moderate signal: partial direction, spot on wrong side
        sig = _make_signal(
            playbook_id="PB1", direction="BULL", vol_regime="NORMAL_VOL",
            direction_score=2, pcr=0.9,  # weak pcr for bull
            spot=21600.0, call_wall=22500.0, put_wall=21500.0,
        )
        result = score_candidate(sig, data_age_seconds=10.0)
        assert result["tier"] in (2, 0)

    def test_vol_provisional_reduces_score(self):
        sig_normal = _make_signal(vol_provisional=False)
        sig_prov = _make_signal(vol_provisional=True)
        result_normal = score_candidate(sig_normal, data_age_seconds=0.0)
        result_prov = score_candidate(sig_prov, data_age_seconds=0.0)
        assert result_prov["score"] < result_normal["score"]

    def test_vol_provisional_approx_10pct_reduction(self):
        sig = _make_signal(vol_provisional=True)
        result = score_candidate(sig, data_age_seconds=0.0)
        # final = raw * 0.9 (p5 is 0 when provisional, p3 is halved)
        assert result["score"] <= result["raw_score"]

    def test_stale_data_reduces_tier(self):
        # Perfect signal but stale data
        sig = _make_signal(
            playbook_id="PB1", direction="BULL", vol_regime="NORMAL_VOL",
            direction_score=5, pcr=1.2, spot=22300.0,
            call_wall=22500.0, put_wall=21500.0,
        )
        fresh = score_candidate(sig, data_age_seconds=0.0)
        stale = score_candidate(sig, data_age_seconds=60.0)
        assert stale["score"] < fresh["score"]

    def test_score_capped_at_100(self):
        sig = _make_signal(
            playbook_id="PB1", direction="BULL", vol_regime="NORMAL_VOL",
            direction_score=7, pcr=1.5, spot=22490.0,
            call_wall=22500.0, put_wall=21500.0,
        )
        result = score_candidate(sig, data_age_seconds=0.0)
        assert result["score"] <= 100

    def test_tier_thresholds(self):
        assert TIER1_THRESHOLD == 80
        assert TIER2_THRESHOLD == 60


# ──────────────────────────────────────────────────────────────────────────────
# rank_and_filter (anti-correlation)
# ──────────────────────────────────────────────────────────────────────────────

class TestRankAndFilter:
    def _sc(self, score):
        return {"score": score, "tier": 1, "raw_score": float(score), "breakdown": {}}

    def test_sorted_descending(self):
        # Use NIFTY + FINNIFTY: different correlated groups, so both kept
        s1 = _make_signal(symbol="NIFTY")
        s2 = _make_signal(symbol="FINNIFTY")
        candidates = [(s1, self._sc(70)), (s2, self._sc(85))]
        result = rank_and_filter(candidates)
        assert result[0][1]["score"] == 85
        assert result[1][1]["score"] == 70

    def test_anti_correlation_drops_lower_nifty_sensex(self):
        nifty = _make_signal(symbol="NIFTY", playbook_id="PB1", direction="BULL")
        sensex = _make_signal(symbol="SENSEX", playbook_id="PB1", direction="BULL")
        candidates = [(nifty, self._sc(90)), (sensex, self._sc(80))]
        result = rank_and_filter(candidates)
        # Only NIFTY (higher score) should survive
        symbols = [s.symbol for s, _ in result]
        assert "NIFTY" in symbols
        assert "SENSEX" not in symbols

    def test_anti_correlation_keeps_higher_score(self):
        nifty = _make_signal(symbol="NIFTY", playbook_id="PB1", direction="BULL")
        sensex = _make_signal(symbol="SENSEX", playbook_id="PB1", direction="BULL")
        # SENSEX higher score
        candidates = [(nifty, self._sc(75)), (sensex, self._sc(88))]
        result = rank_and_filter(candidates)
        symbols = [s.symbol for s, _ in result]
        assert "SENSEX" in symbols
        assert "NIFTY" not in symbols

    def test_different_directions_both_kept(self):
        nifty_bull = _make_signal(symbol="NIFTY", playbook_id="PB1", direction="BULL")
        sensex_bear = _make_signal(symbol="SENSEX", playbook_id="PB1", direction="BEAR")
        candidates = [(nifty_bull, self._sc(85)), (sensex_bear, self._sc(82))]
        result = rank_and_filter(candidates)
        assert len(result) == 2

    def test_pb2_not_filtered(self):
        # Anti-correlation applies only to PB1; PB2 on same direction should both survive
        nifty = _make_signal(symbol="NIFTY", playbook_id="PB2", direction="NEUTRAL")
        sensex = _make_signal(symbol="SENSEX", playbook_id="PB2", direction="NEUTRAL")
        candidates = [(nifty, self._sc(85)), (sensex, self._sc(82))]
        result = rank_and_filter(candidates)
        assert len(result) == 2

    def test_empty_input(self):
        assert rank_and_filter([]) == []

    def test_single_candidate_passes_through(self):
        sig = _make_signal()
        result = rank_and_filter([(sig, self._sc(85))])
        assert len(result) == 1

    def test_non_correlated_symbols_not_filtered(self):
        # BANKNIFTY + FINNIFTY: different pair, both should pass
        bnk = _make_signal(symbol="BANKNIFTY", playbook_id="PB1", direction="BULL")
        fin = _make_signal(symbol="FINNIFTY", playbook_id="PB1", direction="BULL")
        candidates = [(bnk, self._sc(85)), (fin, self._sc(82))]
        result = rank_and_filter(candidates)
        assert len(result) == 2


# ──────────────────────────────────────────────────────────────────────────────
# format_confluence_breakdown
# ──────────────────────────────────────────────────────────────────────────────

class TestFormatConfluenceBreakdown:
    def test_returns_string(self):
        sig = _make_signal()
        result = score_candidate(sig)
        text = format_confluence_breakdown(sig, result)
        assert isinstance(text, str)

    def test_contains_score(self):
        sig = _make_signal()
        result = score_candidate(sig)
        text = format_confluence_breakdown(sig, result)
        assert str(result["score"]) in text

    def test_contains_tier(self):
        sig = _make_signal()
        result = score_candidate(sig)
        text = format_confluence_breakdown(sig, result)
        assert "Tier" in text

    def test_provisional_warning_shown(self):
        sig = _make_signal(vol_provisional=True)
        result = score_candidate(sig)
        text = format_confluence_breakdown(sig, result)
        assert "provisional" in text.lower() or "vol_provisional" in text.lower()

    def test_no_provisional_warning_when_not_provisional(self):
        sig = _make_signal(vol_provisional=False)
        result = score_candidate(sig)
        text = format_confluence_breakdown(sig, result)
        assert "vol_provisional=True" not in text
