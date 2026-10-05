# =============================================================================
# P0.1 — MARKET-HOURS & HOLIDAY GATE
# Strict execution gate: 09:10–15:32 IST, Asia/Kolkata tz.
# No trade scan, alert, or quote walk may run on weekends, exchange holidays,
# or outside these bounds.
# =============================================================================
import datetime
import logging

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python 3.8 compat

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# NSE holiday list for 2026 (update annually from NSE circular).
# Format: "YYYY-MM-DD"
NSE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-03-31",  # Holi
    "2026-04-10",  # Good Friday
    "2026-04-14",  # Dr. B.R. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-09-22",  # Ganesh Chaturthi
    "2026-10-02",  # Gandhi Jayanti / Dussehra
    "2026-11-04",  # Diwali Laxmi Puja
    "2026-11-05",  # Diwali Balipratipada
    "2026-11-19",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}

# Allow loading a supplementary holiday file (one ISO date per line).
_HOLIDAY_FILE = "nse_holidays.txt"

def _load_extra_holidays() -> set:
    extras = set()
    try:
        with open(_HOLIDAY_FILE) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    extras.add(line)
    except FileNotFoundError:
        pass
    return extras


_ALL_HOLIDAYS: set | None = None


def _get_holidays() -> set:
    global _ALL_HOLIDAYS
    if _ALL_HOLIDAYS is None:
        _ALL_HOLIDAYS = NSE_HOLIDAYS_2026 | _load_extra_holidays()
    return _ALL_HOLIDAYS


# Gate bounds (IST)
MARKET_OPEN_HM = (9, 10)    # 09:10
MARKET_CLOSE_HM = (15, 32)  # 15:32


def is_market_open(now: datetime.datetime | None = None) -> tuple[bool, str]:
    """
    Returns (True, "OPEN") if current IST time is a valid trading moment,
    else (False, reason_string).

    Pass `now` (tz-aware or tz-naive in IST) for testing; omit for live use.
    """
    if now is None:
        now = datetime.datetime.now(tz=IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)

    # Convert to IST if needed
    now_ist = now.astimezone(IST)

    # Weekend check
    if now_ist.weekday() >= 5:
        reason = f"CLOSED_WEEKEND day={now_ist.strftime('%A')}"
        logger.info("Gate: %s", reason)
        return False, reason

    # Holiday check
    date_str = now_ist.strftime("%Y-%m-%d")
    if date_str in _get_holidays():
        reason = f"CLOSED_HOLIDAY date={date_str}"
        logger.info("Gate: %s", reason)
        return False, reason

    # Time window check
    hm = (now_ist.hour, now_ist.minute)
    if hm < MARKET_OPEN_HM:
        reason = f"CLOSED_PRE_MARKET time={now_ist.strftime('%H:%M')}"
        logger.info("Gate: %s", reason)
        return False, reason
    if hm > MARKET_CLOSE_HM:
        reason = f"CLOSED_POST_MARKET time={now_ist.strftime('%H:%M')}"
        logger.info("Gate: %s", reason)
        return False, reason

    return True, "OPEN"


def assert_market_open(context: str = "") -> None:
    """Raise RuntimeError (logged as DATA_FAULT) if market is closed."""
    open_flag, reason = is_market_open()
    if not open_flag:
        msg = f"DATA_FAULT market_hours_gate BLOCKED context={context!r} reason={reason}"
        logger.error(msg)
        raise RuntimeError(msg)
