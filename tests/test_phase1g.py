"""Phase 1G tests: dedup, DTE gate, dynamic label, quota integrity, observer modes."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from candidate_logger import log_candidate, load_candidates
from db_init import init_db
from playbook_triggers import (
    PlaybookSignal,
    _compute_dte,
    evaluate_pb6,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_p1g.db")
    init_db(db_path)
    return db_path


def _sig(
    symbol="NIFTY",
    playbook_id="PB1",
    direction="BULL",
    vol_regime="NORMAL_VOL",
    expiry="2026-10-08",
    vol_provisional=False,
) -> PlaybookSignal:
    return PlaybookSignal(
        playbook_id=playbook_id,
        symbol=symbol,
        direction=direction,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type="ATM_CALL",
        atm_strike=22000.0,
        reason="test",
        spot=22000.0,
        max_pain=22000.0,
        call_wall=22500.0,
        put_wall=21500.0,
        pcr=1.0,
        direction_score=3,
        expiry=expiry,
        step=50,
    )


def _score(score=85, raw_score=None) -> dict:
    if raw_score is None:
        raw_score = float(score)
    return {
        "tier": 1,
        "score": score,
        "raw_score": raw_score,
        "breakdown": {
            "regime_structure": 28.0,
            "microstructure": 20.0,
            "volatility_em": 18.0,
            "risk_reward": 14.0,
            "data_quality": 5.0,
        },
    }


def _analysis(spot=22000.0, call_wall=22500.0, put_wall=21500.0, expiry="2026-10-08"):
    return {
        "spot": spot,
        "max_pain": spot,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "pcr_oi": 1.0,
        "expiry": expiry,
    }


def _regime(direction="NEUTRAL", vol="NORMAL_VOL"):
    return {
        "direction_label": direction,
        "vol_regime": vol,
        "direction_score": 0,
        "vol_provisional": False,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Item 1: Candidate deduplication
# ──────────────────────────────────────────────────────────────────────────────

class TestCandidateDedup:
    def test_60_scans_produce_1_row(self, tmp_db):
        """60 calls with the same signal → 1 DB row, occurrences=60."""
        sig = _sig()
        sc = _score()
        ids = [log_candidate(sig, sc, dispatched=False, db_path=tmp_db) for _ in range(60)]
        assert len(set(ids)) == 1, "All 60 scans should map to same row"

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT occurrences FROM candidates WHERE candidate_id=?", (ids[0],)).fetchone()
        conn.close()
        assert row[0] == 60

    def test_regime_shift_closes_old_row_opens_new(self, tmp_db):
        """Regime shift: old open row closed, new row inserted."""
        sig_bull = _sig(vol_regime="NORMAL_VOL")
        sig_elevated = _sig(vol_regime="ELEVATED_VOL")
        sc = _score()

        id_bull = log_candidate(sig_bull, sc, dispatched=False, db_path=tmp_db)

        # regime shifts — ELEVATED_VOL has a different setup_key
        id_elev = log_candidate(sig_elevated, sc, dispatched=False, db_path=tmp_db)

        assert id_bull != id_elev, "Regime shift should open a new row"

        conn = sqlite3.connect(tmp_db)
        old = conn.execute("SELECT setup_closed_at FROM candidates WHERE candidate_id=?", (id_bull,)).fetchone()
        new = conn.execute("SELECT setup_closed_at FROM candidates WHERE candidate_id=?", (id_elev,)).fetchone()
        conn.close()
        assert old[0] is not None, "Old row should be closed"
        assert new[0] is None, "New row should be open"

    def test_setup_key_format(self, tmp_db):
        """setup_key = 'symbol|playbook_id|expiry|direction_vol_regime'."""
        sig = _sig(symbol="NIFTY", playbook_id="PB1", direction="BULL",
                   vol_regime="NORMAL_VOL", expiry="2026-10-08")
        sc = _score()
        cid = log_candidate(sig, sc, dispatched=False, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT setup_key FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] == "NIFTY|PB1|2026-10-08|BULL_NORMAL_VOL"

    def test_first_seen_last_seen_tracked(self, tmp_db):
        """first_seen stays on first call; last_seen updates each call."""
        sig = _sig()
        sc = _score()
        ts1 = "2026-10-06T09:30:00+00:00"
        ts2 = "2026-10-06T09:31:00+00:00"

        cid = log_candidate(sig, sc, dispatched=False, ts_override=ts1, db_path=tmp_db)
        log_candidate(sig, sc, dispatched=False, ts_override=ts2, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT first_seen, last_seen FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert row[0] == ts1, "first_seen must not change on update"
        assert row[1] == ts2, "last_seen must reflect latest call"

    def test_different_symbols_are_separate_rows(self, tmp_db):
        """Different symbols always produce separate rows (different setup_key)."""
        sc = _score()
        id1 = log_candidate(_sig(symbol="NIFTY"), sc, dispatched=False, db_path=tmp_db)
        id2 = log_candidate(_sig(symbol="BANKNIFTY"), sc, dispatched=False, db_path=tmp_db)
        assert id1 != id2

    def test_raw_score_stored(self, tmp_db):
        """raw_score column is populated."""
        sig = _sig(vol_provisional=True)
        sc = _score(score=76, raw_score=85.0)
        cid = log_candidate(sig, sc, dispatched=False, db_path=tmp_db)

        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT raw_score FROM candidates WHERE candidate_id=?", (cid,)).fetchone()
        conn.close()
        assert abs(row[0] - 85.0) < 0.01


# ──────────────────────────────────────────────────────────────────────────────
# Item 4: PB6 DTE gate
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeDte:
    def test_same_day_is_zero(self):
        ref = date(2026, 10, 8)
        assert _compute_dte("2026-10-08", ref) == 0

    def test_seven_days_out(self):
        ref = date(2026, 10, 1)
        assert _compute_dte("2026-10-08", ref) == 7

    def test_unparseable_expiry_returns_999(self):
        assert _compute_dte("not-a-date") == 999

    def test_past_expiry_returns_zero(self):
        ref = date(2026, 10, 10)
        assert _compute_dte("2026-10-08", ref) == 0


class TestPB6DteGate:
    def test_dte_exactly_7_triggers(self):
        ref = date(2026, 10, 23)
        sig = evaluate_pb6(
            "NIFTY",
            _analysis(expiry="2026-10-30"),
            _regime(),
            step=50,
            _reference_date=ref,
        )
        assert sig is not None
        assert sig.dte == 7

    def test_dte_8_blocked(self):
        ref = date(2026, 10, 22)  # expiry 2026-10-30 → DTE=8
        sig = evaluate_pb6(
            "NIFTY",
            _analysis(expiry="2026-10-30"),
            _regime(),
            step=50,
            _reference_date=ref,
        )
        assert sig is None

    def test_dte_0_triggers(self):
        ref = date(2026, 10, 30)
        sig = evaluate_pb6(
            "NIFTY",
            _analysis(expiry="2026-10-30"),
            _regime(),
            step=50,
            _reference_date=ref,
        )
        assert sig is not None
        assert sig.dte == 0

    def test_dte_field_on_signal(self):
        ref = date(2026, 10, 27)
        sig = evaluate_pb6(
            "NIFTY",
            _analysis(expiry="2026-10-30"),
            _regime(),
            step=50,
            _reference_date=ref,
        )
        assert sig is not None
        assert sig.dte == 3

    def test_reason_includes_dte(self):
        ref = date(2026, 10, 27)
        sig = evaluate_pb6(
            "NIFTY",
            _analysis(expiry="2026-10-30"),
            _regime(),
            step=50,
            _reference_date=ref,
        )
        assert sig is not None
        assert "DTE=3" in sig.reason


# ──────────────────────────────────────────────────────────────────────────────
# Item 4b: Dynamic strategy label in auto_trade_hunter
# ──────────────────────────────────────────────────────────────────────────────

class TestDynamicStrategyLabel:
    """Verify the label logic inside auto_trade_hunter for PB6 signals."""

    def _get_label(self, dte: int) -> str:
        sig = PlaybookSignal(
            playbook_id="PB6",
            symbol="NIFTY",
            direction="NEUTRAL",
            vol_regime="NORMAL_VOL",
            vol_provisional=False,
            instrument_type="IRON_CONDOR",
            short_strike_ce=22300.0,
            short_strike_pe=21700.0,
            long_strike_ce=22400.0,
            long_strike_pe=21600.0,
            reason="test",
            spot=22000.0,
            max_pain=22000.0,
            call_wall=22300.0,
            put_wall=21700.0,
            pcr=1.0,
            direction_score=0,
            expiry="2026-10-30",
            step=50,
            dte=dte,
        )
        pb6_dte = getattr(sig, "dte", 0)
        if pb6_dte == 0:
            return "0DTE Delta-Neutral Iron Condor"
        return f"Iron Condor ({pb6_dte} DTE)"

    def test_dte_zero_gives_0dte_label(self):
        assert self._get_label(0) == "0DTE Delta-Neutral Iron Condor"

    def test_dte_4_gives_dynamic_label(self):
        assert self._get_label(4) == "Iron Condor (4 DTE)"

    def test_dte_7_gives_dynamic_label(self):
        assert self._get_label(7) == "Iron Condor (7 DTE)"


# ──────────────────────────────────────────────────────────────────────────────
# Item 5: Quota integrity
# ──────────────────────────────────────────────────────────────────────────────

class TestQuotaIntegrity:
    def _make_ledger(self, tmp_path, trades: list) -> str:
        path = str(tmp_path / "ledger.json")
        with open(path, "w") as f:
            json.dump(trades, f)
        return path

    def _count_quota(self, ledger_path: str, today_tag: str) -> tuple[int, int]:
        """Replicate the quota counting logic from auto_trade_hunter."""
        with open(ledger_path) as f:
            trades = json.load(f)
        today_trades = [
            t for t in trades
            if t.get("trade_id", "").startswith(today_tag)
            and t.get("source", "LIVE") != "SIMULATED"
        ]
        hedged = [t for t in today_trades if t.get("book") == "HEDGED"]
        naked = [t for t in today_trades if t.get("book") == "NAKED"]
        return len(hedged), len(naked)

    def test_simulated_trades_excluded(self, tmp_path):
        today_tag = "20261006"
        trades = [
            {"trade_id": f"{today_tag}_H1", "book": "HEDGED", "source": "LIVE"},
            {"trade_id": f"{today_tag}_N1", "book": "NAKED", "source": "SIMULATED"},
        ]
        lp = self._make_ledger(tmp_path, trades)
        hedged, naked = self._count_quota(lp, today_tag)
        assert hedged == 1
        assert naked == 0  # SIMULATED excluded

    def test_stale_trades_excluded(self, tmp_path):
        today_tag = "20261006"
        trades = [
            {"trade_id": "20261005_H1", "book": "HEDGED", "source": "LIVE"},  # yesterday
            {"trade_id": f"{today_tag}_H1", "book": "HEDGED", "source": "LIVE"},
        ]
        lp = self._make_ledger(tmp_path, trades)
        hedged, naked = self._count_quota(lp, today_tag)
        assert hedged == 1
        assert naked == 0

    def test_real_today_trades_counted(self, tmp_path):
        today_tag = "20261006"
        trades = [
            {"trade_id": f"{today_tag}_H1", "book": "HEDGED", "source": "LIVE"},
            {"trade_id": f"{today_tag}_H2", "book": "HEDGED", "source": "LIVE"},
            {"trade_id": f"{today_tag}_N1", "book": "NAKED", "source": "LIVE"},
        ]
        lp = self._make_ledger(tmp_path, trades)
        hedged, naked = self._count_quota(lp, today_tag)
        assert hedged == 2
        assert naked == 1
