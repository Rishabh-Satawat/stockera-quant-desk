"""Playbook Trigger Evaluators — Phase 1C.

Implements institutional trigger logic for the three core production playbooks:
  PB1  Directional Trend Continuation
  PB2  Mean Reversion / Max Pain Pinning
  PB6  Steady-State 0DTE Theta Condor

Each evaluator returns a PlaybookSignal (or None) carrying the playbook id,
the instrument specification, the reason text, and raw sub-scores that the
scoring engine uses to compute the composite confluence score.

All inputs come from the regime_engine result and the chain microstructure
analysis dict — no live network calls are made here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PlaybookSignal:
    """Output of a successful playbook trigger evaluation."""

    playbook_id: str        # "PB1", "PB2", "PB6"
    symbol: str
    direction: str          # "BULL", "BEAR", "NEUTRAL"
    vol_regime: str
    vol_provisional: bool

    # Instrument spec (what to trade)
    instrument_type: str    # e.g. "ATM_CALL", "ATM_PUT", "IRON_BUTTERFLY", "IRON_CONDOR"
    short_strike_ce: Optional[float] = None
    short_strike_pe: Optional[float] = None
    long_strike_ce: Optional[float] = None
    long_strike_pe: Optional[float] = None
    atm_strike: Optional[float] = None

    # Metadata for the Telegram card
    reason: str = ""
    sub_scores: dict = field(default_factory=dict)

    # Raw values from microstructure for scoring
    spot: float = 0.0
    max_pain: float = 0.0
    pin_score: float = 0.0
    call_wall: float = 0.0
    put_wall: float = 0.0
    pcr: float = 0.0
    direction_score: int = 0
    expiry: str = ""
    step: int = 50
    dte: int = 0  # days to expiry at signal time


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _atm(spot: float, step: int) -> float:
    return float(round(round(spot / step) * step))


def _compute_pin_score(spot: float, max_pain: float, call_wall: float, put_wall: float) -> float:
    """Heuristic pin score: how strongly is spot pinned toward max pain.

    Returns a value in [0, 1].  1 means spot = max_pain, 0 means spot is at
    or beyond the walls.
    """
    half_range = (call_wall - put_wall) / 2.0 if call_wall > put_wall else 1.0
    if half_range <= 0:
        return 0.0
    distance_to_maxpain = abs(spot - max_pain)
    # Normalise: distance 0 → score 1; distance = half_range → score 0
    raw = 1.0 - min(distance_to_maxpain / half_range, 1.0)
    return round(raw, 4)


# ──────────────────────────────────────────────────────────────────────────────
# PB1: Directional Trend Continuation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_pb1(
    symbol: str,
    analysis: dict,
    regime: dict,
    step: int,
    or_high: Optional[float] = None,
    or_low: Optional[float] = None,
    vwap: Optional[float] = None,
) -> Optional[PlaybookSignal]:
    """PB1: Directional Trend Continuation.

    Requires:
      * Direction is BULL or BEAR (not NEUTRAL, not STRONG variants promoted OK).
      * Spot is beyond the Opening Range 15m (or_high for Bull, or_low for Bear).
        If OR levels are not provided, skip that gate but flag sub_score as partial.
      * VWAP alignment: spot > vwap for Bull, spot < vwap for Bear.
        If vwap is not provided, skip that gate but flag as partial.

    Generates ATM/1-OTM Call (Bull) or Put (Bear).
    """
    direction = regime.get("direction_label", "NEUTRAL")
    vol_regime = regime.get("vol_regime", "NORMAL_VOL")
    vol_provisional = bool(regime.get("vol_provisional", False))
    spot = float(analysis.get("spot", 0))
    expiry = analysis.get("expiry", "")
    call_wall = float(analysis.get("call_wall", spot + 500))
    put_wall = float(analysis.get("put_wall", spot - 500))
    max_pain = float(analysis.get("max_pain", spot))
    pcr = float(analysis.get("pcr_oi", 1.0))

    if direction not in ("BULL", "BEAR", "STRONG_BULL", "STRONG_BEAR"):
        return None

    # Normalise STRONG variants
    eff_dir = "BULL" if direction in ("BULL", "STRONG_BULL") else "BEAR"

    sub_scores: dict = {}
    gates_passed = 0

    # Gate 1: Opening Range break
    or_gate = False
    if eff_dir == "BULL":
        if or_high is not None:
            or_gate = spot > or_high
            sub_scores["or_break"] = 1 if or_gate else 0
        else:
            sub_scores["or_break"] = 0.5  # unavailable — partial credit
            or_gate = True  # allow through but penalise in score
    else:
        if or_low is not None:
            or_gate = spot < or_low
            sub_scores["or_break"] = 1 if or_gate else 0
        else:
            sub_scores["or_break"] = 0.5
            or_gate = True

    if not or_gate:
        logger.debug("PB1 %s: OR gate failed (spot=%.1f, or=%.1f/%.1f)", symbol, spot, or_high or 0, or_low or 0)
        return None
    gates_passed += 1

    # Gate 2: VWAP alignment
    vwap_gate = False
    if vwap is not None:
        vwap_gate = (spot > vwap) if eff_dir == "BULL" else (spot < vwap)
        sub_scores["vwap_alignment"] = 1 if vwap_gate else 0
    else:
        sub_scores["vwap_alignment"] = 0.5  # unavailable — partial credit
        vwap_gate = True

    if not vwap_gate:
        logger.debug("PB1 %s: VWAP gate failed (spot=%.1f, vwap=%.1f)", symbol, spot, vwap or 0)
        return None
    gates_passed += 1

    atm_strike = _atm(spot, step)
    # 1-OTM: one step away from ATM in the trade direction
    if eff_dir == "BULL":
        strike = atm_strike  # ATM call for bull
        instrument_type = "ATM_CALL"
    else:
        strike = atm_strike  # ATM put for bear
        instrument_type = "ATM_PUT"

    reason_parts = [f"PB1 {eff_dir} | spot={spot:.0f} | OR_break={sub_scores['or_break']} | VWAP={sub_scores['vwap_alignment']}"]
    reason = " | ".join(reason_parts)

    return PlaybookSignal(
        playbook_id="PB1",
        symbol=symbol,
        direction=eff_dir,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type=instrument_type,
        atm_strike=strike,
        short_strike_ce=strike if eff_dir == "BULL" else None,
        short_strike_pe=strike if eff_dir == "BEAR" else None,
        reason=reason,
        sub_scores=sub_scores,
        spot=spot,
        max_pain=max_pain,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        direction_score=regime.get("direction_score", 0),
        expiry=expiry,
        step=step,
    )


# ──────────────────────────────────────────────────────────────────────────────
# PB2: Mean Reversion / Max Pain Pinning
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_pb2(
    symbol: str,
    analysis: dict,
    regime: dict,
    step: int,
    min_pin_score: float = 0.50,
    max_distance_pts: float = 100.0,
) -> Optional[PlaybookSignal]:
    """PB2: Mean Reversion / Max Pain Pinning.

    Requires:
      * Direction regime is NEUTRAL.
      * |spot - max_pain| <= max_distance_pts (default 100 pts).
      * Pin Score >= min_pin_score (default 0.50).

    Generates Iron Butterfly / tight Iron Condor centered on Max Pain.
    """
    direction = regime.get("direction_label", "")
    if direction != "NEUTRAL":
        return None

    vol_regime = regime.get("vol_regime", "NORMAL_VOL")
    vol_provisional = bool(regime.get("vol_provisional", False))
    spot = float(analysis.get("spot", 0))
    max_pain = float(analysis.get("max_pain", spot))
    call_wall = float(analysis.get("call_wall", spot + 500))
    put_wall = float(analysis.get("put_wall", spot - 500))
    pcr = float(analysis.get("pcr_oi", 1.0))
    expiry = analysis.get("expiry", "")

    pin_score = _compute_pin_score(spot, max_pain, call_wall, put_wall)
    distance = abs(spot - max_pain)

    sub_scores = {
        "distance_to_maxpain": round(distance, 1),
        "pin_score": pin_score,
    }

    if distance > max_distance_pts:
        logger.debug("PB2 %s: distance gate failed (%.1f > %.1f)", symbol, distance, max_distance_pts)
        return None

    if pin_score < min_pin_score:
        logger.debug("PB2 %s: pin_score gate failed (%.3f < %.3f)", symbol, pin_score, min_pin_score)
        return None

    center = _atm(max_pain, step)
    short_ce = center + step
    short_pe = center - step
    long_ce = center + 3 * step
    long_pe = center - 3 * step

    reason = (
        f"PB2 NEUTRAL | max_pain={max_pain:.0f} | distance={distance:.0f}pts "
        f"| pin_score={pin_score:.2f}"
    )

    return PlaybookSignal(
        playbook_id="PB2",
        symbol=symbol,
        direction="NEUTRAL",
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type="IRON_BUTTERFLY",
        atm_strike=center,
        short_strike_ce=short_ce,
        short_strike_pe=short_pe,
        long_strike_ce=long_ce,
        long_strike_pe=long_pe,
        reason=reason,
        sub_scores=sub_scores,
        spot=spot,
        max_pain=max_pain,
        pin_score=pin_score,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        direction_score=regime.get("direction_score", 0),
        expiry=expiry,
        step=step,
    )


# ──────────────────────────────────────────────────────────────────────────────
# PB6: Steady-State 0DTE Theta Condor
# ──────────────────────────────────────────────────────────────────────────────

def _compute_dte(expiry: str, reference_date: Optional[date] = None) -> int:
    """Return days-to-expiry from reference_date (default: today) for an ISO-date expiry string."""
    try:
        exp = date.fromisoformat(expiry)
        ref = reference_date or date.today()
        return max(0, (exp - ref).days)
    except (ValueError, TypeError):
        return 999  # unparseable → treat as far-dated (no gate trigger)


_PB6_MAX_DTE = 7  # PB6 is short-dated only — 21-day monthly expiries are forbidden


def evaluate_pb6(
    symbol: str,
    analysis: dict,
    regime: dict,
    step: int,
    _reference_date: Optional[date] = None,
) -> Optional[PlaybookSignal]:
    """PB6: Steady-State Theta Condor (short-dated expiries ≤7 DTE only).

    Requires:
      * Expiry is ≤7 DTE (never traded against a 21-day monthly expiry).
      * Vol regime is NORMAL_VOL or LOW_VOL (not ELEVATED or HIGH — sellers' market
        but not when vol is stretched and condor wings blow out).
      * Spot is between the Call Wall and Put Wall (in the safe corridor).

    Generates standard Iron Condor: short strikes at walls, long wings 2 steps out.
    """
    vol_regime = regime.get("vol_regime", "NORMAL_VOL")
    vol_provisional = bool(regime.get("vol_provisional", False))

    if vol_regime not in ("NORMAL_VOL", "LOW_VOL"):
        logger.debug("PB6 %s: vol_regime=%s not eligible", symbol, vol_regime)
        return None

    spot = float(analysis.get("spot", 0))
    call_wall = float(analysis.get("call_wall", spot + 500))
    put_wall = float(analysis.get("put_wall", spot - 500))
    max_pain = float(analysis.get("max_pain", spot))
    pcr = float(analysis.get("pcr_oi", 1.0))
    expiry = analysis.get("expiry", "")

    # DTE gate: PB6 is restricted to short-dated expiries only.
    dte = _compute_dte(expiry, _reference_date)
    if dte > _PB6_MAX_DTE:
        logger.debug("PB6 %s: DTE=%d > %d — monthly expiry gate blocked", symbol, dte, _PB6_MAX_DTE)
        return None

    in_corridor = put_wall < spot < call_wall
    sub_scores = {
        "in_corridor": 1 if in_corridor else 0,
        "call_wall": call_wall,
        "put_wall": put_wall,
    }

    if not in_corridor:
        logger.debug("PB6 %s: spot=%.1f not between walls (%.1f, %.1f)", symbol, spot, put_wall, call_wall)
        return None

    # Short strikes at the walls, rounded to nearest step
    short_ce = _atm(call_wall, step)
    short_pe = _atm(put_wall, step)
    long_ce = short_ce + 2 * step
    long_pe = short_pe - 2 * step

    direction = regime.get("direction_label", "NEUTRAL")

    reason = (
        f"PB6 CONDOR | vol={vol_regime} | spot={spot:.0f} in corridor "
        f"[{put_wall:.0f}–{call_wall:.0f}] | DTE={dte}"
    )

    return PlaybookSignal(
        playbook_id="PB6",
        symbol=symbol,
        direction=direction,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type="IRON_CONDOR",
        short_strike_ce=short_ce,
        short_strike_pe=short_pe,
        long_strike_ce=long_ce,
        long_strike_pe=long_pe,
        reason=reason,
        sub_scores=sub_scores,
        spot=spot,
        max_pain=max_pain,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        direction_score=regime.get("direction_score", 0),
        expiry=expiry,
        step=step,
        dte=dte,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Composite evaluator
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_all_playbooks(
    symbol: str,
    analysis: dict,
    regime: dict,
    step: int,
    or_high: Optional[float] = None,
    or_low: Optional[float] = None,
    vwap: Optional[float] = None,
    _reference_date: Optional[date] = None,
) -> list[PlaybookSignal]:
    """Evaluate all three playbooks for the given symbol and return all that trigger.

    Returns a list (possibly empty) of PlaybookSignal objects.  The caller
    (scoring_engine / auto_trade_hunter) is responsible for ranking and filtering.
    """
    signals: list[PlaybookSignal] = []

    pb1 = evaluate_pb1(symbol, analysis, regime, step, or_high=or_high, or_low=or_low, vwap=vwap)
    if pb1 is not None:
        signals.append(pb1)

    pb2 = evaluate_pb2(symbol, analysis, regime, step)
    if pb2 is not None:
        signals.append(pb2)

    pb6 = evaluate_pb6(symbol, analysis, regime, step, _reference_date=_reference_date)
    if pb6 is not None:
        signals.append(pb6)

    return signals
