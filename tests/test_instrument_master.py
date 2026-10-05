"""Unit tests for instrument_master.py using mock CSV fixtures.

Tests cover:
- correct UNDERLYING_SYMBOL matching
- correct EXCH_ID filtering (NSE vs BSE)
- correct SM_EXPIRY_DATE filtering (>= today only)
- near-month (earliest expiry) selection
- SECURITY_ID and LOT_SIZE extraction
- error path when no rows found
"""

import datetime
from datetime import timezone
import io
import csv
import pytest
import instrument_master as im


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv_text(rows: list[dict], fieldnames: list[str] | None = None) -> str:
    """Render a list of dicts as CSV text."""
    if not rows:
        return ""
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


_FIELDS = [
    "EXCH_ID", "SEGMENT", "SECURITY_ID", "ISIN", "INSTRUMENT",
    "UNDERLYING_SECURITY_ID", "UNDERLYING_SYMBOL", "SYMBOL_NAME",
    "DISPLAY_NAME", "INSTRUMENT_TYPE", "SERIES", "LOT_SIZE", "SM_EXPIRY_DATE",
]

_TODAY = datetime.date.today().isoformat()
_TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
_YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
_NEXT_MONTH = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()


def _row(
    underlying_symbol: str = "NIFTY",
    exch_id: str = "NSE",
    security_id: str = "1234",
    lot_size: str = "75",
    expiry: str = _TOMORROW,
    instrument: str = "FUTIDX",
) -> dict:
    return {
        "EXCH_ID": exch_id,
        "SEGMENT": "IDX_I",
        "SECURITY_ID": security_id,
        "ISIN": "INE000000001",
        "INSTRUMENT": instrument,
        "UNDERLYING_SECURITY_ID": "13",
        "UNDERLYING_SYMBOL": underlying_symbol,
        "SYMBOL_NAME": underlying_symbol,
        "DISPLAY_NAME": underlying_symbol,
        "INSTRUMENT_TYPE": "INDEX",
        "SERIES": "XX",
        "LOT_SIZE": lot_size,
        "SM_EXPIRY_DATE": expiry,
    }


def _inject_rows(rows: list[dict], monkeypatch):
    """Bypass HTTP/cache — inject rows directly into the module globals."""
    monkeypatch.setattr(im, "_loaded_rows", rows)
    monkeypatch.setattr(im, "_loaded_at", datetime.datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Tests: near-month security_id
# ---------------------------------------------------------------------------

class TestGetNearMonthSecurityId:
    def test_nse_nifty_returns_correct_security_id(self, monkeypatch):
        rows = [_row("NIFTY", "NSE", "1001", "65", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("NIFTY") == 1001

    def test_bse_sensex_returns_correct_security_id(self, monkeypatch):
        rows = [_row("SENSEX", "BSE", "5001", "20", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("SENSEX") == 5001

    def test_selects_near_month_when_multiple_expiries(self, monkeypatch):
        rows = [
            _row("NIFTY", "NSE", "9999", "65", _NEXT_MONTH),
            _row("NIFTY", "NSE", "1001", "65", _TOMORROW),
        ]
        _inject_rows(rows, monkeypatch)
        # near-month is TOMORROW (earliest)
        assert im.get_near_month_security_id("NIFTY") == 1001

    def test_excludes_expired_rows(self, monkeypatch):
        rows = [
            _row("NIFTY", "NSE", "8888", "65", _YESTERDAY),   # expired — excluded
            _row("NIFTY", "NSE", "1001", "65", _TOMORROW),    # valid
        ]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("NIFTY") == 1001

    def test_raises_when_no_futidx_rows(self, monkeypatch):
        rows = [_row("NIFTY", "NSE", "1001", "65", _TOMORROW, instrument="OPTIDX")]
        _inject_rows(rows, monkeypatch)
        with pytest.raises(RuntimeError, match="No FUTIDX rows found"):
            im.get_near_month_security_id("NIFTY")

    def test_raises_when_wrong_exchange(self, monkeypatch):
        # SENSEX must be BSE; NSE row should be filtered out
        rows = [_row("SENSEX", "NSE", "5001", "20", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        with pytest.raises(RuntimeError, match="No FUTIDX rows found"):
            im.get_near_month_security_id("SENSEX")

    def test_raises_when_symbol_not_found(self, monkeypatch):
        rows = [_row("NIFTY", "NSE", "1001", "65", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        with pytest.raises(RuntimeError, match="No FUTIDX rows found"):
            im.get_near_month_security_id("BANKNIFTY")

    def test_case_insensitive_symbol_match(self, monkeypatch):
        rows = [_row("NIFTY", "NSE", "1001", "65", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("nifty") == 1001

    def test_nse_banknifty(self, monkeypatch):
        rows = [_row("BANKNIFTY", "NSE", "2001", "30", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("BANKNIFTY") == 2001

    def test_nse_finnifty(self, monkeypatch):
        rows = [_row("FINNIFTY", "NSE", "3001", "60", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("FINNIFTY") == 3001

    def test_today_expiry_is_included(self, monkeypatch):
        # Expiry = today should still be included (>= today)
        rows = [_row("NIFTY", "NSE", "1001", "65", _TODAY)]
        _inject_rows(rows, monkeypatch)
        assert im.get_near_month_security_id("NIFTY") == 1001


# ---------------------------------------------------------------------------
# Tests: lot size
# ---------------------------------------------------------------------------

class TestGetLotSize:
    def test_nifty_lot_size(self, monkeypatch):
        rows = [_row("NIFTY", "NSE", "1001", "65", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_lot_size("NIFTY") == 65

    def test_sensex_lot_size(self, monkeypatch):
        rows = [_row("SENSEX", "BSE", "5001", "20", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_lot_size("SENSEX") == 20

    def test_banknifty_lot_size(self, monkeypatch):
        rows = [_row("BANKNIFTY", "NSE", "2001", "30", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_lot_size("BANKNIFTY") == 30

    def test_finnifty_lot_size(self, monkeypatch):
        rows = [_row("FINNIFTY", "NSE", "3001", "60", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        assert im.get_lot_size("FINNIFTY") == 60

    def test_lot_size_from_near_month_row(self, monkeypatch):
        # Lot sizes may differ across expiries (contract re-sizing);
        # we must return the near-month one.
        rows = [
            _row("NIFTY", "NSE", "9999", "50", _NEXT_MONTH),
            _row("NIFTY", "NSE", "1001", "65", _TOMORROW),
        ]
        _inject_rows(rows, monkeypatch)
        assert im.get_lot_size("NIFTY") == 65

    def test_raises_when_no_rows(self, monkeypatch):
        # Inject a row for a different symbol so NIFTY lookup returns no candidates
        rows = [_row("SENSEX", "BSE", "5001", "20", _TOMORROW)]
        _inject_rows(rows, monkeypatch)
        with pytest.raises(RuntimeError, match="No FUTIDX rows found"):
            im.get_lot_size("NIFTY")
