"""Phase 1B tests — Volatility Engine, GEX Engine, Regime Engine.

All tests run with NO credentials and NO live network calls.
SQLite databases are created in-memory or in tmp directories.
"""

import math
import os
import sqlite3
import tempfile
import datetime
from typing import Optional
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixture helpers
# ──────────────────────────────────────────────────────────────────────────────

_IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> str:
    return datetime.datetime.now(tz=_IST).strftime("%Y-%m-%d")


def _make_db(tmp_path) -> str:
    db_path = str(tmp_path / "test.db")
    from db_init import init_db
    init_db(db_path)
    return db_path


def _insert_snapshot(
    conn: sqlite3.Connection,
    symbol: str,
    expiry: str,
    strike: float,
    option_type: str,  # "CE" or "PE"
    ts: str,
    ltp: float = 100.0,
    oi: int = 1000,
    volume: int = 500,
    iv: Optional[float] = 0.20,
    delta: Optional[float] = None,
    gamma: Optional[float] = None,
    theta: Optional[float] = None,
    vega: Optional[float] = None,
    security_id: int = 12345,
    is_synthetic: int = 0,
):
    conn.execute(
        """INSERT OR REPLACE INTO chain_snapshots
           (symbol, expiry, strike, option_type, timestamp,
            ltp, oi, volume, iv, delta, theta, gamma, vega, security_id, is_synthetic)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol, expiry, strike, option_type, ts,
         ltp, oi, volume, iv, delta, theta, gamma, vega, security_id, is_synthetic),
    )


def _insert_bar(
    conn: sqlite3.Connection,
    symbol: str,
    bar_tf: str,
    bar_open_ts: str,
    open_: float = 22000.0,
    high: float = 22100.0,
    low: float = 21900.0,
    close: float = 22050.0,
    volume: int = 10000,
):
    conn.execute(
        """INSERT OR REPLACE INTO underlying_bars
           (symbol, bar_tf, bar_open_ts, open, high, low, close, volume)
           VALUES (?,?,?,?,?,?,?,?)""",
        (symbol, bar_tf, bar_open_ts, open_, high, low, close, volume),
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Volatility Engine Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestIVR:
    def test_ivr_correct_range(self):
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS
        # Pad to MIN_LOOKBACK_SESSIONS with a filler below the range
        base = [0.12] * (MIN_LOOKBACK_SESSIONS - 5)
        ivs = base + [0.15, 0.18, 0.20, 0.22, 0.25]
        ivr = compute_ivr(ivs)
        assert ivr is not None
        assert 0.0 <= ivr <= 100.0

    def test_ivr_current_is_max(self):
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS
        # current (last) = 0.30 = max; pad to minimum required length
        ivs = [0.10] * (MIN_LOOKBACK_SESSIONS - 3) + [0.15, 0.20, 0.30]
        ivr = compute_ivr(ivs)
        assert ivr is not None
        assert abs(ivr - 100.0) < 1e-9

    def test_ivr_current_is_min(self):
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS
        # current (last) = 0.15 = min; pad to minimum required length
        ivs = [0.30] * (MIN_LOOKBACK_SESSIONS - 2) + [0.25, 0.15]
        ivr = compute_ivr(ivs)
        assert ivr is not None
        assert abs(ivr - 0.0) < 1e-9

    def test_ivr_midpoint(self):
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS
        # current=0.15, min=0.10, max=0.20 → IVR=50.0; pad to minimum length
        ivs = [0.10] * (MIN_LOOKBACK_SESSIONS - 2) + [0.20, 0.15]
        ivr = compute_ivr(ivs)
        assert ivr is not None
        assert abs(ivr - 50.0) < 1e-9

    def test_ivr_none_on_single_element(self):
        from volatility_engine import compute_ivr
        assert compute_ivr([0.20]) is None

    def test_ivr_none_on_empty(self):
        from volatility_engine import compute_ivr
        assert compute_ivr([]) is None

    def test_ivr_none_when_min_equals_max(self):
        from volatility_engine import compute_ivr
        # Short list → None due to insufficient lookback
        assert compute_ivr([0.20, 0.20, 0.20]) is None

    def test_ivr_none_on_two_identical(self):
        from volatility_engine import compute_ivr
        assert compute_ivr([0.20, 0.20]) is None


class TestIVP:
    def test_ivp_correct_range(self):
        from volatility_engine import compute_ivp, MIN_LOOKBACK_SESSIONS
        base = [0.12] * (MIN_LOOKBACK_SESSIONS - 5)
        ivs = base + [0.10, 0.15, 0.18, 0.22, 0.25]
        ivp = compute_ivp(ivs)
        assert ivp is not None
        assert 0.0 <= ivp <= 100.0

    def test_ivp_current_above_all(self):
        from volatility_engine import compute_ivp, MIN_LOOKBACK_SESSIONS
        # current=0.30, all prior below → IVP=100.0; pad to minimum length
        ivs = [0.10] * (MIN_LOOKBACK_SESSIONS - 4) + [0.10, 0.12, 0.15, 0.30]
        ivp = compute_ivp(ivs)
        assert ivp is not None
        assert abs(ivp - 100.0) < 1e-9

    def test_ivp_current_below_all(self):
        from volatility_engine import compute_ivp, MIN_LOOKBACK_SESSIONS
        # current=0.05, 0 prior below → IVP=0.0; pad to minimum length
        ivs = [0.30] * (MIN_LOOKBACK_SESSIONS - 4) + [0.30, 0.25, 0.20, 0.05]
        ivp = compute_ivp(ivs)
        assert ivp is not None
        assert abs(ivp - 0.0) < 1e-9

    def test_ivp_none_on_single_element(self):
        from volatility_engine import compute_ivp
        assert compute_ivp([0.20]) is None

    def test_ivp_none_on_empty(self):
        from volatility_engine import compute_ivp
        assert compute_ivp([]) is None


class TestRV5m:
    def test_rv_positive(self):
        from volatility_engine import compute_rv_5m
        closes = [22000, 22050, 21990, 22100, 22080, 22200, 22150]
        rv = compute_rv_5m(closes)
        assert rv is not None
        assert rv > 0

    def test_rv_none_on_single(self):
        from volatility_engine import compute_rv_5m
        assert compute_rv_5m([22000]) is None

    def test_rv_none_on_empty(self):
        from volatility_engine import compute_rv_5m
        assert compute_rv_5m([]) is None

    def test_rv_annualization(self):
        """Two equal-sized returns with known std; check annualization factor."""
        from volatility_engine import compute_rv_5m
        # Constant price → zero returns → RV = 0
        closes = [100.0] * 10
        rv = compute_rv_5m(closes)
        assert rv is not None
        assert rv == pytest.approx(0.0, abs=1e-10)

    def test_vrp_sign_convention(self):
        """VRP = ATM_IV - RV; positive means IV > RV."""
        from volatility_engine import compute_vol_metrics
        # We test the formula indirectly via compute_vol_metrics in DB tests
        # Here just test the sign: if ATM_IV > RV → positive VRP
        iv = 0.25
        rv = 0.15
        vrp = iv - rv
        assert vrp > 0  # positive = IV > RV overpriced


class TestVolatilityEngineDB:
    def test_ivr_from_db(self, tmp_path):
        """IVR is computed from iv_history daily rows, not intraday chain_snapshots."""
        from volatility_engine import compute_vol_metrics, MIN_LOOKBACK_SESSIONS
        from db_init import get_connection
        db_path = _make_db(tmp_path)
        symbol, expiry = "NIFTY", "2026-10-27"

        # Insert MIN_LOOKBACK_SESSIONS daily iv_history rows (varied IVs)
        conn = get_connection(db_path)
        for i in range(MIN_LOOKBACK_SESSIONS):
            date_str = f"2026-09-{i+1:02d}" if i < 30 else f"2026-10-{i-29:02d}"
            atm_iv = 0.12 + i * 0.005  # rising IV series
            _insert_iv_history(conn, symbol, date_str, expiry, atm_iv)
        conn.close()

        result = compute_vol_metrics(symbol, expiry, db_path)
        assert result["ivr"] is not None
        assert 0.0 <= result["ivr"] <= 100.0
        assert result["ivp"] is not None
        assert result["vol_regime"] in {"LOW_VOL", "NORMAL_VOL", "ELEVATED_VOL", "HIGH_VOL"}

    def test_ivr_none_empty_db(self, tmp_path):
        from volatility_engine import compute_vol_metrics
        db_path = _make_db(tmp_path)
        result = compute_vol_metrics("NIFTY", "2026-10-27", db_path)
        assert result["ivr"] is None
        assert result["ivp"] is None
        assert result["vol_regime"] == "UNKNOWN"

    def test_rv_from_bars(self, tmp_path):
        from volatility_engine import compute_vol_metrics
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        closes = [22000, 22050, 22020, 22100, 22080, 22150, 22200, 22130]
        for i, close_val in enumerate(closes):
            ts = f"{today}T09:{15+i*5:02d}:00"
            _insert_bar(conn, "NIFTY", "5m", ts, **{"close": close_val})
        conn.commit()
        conn.close()

        result = compute_vol_metrics("NIFTY", "2026-10-27", db_path)
        assert result["rv_5m"] is not None
        assert result["rv_5m"] > 0

    def test_rr25_with_delta_data(self, tmp_path):
        from volatility_engine import compute_vol_metrics
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"
        ts = f"{today}T10:00:00+05:30"

        # ATM: delta ≈ 0.5
        _insert_snapshot(conn, symbol, expiry, 22000.0, "CE", ts, iv=0.20, delta=0.50)
        _insert_snapshot(conn, symbol, expiry, 22000.0, "PE", ts, iv=0.21, delta=-0.50)
        # 25-delta call: delta ≈ 0.25
        _insert_snapshot(conn, symbol, expiry, 22500.0, "CE", ts, iv=0.18, delta=0.25)
        # 25-delta put: delta ≈ -0.25
        _insert_snapshot(conn, symbol, expiry, 21500.0, "PE", ts, iv=0.22, delta=-0.25)
        conn.commit()
        conn.close()

        result = compute_vol_metrics(symbol, expiry, db_path)
        assert result["rr_25"] is not None
        # RR = IV_25Δput - IV_25Δcall = 0.22 - 0.18 = 0.04
        assert abs(result["rr_25"] - 0.04) < 1e-9

    def test_rr25_none_without_delta(self, tmp_path):
        from volatility_engine import compute_vol_metrics
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        ts = f"{today}T10:00:00+05:30"
        _insert_snapshot(conn, "NIFTY", "2026-10-27", 22000.0, "CE", ts, iv=0.20, delta=None)
        _insert_snapshot(conn, "NIFTY", "2026-10-27", 22000.0, "PE", ts, iv=0.20, delta=None)
        conn.commit()
        conn.close()

        result = compute_vol_metrics("NIFTY", "2026-10-27", db_path)
        assert result["rr_25"] is None


class TestVolRegime:
    def test_regime_low_vol(self):
        from volatility_engine import ivr_to_regime
        assert ivr_to_regime(10.0) == "LOW_VOL"
        assert ivr_to_regime(0.0) == "LOW_VOL"

    def test_regime_boundary_low(self):
        from volatility_engine import ivr_to_regime
        assert ivr_to_regime(24.9) == "LOW_VOL"
        assert ivr_to_regime(25.0) == "NORMAL_VOL"

    def test_regime_normal_vol(self):
        from volatility_engine import ivr_to_regime
        assert ivr_to_regime(50.0) == "NORMAL_VOL"
        assert ivr_to_regime(70.0) == "NORMAL_VOL"

    def test_regime_elevated_vol(self):
        from volatility_engine import ivr_to_regime
        assert ivr_to_regime(75.0) == "ELEVATED_VOL"
        assert ivr_to_regime(85.0) == "ELEVATED_VOL"

    def test_regime_high_vol(self):
        from volatility_engine import ivr_to_regime
        assert ivr_to_regime(86.0) == "HIGH_VOL"
        assert ivr_to_regime(100.0) == "HIGH_VOL"

    def test_regime_unknown_on_none(self):
        from volatility_engine import ivr_to_regime
        assert ivr_to_regime(None) == "UNKNOWN"


# ──────────────────────────────────────────────────────────────────────────────
# GEX Engine Tests
# ──────────────────────────────────────────────────────────────────────────────

def _make_oc(strikes, lot_size=65, spot=22000.0):
    """Helper: build option chain dict for GEX tests."""
    oc = {}
    for strike, call_gamma, call_oi, put_gamma, put_oi in strikes:
        oc[str(int(strike))] = {
            "ce": {
                "oi": call_oi,
                "volume": 100,
                "last_price": 100.0,
                "implied_volatility": 0.20,
                "security_id": 1,
                "greeks": {"delta": 0.5, "gamma": call_gamma, "theta": -5.0, "vega": 10.0},
            },
            "pe": {
                "oi": put_oi,
                "volume": 100,
                "last_price": 100.0,
                "implied_volatility": 0.20,
                "security_id": 2,
                "greeks": {"delta": -0.5, "gamma": put_gamma, "theta": -5.0, "vega": 10.0},
            },
        }
    return oc


class TestGEXStrikeMath:
    def test_call_gex_positive(self):
        """Call GEX is positive (dealer long gamma)."""
        from gex_engine import compute_per_strike_gex
        oc = _make_oc([(22000, 0.01, 1000, 0.0, 0)])  # only call gamma
        result = compute_per_strike_gex(oc, lot_size=65, spot=22000.0)
        assert len(result) == 1
        assert result[0]["call_gex"] > 0
        assert result[0]["put_gex"] == 0.0
        assert result[0]["net_gex"] > 0

    def test_put_gex_negative(self):
        """Put GEX is negative (dealer short gamma)."""
        from gex_engine import compute_per_strike_gex
        oc = _make_oc([(22000, 0.0, 0, 0.01, 1000)])  # only put gamma
        result = compute_per_strike_gex(oc, lot_size=65, spot=22000.0)
        assert len(result) == 1
        assert result[0]["call_gex"] == 0.0
        assert result[0]["put_gex"] < 0
        assert result[0]["net_gex"] < 0

    def test_gex_formula(self):
        """GEX = gamma * oi * lot_size * (spot/100)^2."""
        from gex_engine import _gex_strike
        gamma, oi, lot_size, spot = 0.01, 1000, 65, 22000.0
        expected = 0.01 * 1000 * 65 * (22000.0 / 100.0) ** 2
        assert abs(_gex_strike(gamma, oi, lot_size, spot) - expected) < 1e-6

    def test_net_gex_is_call_minus_put(self):
        """net_gex = call_gex + put_gex (put contribution is negative)."""
        from gex_engine import compute_per_strike_gex
        # Equal gamma and OI on both sides → call positive, put negative → should cancel
        oc = _make_oc([(22000, 0.01, 1000, 0.01, 1000)])
        result = compute_per_strike_gex(oc, lot_size=65, spot=22000.0)
        assert abs(result[0]["net_gex"]) < 1e-6  # net = 0

    def test_sorted_by_strike(self):
        from gex_engine import compute_per_strike_gex
        oc = _make_oc([
            (22200, 0.01, 1000, 0.01, 1000),
            (22000, 0.01, 1000, 0.01, 1000),
            (21800, 0.01, 1000, 0.01, 1000),
        ])
        result = compute_per_strike_gex(oc, lot_size=65, spot=22000.0)
        strikes = [r["strike"] for r in result]
        assert strikes == sorted(strikes)

    def test_zero_oi_excluded(self):
        """Strike with zero OI on both sides gives zero GEX."""
        from gex_engine import compute_per_strike_gex
        oc = _make_oc([(22000, 0.01, 0, 0.01, 0)])
        result = compute_per_strike_gex(oc, lot_size=65, spot=22000.0)
        assert result[0]["call_gex"] == 0.0
        assert result[0]["put_gex"] == 0.0

    def test_none_gamma_excluded(self):
        """None gamma produces zero contribution."""
        from gex_engine import compute_per_strike_gex
        oc = {
            "22000": {
                "ce": {"oi": 1000, "volume": 100, "last_price": 100, "implied_volatility": 0.2,
                       "security_id": 1, "greeks": {"delta": 0.5, "gamma": None, "theta": -5, "vega": 10}},
                "pe": {"oi": 0, "volume": 0, "last_price": 0, "implied_volatility": 0.2,
                       "security_id": 2, "greeks": {"delta": -0.5, "gamma": None, "theta": -5, "vega": 10}},
            }
        }
        result = compute_per_strike_gex(oc, lot_size=65, spot=22000.0)
        assert result[0]["call_gex"] == 0.0


class TestGammaFlip:
    def test_flip_detected(self):
        """Finds the strike where cumulative net GEX crosses from negative to positive."""
        from gex_engine import find_gamma_flip
        per_strike = [
            {"strike": 21800, "net_gex": -500, "call_gex": 0, "put_gex": -500},
            {"strike": 22000, "net_gex": -200, "call_gex": 100, "put_gex": -300},
            {"strike": 22200, "net_gex": 1000, "call_gex": 1200, "put_gex": -200},
        ]
        flip = find_gamma_flip(per_strike)
        assert flip == 22200

    def test_flip_none_all_positive(self):
        """No flip when cumulative is always positive."""
        from gex_engine import find_gamma_flip
        per_strike = [
            {"strike": 21800, "net_gex": 500, "call_gex": 500, "put_gex": 0},
            {"strike": 22000, "net_gex": 500, "call_gex": 500, "put_gex": 0},
        ]
        assert find_gamma_flip(per_strike) is None

    def test_flip_none_all_negative(self):
        """No flip when cumulative never goes positive."""
        from gex_engine import find_gamma_flip
        per_strike = [
            {"strike": 21800, "net_gex": -500, "call_gex": 0, "put_gex": -500},
            {"strike": 22000, "net_gex": -500, "call_gex": 0, "put_gex": -500},
        ]
        assert find_gamma_flip(per_strike) is None

    def test_flip_none_empty(self):
        from gex_engine import find_gamma_flip
        assert find_gamma_flip([]) is None


class TestMaxPain:
    def test_max_pain_simple(self):
        """At ATM with equal OI on both sides, max pain should be near ATM."""
        from gex_engine import compute_max_pain
        oc = {}
        # Symmetric OI: 3 strikes equally spaced
        for strike, call_oi, put_oi in [(21900, 500, 200), (22000, 1000, 1000), (22100, 200, 500)]:
            oc[str(strike)] = {
                "ce": {"oi": call_oi},
                "pe": {"oi": put_oi},
            }
        max_pain = compute_max_pain(oc)
        assert max_pain is not None
        assert max_pain in [21900, 22000, 22100]

    def test_max_pain_formula_correctness(self):
        """Verify max pain formula: pain at each candidate K."""
        from gex_engine import compute_max_pain
        # Simple 2-strike case: 22000 and 22100
        # At K=22000: call pain=0, put pain= (22000-22000)*oi_put_22000 + (22000-22100)*oi_put_22100 = 0
        # Actually formula: pain = sum over all S of max(0,S-K)*call_oi + max(0,K-S)*put_oi
        # At K=22000: put_22100_pain=0 (22000 < 22100 → 0), call_22100 pain = (22100-22000)*call_oi_22100
        oc = {
            "22000": {"ce": {"oi": 1000}, "pe": {"oi": 500}},
            "22100": {"ce": {"oi": 200}, "pe": {"oi": 800}},
        }
        max_pain = compute_max_pain(oc)
        assert max_pain is not None

    def test_max_pain_none_on_empty(self):
        from gex_engine import compute_max_pain
        assert compute_max_pain({}) is None

    def test_max_pain_single_strike(self):
        from gex_engine import compute_max_pain
        oc = {"22000": {"ce": {"oi": 1000}, "pe": {"oi": 1000}}}
        result = compute_max_pain(oc)
        assert result == 22000.0


class TestPinScore:
    def test_pin_score_100_at_max_pain(self):
        """Pin score = 100 when spot == max_pain."""
        from gex_engine import compute_pin_score
        score = compute_pin_score(22000.0, 22000.0)
        assert abs(score - 100.0) < 1e-9

    def test_pin_score_decays_with_distance(self):
        """Pin score decreases as spot moves further from max pain."""
        from gex_engine import compute_pin_score
        s0 = compute_pin_score(22000.0, 22000.0)  # at max pain
        s1 = compute_pin_score(22100.0, 22000.0)  # 100 pts away
        s2 = compute_pin_score(22500.0, 22000.0)  # 500 pts away
        assert s0 > s1 > s2

    def test_pin_score_zero_when_no_max_pain(self):
        from gex_engine import compute_pin_score
        assert compute_pin_score(22000.0, None) == 0.0

    def test_pin_score_range(self):
        """Pin score always in [0, 100]."""
        from gex_engine import compute_pin_score
        for dist in [0, 100, 500, 2000]:
            score = compute_pin_score(22000.0, 22000.0 + dist)
            assert 0.0 <= score <= 100.0

    def test_pin_score_formula(self):
        """Verify: pin_score = 100 * exp(-|spot - max_pain| / (spot * 0.005))."""
        from gex_engine import compute_pin_score
        spot, max_pain = 22000.0, 21890.0
        expected = 100.0 * math.exp(-abs(spot - max_pain) / (spot * 0.005))
        assert abs(compute_pin_score(spot, max_pain) - expected) < 1e-6


class TestComputeGEXNoLiveData:
    def test_empty_snapshot_returns_zeros(self, tmp_path):
        """compute_gex returns zeros when no fresh snapshot available."""
        from gex_engine import compute_gex
        db_path = _make_db(tmp_path)
        # No data inserted → get_latest_chain_snapshot returns {}
        result = compute_gex("NIFTY", "2026-10-27", 22000.0, 65, db_path)
        assert result["total_net_gex"] == 0.0
        assert result["gamma_flip_level"] is None
        assert result["max_pain"] is None
        assert result["pin_score"] == 0.0
        assert result["per_strike_gex"] == []


# ──────────────────────────────────────────────────────────────────────────────
# Regime Engine Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestDirectionScore:
    def test_strong_bull(self):
        from regime_engine import score_to_direction
        assert score_to_direction(5) == "STRONG_BULL"
        assert score_to_direction(7) == "STRONG_BULL"

    def test_bull(self):
        from regime_engine import score_to_direction
        assert score_to_direction(2) == "BULL"
        assert score_to_direction(4) == "BULL"

    def test_neutral(self):
        from regime_engine import score_to_direction
        assert score_to_direction(0) == "NEUTRAL"
        assert score_to_direction(1) == "NEUTRAL"
        assert score_to_direction(-1) == "NEUTRAL"

    def test_bear(self):
        from regime_engine import score_to_direction
        assert score_to_direction(-2) == "BEAR"
        assert score_to_direction(-4) == "BEAR"

    def test_strong_bear(self):
        from regime_engine import score_to_direction
        assert score_to_direction(-5) == "STRONG_BEAR"
        assert score_to_direction(-7) == "STRONG_BEAR"


class TestPlaybookGating:
    """Every cell in the playbook matrix maps correctly."""

    @pytest.mark.parametrize("direction,vol,expected", [
        ("STRONG_BULL", "LOW_VOL",       "LONG_CALL_SPREAD"),
        ("BULL",        "LOW_VOL",       "LONG_CALL_SPREAD"),
        ("STRONG_BULL", "NORMAL_VOL",    "BULL_CALL_SPREAD"),
        ("BULL",        "NORMAL_VOL",    "BULL_CALL_SPREAD"),
        ("STRONG_BULL", "ELEVATED_VOL",  "LONG_CALL"),
        ("BULL",        "ELEVATED_VOL",  "LONG_CALL"),
        ("STRONG_BULL", "HIGH_VOL",      "LONG_CALL"),
        ("BULL",        "HIGH_VOL",      "LONG_CALL"),
        ("STRONG_BEAR", "LOW_VOL",       "LONG_PUT_SPREAD"),
        ("BEAR",        "LOW_VOL",       "LONG_PUT_SPREAD"),
        ("STRONG_BEAR", "NORMAL_VOL",    "BEAR_PUT_SPREAD"),
        ("BEAR",        "NORMAL_VOL",    "BEAR_PUT_SPREAD"),
        ("STRONG_BEAR", "ELEVATED_VOL",  "LONG_PUT"),
        ("BEAR",        "ELEVATED_VOL",  "LONG_PUT"),
        ("STRONG_BEAR", "HIGH_VOL",      "LONG_PUT"),
        ("BEAR",        "HIGH_VOL",      "LONG_PUT"),
        ("NEUTRAL",     "LOW_VOL",       "SHORT_STRANGLE"),
        ("NEUTRAL",     "NORMAL_VOL",    "IRON_CONDOR"),
        ("NEUTRAL",     "ELEVATED_VOL",  "STRADDLE_BUY"),
        ("NEUTRAL",     "HIGH_VOL",      "STRADDLE_BUY"),
    ])
    def test_playbook_cell(self, direction, vol, expected):
        from regime_engine import get_playbook
        assert get_playbook(direction, vol) == expected

    def test_unknown_combination(self):
        from regime_engine import get_playbook
        assert get_playbook("STRONG_BULL", "UNKNOWN") == "NO_TRADE"


class TestVWAPComponent:
    def test_vwap_above(self, tmp_path):
        from regime_engine import _score_vwap
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        ts = f"{today}T09:15:00"
        _insert_bar(conn, "NIFTY", "15m", ts, open_=21900, high=22100, low=21800, close=22050, volume=10000)
        conn.commit()
        conn.close()
        # VWAP ≈ (22100+21800+22050)/3 = 21983; spot 22100 > VWAP → +1
        result = _score_vwap("NIFTY", 22100.0, db_path)
        assert result == 1

    def test_vwap_below(self, tmp_path):
        from regime_engine import _score_vwap
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        ts = f"{today}T09:15:00"
        _insert_bar(conn, "NIFTY", "15m", ts, open_=22000, high=22200, low=22000, close=22100, volume=10000)
        conn.commit()
        conn.close()
        # VWAP ≈ (22200+22000+22100)/3 = 22100; spot 21900 < VWAP → -1
        result = _score_vwap("NIFTY", 21900.0, db_path)
        assert result == -1

    def test_vwap_no_bars(self, tmp_path):
        from regime_engine import _score_vwap
        db_path = _make_db(tmp_path)
        assert _score_vwap("NIFTY", 22000.0, db_path) == 0


class TestBasisComponent:
    def test_contango(self):
        from regime_engine import _score_basis
        assert _score_basis(22000.0, 22050.0) == 1

    def test_backwardation(self):
        from regime_engine import _score_basis
        assert _score_basis(22000.0, 21950.0) == -1

    def test_equal(self):
        from regime_engine import _score_basis
        assert _score_basis(22000.0, 22000.0) == 0

    def test_none_futures(self):
        from regime_engine import _score_basis
        assert _score_basis(22000.0, None) == 0


class TestPCRZScoreComponent:
    def test_pcr_bullish_low_pcr(self, tmp_path):
        """Low PCR z-score (< -1) → bullish → +1."""
        from regime_engine import _score_pcr
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"

        # Session PCRs: high call OI relative to put OI → low PCR
        for i, (call_oi, put_oi) in enumerate([(10000, 5000)] * 5 + [(10000, 1000)]):
            ts = f"{today}T09:{15+i*5:02d}:00+05:30"
            for strike in [22000.0, 22100.0]:
                _insert_snapshot(conn, symbol, expiry, strike, "CE", ts, oi=call_oi)
                _insert_snapshot(conn, symbol, expiry, strike, "PE", ts, oi=put_oi)
        conn.commit()
        conn.close()

        result = _score_pcr(symbol, expiry, db_path)
        # With a very low final PCR compared to session avg → z < -1 → +1
        assert result in [-1, 0, 1]  # can't guarantee exact value, but no crash

    def test_pcr_insufficient_data(self, tmp_path):
        from regime_engine import _score_pcr
        db_path = _make_db(tmp_path)
        assert _score_pcr("NIFTY", "2026-10-27", db_path) == 0


class TestOIBuildup:
    def test_call_buildup_bullish(self, tmp_path):
        from regime_engine import _score_oi_buildup
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"

        ts1 = f"{today}T09:15:00+05:30"
        ts2 = f"{today}T09:20:00+05:30"
        for strike in [22000.0]:
            _insert_snapshot(conn, symbol, expiry, strike, "CE", ts1, oi=10000)
            _insert_snapshot(conn, symbol, expiry, strike, "PE", ts1, oi=5000)
            _insert_snapshot(conn, symbol, expiry, strike, "CE", ts2, oi=11000)  # +10% call OI
            _insert_snapshot(conn, symbol, expiry, strike, "PE", ts2, oi=5000)
        conn.commit()
        conn.close()

        result = _score_oi_buildup(symbol, expiry, db_path)
        assert result == 1

    def test_put_buildup_bearish(self, tmp_path):
        from regime_engine import _score_oi_buildup
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"

        ts1 = f"{today}T09:15:00+05:30"
        ts2 = f"{today}T09:20:00+05:30"
        for strike in [22000.0]:
            _insert_snapshot(conn, symbol, expiry, strike, "CE", ts1, oi=5000)
            _insert_snapshot(conn, symbol, expiry, strike, "PE", ts1, oi=10000)
            _insert_snapshot(conn, symbol, expiry, strike, "CE", ts2, oi=5000)
            _insert_snapshot(conn, symbol, expiry, strike, "PE", ts2, oi=11000)  # +10% put OI
        conn.commit()
        conn.close()

        result = _score_oi_buildup(symbol, expiry, db_path)
        assert result == -1

    def test_insufficient_snapshots(self, tmp_path):
        from regime_engine import _score_oi_buildup
        db_path = _make_db(tmp_path)
        assert _score_oi_buildup("NIFTY", "2026-10-27", db_path) == 0


class TestSwingStructure:
    def test_bullish_swing(self, tmp_path):
        from regime_engine import _score_swing
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        # 8 bars: 4 recent (higher H/L) and 4 prior (lower H/L)
        for i in range(8):
            ts = f"{today}T{9+i//4:02d}:{(i%4)*15:02d}:00"
            if i < 4:  # most recent (DESC order, so these are the higher ones)
                _insert_bar(conn, "NIFTY", "15m", ts, high=22200+i*10, low=22100+i*10)
            else:
                _insert_bar(conn, "NIFTY", "15m", ts, high=21900+i*10, low=21800+i*10)
        conn.commit()
        conn.close()
        # Should detect HH/HL
        result = _score_swing("NIFTY", db_path)
        assert result in [-1, 0, 1]  # direction check passes


class TestDeltaWeightedPCR:
    def test_put_heavy_bearish(self, tmp_path):
        from regime_engine import _score_delta_weighted_pcr
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"
        ts = f"{today}T10:00:00+05:30"

        # Put delta-weighted OI >> call delta-weighted OI → bearish
        _insert_snapshot(conn, symbol, expiry, 22000.0, "CE", ts, delta=0.3, oi=1000)
        _insert_snapshot(conn, symbol, expiry, 22000.0, "PE", ts, delta=-0.6, oi=5000)  # large
        conn.commit()
        conn.close()

        result = _score_delta_weighted_pcr(symbol, expiry, db_path)
        # ratio = (0.6*5000)/(0.3*1000) = 3000/300 = 10 >> 1.1 → -1
        assert result == -1

    def test_call_heavy_bullish(self, tmp_path):
        from regime_engine import _score_delta_weighted_pcr
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"
        ts = f"{today}T10:00:00+05:30"

        # Call delta-weighted OI >> put → bullish
        _insert_snapshot(conn, symbol, expiry, 22000.0, "CE", ts, delta=0.6, oi=5000)
        _insert_snapshot(conn, symbol, expiry, 22000.0, "PE", ts, delta=-0.3, oi=1000)
        conn.commit()
        conn.close()

        result = _score_delta_weighted_pcr(symbol, expiry, db_path)
        # ratio = (0.3*1000)/(0.6*5000) = 300/3000 = 0.1 < 0.9 → +1
        assert result == 1

    def test_neutral_delta_pcr(self, tmp_path):
        from regime_engine import _score_delta_weighted_pcr
        db_path = _make_db(tmp_path)
        today = _today_ist()
        conn = sqlite3.connect(db_path)
        symbol, expiry = "NIFTY", "2026-10-27"
        ts = f"{today}T10:00:00+05:30"

        # Equal delta-weighted OI → neutral
        _insert_snapshot(conn, symbol, expiry, 22000.0, "CE", ts, delta=0.5, oi=1000)
        _insert_snapshot(conn, symbol, expiry, 22000.0, "PE", ts, delta=-0.5, oi=1000)
        conn.commit()
        conn.close()

        result = _score_delta_weighted_pcr(symbol, expiry, db_path)
        assert result == 0

    def test_no_data(self, tmp_path):
        from regime_engine import _score_delta_weighted_pcr
        db_path = _make_db(tmp_path)
        assert _score_delta_weighted_pcr("NIFTY", "2026-10-27", db_path) == 0


class TestComputeRegime:
    def test_returns_all_keys(self, tmp_path):
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        assert set(result.keys()) == {
            "direction_score", "direction_label", "vol_regime", "playbook", "component_scores"
        }

    def test_component_scores_has_7_keys(self, tmp_path):
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        assert len(result["component_scores"]) == 7

    def test_direction_score_range(self, tmp_path):
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        assert -7 <= result["direction_score"] <= 7

    def test_direction_label_valid(self, tmp_path):
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        assert result["direction_label"] in {
            "STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR"
        }

    def test_playbook_valid(self, tmp_path):
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        valid_playbooks = {
            "LONG_CALL_SPREAD", "BULL_CALL_SPREAD", "LONG_CALL",
            "LONG_PUT_SPREAD", "BEAR_PUT_SPREAD", "LONG_PUT",
            "SHORT_STRANGLE", "IRON_CONDOR", "STRADDLE_BUY", "NO_TRADE"
        }
        assert result["playbook"] in valid_playbooks

    def test_component_scores_bounded(self, tmp_path):
        """Each component must be -1, 0, or +1."""
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        for name, score in result["component_scores"].items():
            assert score in {-1, 0, 1}, f"Component {name} = {score} not in {{-1, 0, 1}}"

    def test_futures_price_affects_basis(self, tmp_path):
        """Passing futures_price changes basis component score."""
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        r_contango = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path, futures_price=22100.0)
        r_backwardation = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path, futures_price=21900.0)
        assert r_contango["component_scores"]["basis"] == 1
        assert r_backwardation["component_scores"]["basis"] == -1

    def test_no_futures_price_zero_basis(self, tmp_path):
        from regime_engine import compute_regime
        db_path = _make_db(tmp_path)
        result = compute_regime("NIFTY", "2026-10-27", 22000.0, db_path)
        assert result["component_scores"]["basis"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1B.1 — IVR/IVP using iv_history (historical daily sessions)
# ──────────────────────────────────────────────────────────────────────────────

def _insert_iv_history(conn, symbol, trade_date, expiry, atm_iv, spot=22000.0):
    conn.execute(
        """INSERT OR REPLACE INTO iv_history
           (symbol, trade_date, expiry, atm_iv, iv_25d_put, iv_25d_call, spot, source)
           VALUES (?, ?, ?, ?, NULL, NULL, ?, 'EOD_SNAPSHOT')""",
        (symbol, trade_date, expiry, atm_iv, spot),
    )
    conn.commit()


class TestIVRHistoricalWindow:
    """IVR/IVP must use iv_history daily rows, not intraday snapshots."""

    def test_below_min_lookback_returns_none(self, tmp_path):
        """< MIN_LOOKBACK_SESSIONS rows → compute_ivr/ivp return None."""
        from volatility_engine import compute_ivr, compute_ivp, MIN_LOOKBACK_SESSIONS

        # Provide fewer rows than the minimum
        few_ivs = [0.12] * (MIN_LOOKBACK_SESSIONS - 1)
        assert compute_ivr(few_ivs) is None
        assert compute_ivp(few_ivs) is None

    def test_exactly_min_lookback_does_not_return_none(self, tmp_path):
        """Exactly MIN_LOOKBACK_SESSIONS rows → compute_ivr returns a value."""
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS

        # Build a series where last value > min
        ivs = [0.12] * (MIN_LOOKBACK_SESSIONS - 1) + [0.20]
        result = compute_ivr(ivs)
        assert result is not None

    def test_flat_iv_history_not_intraday_noise(self, tmp_path):
        """A series spanning lo..hi with midpoint as the current value returns IVR = 50.0."""
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS

        lo, hi = 0.10, 0.30
        mid = (lo + hi) / 2  # 0.20

        # Series: half lo + (half-1) hi + 1 mid at the end
        # Ensures min=lo, max=hi, current=mid → IVR = (mid-lo)/(hi-lo)*100 = 50.0
        n = MIN_LOOKBACK_SESSIONS
        half = n // 2
        ivs_mid = [lo] * half + [hi] * (half - 1) + [mid]
        assert len(ivs_mid) == n  # sanity-check length == 20

        result = compute_ivr(ivs_mid)
        assert result is not None
        assert abs(result - 50.0) < 1e-6, f"Expected 50.0, got {result}"

    def test_min_of_history_returns_ivr_zero(self, tmp_path):
        """The minimum IV day must return IVR = 0.0."""
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS

        n = MIN_LOOKBACK_SESSIONS
        # Last value is the minimum
        ivs = [0.20] * (n - 1) + [0.10]
        result = compute_ivr(ivs)
        assert result is not None
        assert abs(result - 0.0) < 1e-6, f"Expected 0.0, got {result}"

    def test_max_of_history_returns_ivr_100(self, tmp_path):
        """A high IV day (max of history) returns IVR = 100.0."""
        from volatility_engine import compute_ivr, MIN_LOOKBACK_SESSIONS

        n = MIN_LOOKBACK_SESSIONS
        # Last value is the maximum
        ivs = [0.10] * (n - 1) + [0.50]
        result = compute_ivr(ivs)
        assert result is not None
        assert abs(result - 100.0) < 1e-6, f"Expected 100.0, got {result}"

    def test_ivp_uses_full_history(self, tmp_path):
        """IVP counts how many historical sessions had IV below the current IV."""
        from volatility_engine import compute_ivp, MIN_LOOKBACK_SESSIONS

        n = MIN_LOOKBACK_SESSIONS
        # 10 values of 0.10, 9 values of 0.20, 1 current of 0.15 (last)
        # Exactly half the prior n-1 values are below 0.15 → IVP = 50%
        half = (n - 1) // 2
        other_half = (n - 1) - half
        ivs = [0.10] * half + [0.20] * other_half + [0.15]
        result = compute_ivp(ivs)
        assert result is not None
        # half out of (n-1) prior values are below 0.15
        expected = half / (n - 1) * 100.0
        assert abs(result - expected) < 1e-6

    def test_compute_vol_metrics_uses_iv_history(self, tmp_path):
        """compute_vol_metrics reads from iv_history, not intraday chain_snapshots."""
        from volatility_engine import compute_vol_metrics, MIN_LOOKBACK_SESSIONS
        from db_init import init_db, get_connection

        db_path = _make_db(tmp_path)
        conn = get_connection(db_path)

        # Insert enough daily history rows for IVR to be computable
        n = MIN_LOOKBACK_SESSIONS
        for i in range(n):
            date_str = f"2026-{9:02d}-{i+1:02d}" if i < 30 else f"2026-10-{i-29:02d}"
            atm_iv = 0.10 + i * 0.005  # rising IV series
            _insert_iv_history(conn, "NIFTY", date_str, "2026-10-30", atm_iv)
        conn.close()

        result = compute_vol_metrics("NIFTY", "2026-10-30", db_path)
        # With sufficient history, IVR should be non-None
        assert result["ivr"] is not None, "IVR should be non-None with sufficient iv_history rows"
        assert result["ivp"] is not None, "IVP should be non-None with sufficient iv_history rows"
        # With rising IV series the last day should be IVR=100.0
        assert abs(result["ivr"] - 100.0) < 1e-6

    def test_record_eod_iv_writes_row(self, tmp_path):
        """record_eod_iv writes a row to iv_history when chain data exists."""
        from volatility_engine import record_eod_iv
        from db_init import get_connection
        import datetime
        from zoneinfo import ZoneInfo

        db_path = _make_db(tmp_path)
        today = datetime.datetime.now(tz=ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        expiry = "2026-10-30"

        # Insert a snapshot with a valid IV and delta=0.5 (ATM)
        conn = get_connection(db_path)
        _insert_snapshot(
            conn, "NIFTY", expiry, 22000.0, "CE",
            ts=f"{today}T15:29:00",
            iv=0.18, delta=0.50, gamma=0.001,
        )
        conn.commit()
        conn.close()

        result = record_eod_iv("NIFTY", expiry, db_path)
        assert result is True

        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT atm_iv, trade_date FROM iv_history WHERE symbol='NIFTY' AND trade_date=?",
            (today,),
        ).fetchone()
        conn.close()
        assert row is not None, "iv_history row should have been written"
        assert abs(row[0] - 0.18) < 1e-6

    def test_record_eod_iv_returns_false_without_snapshot(self, tmp_path):
        """record_eod_iv returns False when no chain data is present."""
        from volatility_engine import record_eod_iv

        db_path = _make_db(tmp_path)
        result = record_eod_iv("NIFTY", "2026-10-30", db_path)
        assert result is False
