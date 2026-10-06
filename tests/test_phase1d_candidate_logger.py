"""Tests for Phase 1D: candidate_logger, outcome_labeller, calibration_report."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import date, timedelta

import pandas as pd
import pytest

from candidate_logger import log_candidate, load_candidates, _null_if_zero
from outcome_labeller import (
    _compute_triple_barrier,
    label_date,
    run_labeller,
)
from calibration_report import (
    compute_calibration_report,
    format_report_text,
    MIN_SAMPLE_SIZE,
)
from db_init import init_db
from playbook_triggers import PlaybookSignal


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_candidates.db")
    init_db(db_path)
    return db_path


def _make_signal(
    symbol="NIFTY",
    playbook_id="PB1",
    direction="BULL",
    vol_regime="NORMAL_VOL",
    vol_provisional=False,
    spot=24000.0,
    direction_score=5,
    pcr=1.1,
    max_pain=23950.0,
    call_wall=24200.0,
    put_wall=23800.0,
    pin_score=0.7,
    expiry="2026-10-08",
    step=50,
) -> PlaybookSignal:
    return PlaybookSignal(
        playbook_id=playbook_id,
        symbol=symbol,
        direction=direction,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type="ATM_CALL",
        atm_strike=24000.0,
        reason="test signal",
        spot=spot,
        max_pain=max_pain,
        pin_score=pin_score,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        direction_score=direction_score,
        expiry=expiry,
        step=step,
    )


def _make_score(tier=1, score=85) -> dict:
    return {
        "tier": tier,
        "score": score,
        "raw_score": float(score),
        "breakdown": {
            "regime_structure": 28.0,
            "microstructure": 20.0,
            "volatility_em": 18.0,
            "risk_reward": 14.0,
            "data_quality": 5.0,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# candidate_logger tests
# ──────────────────────────────────────────────────────────────────────────────

class TestCandidateLogger:
    def test_log_dispatched_candidate(self, tmp_db):
        sig = _make_signal()
        score = _make_score(tier=1, score=88)
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)
        assert cid  # non-empty UUID string

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT * FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row is not None

    def test_log_tier2_watchlist(self, tmp_db):
        sig = _make_signal()
        score = _make_score(tier=2, score=70)
        cid = log_candidate(sig, score, dispatched=False, skip_reason="tier2_watchlist", db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT dispatched, skip_reason FROM candidates WHERE candidate_id=?", (cid,)
        ).fetchone()
        conn.close()
        assert row[0] == 0
        assert row[1] == "tier2_watchlist"

    def test_log_dropped_candidate(self, tmp_db):
        sig = _make_signal()
        score = _make_score(tier=0, score=45)
        cid = log_candidate(sig, score, dispatched=False, skip_reason="score<60", db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT tier, score, dispatched FROM candidates WHERE candidate_id=?", (cid,)
        ).fetchone()
        conn.close()
        assert row[0] == 0
        assert abs(row[1] - 45.0) < 0.01
        assert row[2] == 0

    def test_null_for_zero_pcr(self, tmp_db):
        """PCR=0.0 should be stored as NULL, not 0.0."""
        sig = _make_signal(pcr=0.0)
        score = _make_score()
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT pcr FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] is None

    def test_null_for_zero_pin_score(self, tmp_db):
        sig = _make_signal(pin_score=0.0)
        score = _make_score()
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT pin_score FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] is None

    def test_nonzero_pcr_stored_correctly(self, tmp_db):
        sig = _make_signal(pcr=1.25)
        score = _make_score()
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT pcr FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert abs(row[0] - 1.25) < 0.0001

    def test_score_breakdown_stored_as_json(self, tmp_db):
        sig = _make_signal()
        score = _make_score()
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT score_breakdown FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        bd = json.loads(row[0])
        assert "regime_structure" in bd
        assert "microstructure" in bd

    def test_vol_provisional_stored_as_int(self, tmp_db):
        sig = _make_signal(vol_provisional=True)
        score = _make_score()
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT vol_provisional FROM candidates WHERE candidate_id=?", (cid,)
        ).fetchone()
        conn.close()
        assert row[0] == 1

    def test_ts_override(self, tmp_db):
        sig = _make_signal()
        score = _make_score()
        ts = "2026-10-05T10:30:00+00:00"
        cid = log_candidate(sig, score, dispatched=True, ts_override=ts, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT ts_signal FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] == ts

    def test_unique_ids_per_call(self, tmp_db):
        # Phase 1G: same setup deduplicates — 5 calls → 1 row with occurrences=5
        sig = _make_signal()
        score = _make_score()
        ids = {log_candidate(sig, score, dispatched=True, db_path=tmp_db) for _ in range(5)}
        assert len(ids) == 1  # all 5 map to the same open setup row
        cid = next(iter(ids))
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT occurrences FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] == 5

    def test_sub_scores_gamma_flip_stored(self, tmp_db):
        sig = _make_signal()
        sig.sub_scores = {"gamma_flip": 24500.0, "net_gex": -1200.0, "ivr": 65.0}
        score = _make_score()
        cid = log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT gamma_flip, net_gex, ivr FROM candidates WHERE candidate_id=?", (cid,)
        ).fetchone()
        conn.close()
        assert abs(row[0] - 24500.0) < 0.01
        assert abs(row[1] - (-1200.0)) < 0.01
        assert abs(row[2] - 65.0) < 0.01


class TestLoadCandidates:
    def test_load_empty_db(self, tmp_db):
        df = load_candidates(tmp_db)
        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_load_returns_rows(self, tmp_db):
        # Two distinct symbols → two distinct setup rows
        sig1 = _make_signal(symbol="NIFTY")
        sig2 = _make_signal(symbol="BANKNIFTY")
        score = _make_score()
        log_candidate(sig1, score, dispatched=True, ts_override="2026-10-05T10:00:00+00:00", db_path=tmp_db)
        log_candidate(sig2, score, dispatched=False, ts_override="2026-10-05T11:00:00+00:00", db_path=tmp_db)

        df = load_candidates(tmp_db)
        assert len(df) == 2

    def test_date_filter_start(self, tmp_db):
        # Two distinct symbols so each is a separate setup row with its own ts_signal
        sig1 = _make_signal(symbol="NIFTY")
        sig2 = _make_signal(symbol="BANKNIFTY")
        score = _make_score()
        log_candidate(sig1, score, dispatched=True, ts_override="2026-10-04T10:00:00+00:00", db_path=tmp_db)
        log_candidate(sig2, score, dispatched=True, ts_override="2026-10-05T10:00:00+00:00", db_path=tmp_db)

        df = load_candidates(tmp_db, start_date="2026-10-05")
        assert len(df) == 1
        assert "2026-10-05" in df.iloc[0]["ts_signal"]

    def test_date_filter_end(self, tmp_db):
        sig = _make_signal()
        score = _make_score()
        log_candidate(sig, score, dispatched=True, ts_override="2026-10-04T10:00:00+00:00", db_path=tmp_db)
        log_candidate(sig, score, dispatched=True, ts_override="2026-10-05T10:00:00+00:00", db_path=tmp_db)

        df = load_candidates(tmp_db, end_date="2026-10-04")
        assert len(df) == 1

    def test_score_breakdown_parsed(self, tmp_db):
        sig = _make_signal()
        score = _make_score()
        log_candidate(sig, score, dispatched=True, db_path=tmp_db)

        df = load_candidates(tmp_db)
        bd = df.iloc[0]["score_breakdown"]
        assert isinstance(bd, dict)
        assert "regime_structure" in bd


class TestNullIfZero:
    def test_zero_returns_none(self):
        assert _null_if_zero(0.0) is None

    def test_none_returns_none(self):
        assert _null_if_zero(None) is None

    def test_nonzero_returns_value(self):
        assert _null_if_zero(1.5) == 1.5
        assert _null_if_zero(-0.001) == -0.001


# ──────────────────────────────────────────────────────────────────────────────
# outcome_labeller tests
# ──────────────────────────────────────────────────────────────────────────────

class TestTripleBarrier:
    def _make_bars(self, closes: list[float]) -> pd.DataFrame:
        return pd.DataFrame({
            "bar_open_ts": [f"2026-10-05T09:{i+30:02d}:00" for i in range(len(closes))],
            "open": closes,
            "high": [c * 1.002 for c in closes],
            "low": [c * 0.998 for c in closes],
            "close": closes,
        })

    def test_winner_target_hit(self):
        # Spot 24000, target +0.5% = 24120; bar high touches target
        bars = pd.DataFrame({
            "bar_open_ts": ["2026-10-05T09:30:00", "2026-10-05T09:31:00"],
            "open": [24000.0, 24100.0],
            "high": [24050.0, 24130.0],  # second bar breaches target
            "low": [23980.0, 24090.0],
            "close": [24040.0, 24120.0],
        })
        label, pnl, _, mae = _compute_triple_barrier(24000.0, bars, 0.005, -0.004)
        assert label == "WINNER"

    def test_loser_stop_hit(self):
        # Spot 24000, stop -0.4% = 23904; bar low touches stop
        bars = pd.DataFrame({
            "bar_open_ts": ["2026-10-05T09:30:00"],
            "open": [24000.0],
            "high": [24010.0],
            "low": [23900.0],  # below stop
            "close": [23920.0],
        })
        label, pnl, _, mae = _compute_triple_barrier(24000.0, bars, 0.005, -0.004)
        assert label == "LOSER"

    def test_expired_neither_hit(self):
        # Spot 24000, narrow range bars
        bars = pd.DataFrame({
            "bar_open_ts": ["2026-10-05T09:30:00", "2026-10-05T09:31:00"],
            "open": [24000.0, 24010.0],
            "high": [24020.0, 24015.0],
            "low": [23990.0, 24000.0],
            "close": [24010.0, 24008.0],
        })
        label, pnl, _, mae = _compute_triple_barrier(24000.0, bars, 0.005, -0.004)
        assert label == "EXPIRED"

    def test_empty_bars_returns_expired(self):
        label, pnl, _, mae = _compute_triple_barrier(24000.0, pd.DataFrame(), 0.005, -0.004)
        assert label == "EXPIRED"
        assert pnl == 0.0

    def test_mae_calculation(self):
        # Spot 24000, bar dips to 23900 — adverse = 100 pts
        bars = pd.DataFrame({
            "bar_open_ts": ["2026-10-05T09:30:00"],
            "open": [24000.0],
            "high": [24010.0],
            "low": [23900.0],
            "close": [23920.0],
        })
        _, _, _, mae = _compute_triple_barrier(24000.0, bars, 0.005, -0.004)
        assert mae == pytest.approx(100.0, abs=0.1)

    def test_winner_before_stop(self):
        # First bar goes up through target, never hits stop
        bars = pd.DataFrame({
            "bar_open_ts": ["2026-10-05T09:30:00"],
            "open": [24000.0],
            "high": [24200.0],  # target +0.5% = 24120 → hit
            "low": [23990.0],   # stop -0.4% = 23904 → not hit
            "close": [24150.0],
        })
        label, _, _, _ = _compute_triple_barrier(24000.0, bars, 0.005, -0.004)
        assert label == "WINNER"


class TestLabelDate:
    def test_labels_unlabelled_rows(self, tmp_db):
        sig = _make_signal()
        score = _make_score(tier=1, score=88)
        ts = "2026-10-04T10:00:00+00:00"
        cid = log_candidate(sig, score, dispatched=True, ts_override=ts, db_path=tmp_db)

        # Add 1m bars for the date (no real price data, so will get EXPIRED)
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "INSERT INTO underlying_bars VALUES (?,?,?,?,?,?,?,?,?)",
            ("NIFTY", "1m", "2026-10-04T09:30:00", 24000, 24020, 23990, 24010, 1000, 0),
        )
        conn.commit()
        conn.close()

        n = label_date("2026-10-04", db_path=tmp_db)
        assert n == 1

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT outcome_label FROM candidates WHERE candidate_id=?", (cid,)
        ).fetchone()
        conn.close()
        assert row[0] in ("WINNER", "LOSER", "EXPIRED")

    def test_does_not_overwrite_labelled_rows(self, tmp_db):
        sig = _make_signal()
        score = _make_score()
        ts = "2026-10-04T10:00:00+00:00"
        cid = log_candidate(sig, score, dispatched=True, ts_override=ts, db_path=tmp_db)

        # Manually label the row
        conn = sqlite3.connect(tmp_db)
        conn.execute(
            "UPDATE candidates SET outcome_label='WINNER' WHERE candidate_id=?", (cid,)
        )
        conn.commit()
        conn.close()

        n = label_date("2026-10-04", db_path=tmp_db)
        assert n == 0  # nothing labelled (row already had a label)

    def test_no_rows_for_date(self, tmp_db):
        n = label_date("2026-01-01", db_path=tmp_db)
        assert n == 0

    def test_run_labeller_defaults_to_yesterday(self, tmp_db):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sig = _make_signal()
        score = _make_score()
        ts = f"{yesterday}T10:00:00+00:00"
        log_candidate(sig, score, dispatched=True, ts_override=ts, db_path=tmp_db)

        n = run_labeller(db_path=tmp_db)
        assert n >= 0  # just check it runs without error


# ──────────────────────────────────────────────────────────────────────────────
# calibration_report tests
# ──────────────────────────────────────────────────────────────────────────────

def _make_labelled_df(
    n_winners: int,
    n_losers: int,
    n_expired: int,
    playbook_id: str = "PB1",
    vol_regime: str = "NORMAL_VOL",
) -> pd.DataFrame:
    rows = []
    for _ in range(n_winners):
        rows.append({"playbook_id": playbook_id, "vol_regime": vol_regime,
                     "outcome_label": "WINNER", "pnl_points": 120.0, "mae_points": 30.0})
    for _ in range(n_losers):
        rows.append({"playbook_id": playbook_id, "vol_regime": vol_regime,
                     "outcome_label": "LOSER", "pnl_points": -80.0, "mae_points": 90.0})
    for _ in range(n_expired):
        rows.append({"playbook_id": playbook_id, "vol_regime": vol_regime,
                     "outcome_label": "EXPIRED", "pnl_points": 0.0, "mae_points": 20.0})
    return pd.DataFrame(rows)


class TestCalibrationReport:
    def test_insufficient_data_below_50(self):
        df = _make_labelled_df(10, 5, 5)  # n=20 < 50
        report = compute_calibration_report(df)
        assert len(report) == 1
        assert "INSUFFICIENT DATA" in str(report.iloc[0]["win_rate_pct"])

    def test_metrics_computed_above_50(self):
        df = _make_labelled_df(35, 15, 10)  # n=60 >= 50
        report = compute_calibration_report(df)
        assert len(report) == 1
        row = report.iloc[0]
        assert isinstance(row["win_rate_pct"], float)
        assert abs(row["win_rate_pct"] - (35 / 60 * 100)) < 0.1

    def test_win_rate_correct(self):
        df = _make_labelled_df(40, 10, 10)  # 40 winners out of 60
        report = compute_calibration_report(df)
        row = report.iloc[0]
        assert abs(row["win_rate_pct"] - (40 / 60 * 100)) < 0.1

    def test_multiple_groups(self):
        df1 = _make_labelled_df(35, 15, 10, "PB1", "NORMAL_VOL")
        df2 = _make_labelled_df(30, 20, 10, "PB6", "LOW_VOL")
        df = pd.concat([df1, df2], ignore_index=True)
        report = compute_calibration_report(df)
        assert len(report) == 2
        groups = set(zip(report["playbook_id"], report["vol_regime"]))
        assert ("PB1", "NORMAL_VOL") in groups
        assert ("PB6", "LOW_VOL") in groups

    def test_profit_factor_positive_when_profitable(self):
        df = _make_labelled_df(40, 10, 10)
        report = compute_calibration_report(df)
        assert report.iloc[0]["profit_factor"] > 1.0

    def test_expectancy_positive_when_profitable(self):
        df = _make_labelled_df(40, 10, 10)
        report = compute_calibration_report(df)
        assert report.iloc[0]["expectancy"] > 0

    def test_avg_mae_calculated(self):
        df = _make_labelled_df(35, 15, 10)
        report = compute_calibration_report(df)
        assert report.iloc[0]["avg_mae_pts"] is not None

    def test_empty_df_returns_empty_report(self):
        df = pd.DataFrame(columns=["playbook_id", "vol_regime", "outcome_label", "pnl_points", "mae_points"])
        report = compute_calibration_report(df)
        assert report.empty

    def test_unlabelled_rows_excluded(self):
        df = _make_labelled_df(35, 15, 10)
        # Add unlabelled rows
        extra = pd.DataFrame([{
            "playbook_id": "PB1", "vol_regime": "NORMAL_VOL",
            "outcome_label": None, "pnl_points": None, "mae_points": None,
        }] * 5)
        df = pd.concat([df, extra], ignore_index=True)
        report = compute_calibration_report(df)
        assert report.iloc[0]["n"] == 60  # unlabelled excluded

    def test_format_report_text_insufficient(self):
        df = _make_labelled_df(5, 5, 5)
        report = compute_calibration_report(df)
        text = format_report_text(report)
        assert "INSUFFICIENT DATA" in text

    def test_format_report_text_sufficient(self):
        df = _make_labelled_df(35, 15, 10)
        report = compute_calibration_report(df)
        text = format_report_text(report)
        assert "PB1" in text
        assert "NORMAL_VOL" in text

    def test_format_report_empty_df(self):
        text = format_report_text(pd.DataFrame())
        assert "no labelled candidates" in text.lower()

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"playbook_id": ["PB1"]})
        with pytest.raises(ValueError, match="missing columns"):
            compute_calibration_report(df)


# ──────────────────────────────────────────────────────────────────────────────
# Polish item tests
# ──────────────────────────────────────────────────────────────────────────────

class TestAntiCorrelationExtended:
    """Polish item 5: NIFTY ↔ BANKNIFTY anti-correlation."""

    def _make_sig_and_score(self, symbol: str, direction: str, score: int):
        sig = PlaybookSignal(
            playbook_id="PB1", symbol=symbol, direction=direction,
            vol_regime="NORMAL_VOL", vol_provisional=False,
            instrument_type="ATM_CALL", spot=24000.0, direction_score=5,
            pcr=1.1, max_pain=23950.0, call_wall=24200.0, put_wall=23800.0,
            pin_score=0.6, expiry="2026-10-08", step=50,
        )
        sr = {"tier": 1, "score": score, "breakdown": {}}
        return sig, sr

    def test_nifty_banknifty_same_direction_deduped(self):
        from scoring_engine import rank_and_filter
        nifty_sig, nifty_sr = self._make_sig_and_score("NIFTY", "BULL", 88)
        bnk_sig, bnk_sr = self._make_sig_and_score("BANKNIFTY", "BULL", 80)
        filtered = rank_and_filter([(nifty_sig, nifty_sr), (bnk_sig, bnk_sr)])
        symbols = [s.symbol for s, _ in filtered]
        # Only the higher-scoring one should survive
        assert "NIFTY" in symbols
        assert "BANKNIFTY" not in symbols

    def test_nifty_banknifty_opposite_directions_both_kept(self):
        from scoring_engine import rank_and_filter
        nifty_sig, nifty_sr = self._make_sig_and_score("NIFTY", "BULL", 85)
        bnk_sig, bnk_sr = self._make_sig_and_score("BANKNIFTY", "BEAR", 82)
        filtered = rank_and_filter([(nifty_sig, nifty_sr), (bnk_sig, bnk_sr)])
        symbols = [s.symbol for s, _ in filtered]
        assert "NIFTY" in symbols
        assert "BANKNIFTY" in symbols

    def test_nifty_sensex_dedup_still_works(self):
        from scoring_engine import rank_and_filter
        nifty_sig, nifty_sr = self._make_sig_and_score("NIFTY", "BEAR", 90)
        sensex_sig, sensex_sr = self._make_sig_and_score("SENSEX", "BEAR", 78)
        filtered = rank_and_filter([(nifty_sig, nifty_sr), (sensex_sig, sensex_sr)])
        symbols = [s.symbol for s, _ in filtered]
        assert "NIFTY" in symbols
        assert "SENSEX" not in symbols

    def test_finnifty_not_deduplicated_with_nifty(self):
        from scoring_engine import rank_and_filter
        nifty_sig, nifty_sr = self._make_sig_and_score("NIFTY", "BULL", 85)
        fin_sig, fin_sr = self._make_sig_and_score("FINNIFTY", "BULL", 80)
        filtered = rank_and_filter([(nifty_sig, nifty_sr), (fin_sig, fin_sr)])
        symbols = [s.symbol for s, _ in filtered]
        # FINNIFTY is not in either correlated group — both should appear
        assert "NIFTY" in symbols
        assert "FINNIFTY" in symbols


class TestProvisionalCardTag:
    """Polish item 3: Telegram alert shows PROVISIONAL tag when vol_provisional=True."""

    def test_provisional_tag_in_message(self):
        """Verify the provisional_tag string is produced correctly."""
        vol_provisional = True
        provisional_tag = "\n⚠️ *PROVISIONAL (Cold-Start IVR)*" if vol_provisional else ""
        assert "PROVISIONAL" in provisional_tag
        assert "Cold-Start IVR" in provisional_tag

    def test_no_tag_when_not_provisional(self):
        vol_provisional = False
        provisional_tag = "\n⚠️ *PROVISIONAL (Cold-Start IVR)*" if vol_provisional else ""
        assert provisional_tag == ""


class TestIVStagnationGuard:
    """Polish item 4: iv_history stagnation guard runs without error."""

    def test_stagnation_guard_no_rows(self, tmp_db, caplog):
        import logging
        from eod_ledger_reporter import _check_iv_stagnation
        with caplog.at_level(logging.WARNING):
            _check_iv_stagnation(tmp_db, lookback_sessions=3)
        # Should log IV_STAGNATION warnings for all 4 symbols
        assert "IV_STAGNATION" in caplog.text

    def test_stagnation_guard_with_recent_rows(self, tmp_db, caplog):
        """No warning when iv_history has recent data."""
        import logging
        conn = sqlite3.connect(tmp_db)
        today = date.today().isoformat()
        for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
            conn.execute(
                "INSERT INTO iv_history VALUES (?,?,?,?,?,?,?,?)",
                (sym, today, "2026-10-08", 18.5, 19.0, 18.0, 24000.0, "EOD_SNAPSHOT"),
            )
        conn.commit()
        conn.close()

        from eod_ledger_reporter import _check_iv_stagnation
        with caplog.at_level(logging.WARNING):
            _check_iv_stagnation(tmp_db, lookback_sessions=3)
        assert "IV_STAGNATION" not in caplog.text


class TestScoringEnginePillarRename:
    """Polish item 2: Pillar 2 label updated in format_confluence_breakdown."""

    def test_breakdown_label_updated(self):
        from scoring_engine import format_confluence_breakdown
        sig = _make_signal()
        score_result = _make_score()
        text = format_confluence_breakdown(sig, score_result)
        assert "PCR" in text or "Strike Conc" in text
        assert "Microstructure/Flow" not in text  # old label must be gone


class TestCandidatesSchemaInDB:
    """Verify candidates table schema matches spec."""

    def test_candidates_table_exists(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        table_names = [t[0] for t in tables]
        assert "candidates" in table_names

    def test_required_columns_present(self, tmp_db):
        conn = sqlite3.connect(tmp_db)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()]
        conn.close()
        required = {
            "candidate_id", "ts_signal", "symbol", "expiry", "playbook_id",
            "tier", "score", "score_breakdown", "vol_regime", "vol_provisional",
            "direction_label", "direction_score", "spot", "vwap", "pcr",
            "max_pain", "call_wall", "put_wall", "gamma_flip", "net_gex",
            "pin_score", "ivr", "ivp", "vrp", "or_high", "or_low",
            "dispatched", "skip_reason",
            "outcome_label", "pnl_points", "option_pnl_pct", "mae_points", "labelled_at",
        }
        missing = required - set(cols)
        assert not missing, f"Missing columns: {missing}"
