"""Playbook Trigger Evaluators — Phase 1C / Phase 2.

Implements institutional trigger logic for the four core production playbooks:
  PB1  Directional Trend Continuation
  PB2  Mean Reversion / Max Pain Pinning
  PB4  0DTE Expiry Gamma Blast  (Phase 2)
  PB6  Steady-State 0DTE Theta Condor

Each evaluator returns a PlaybookSignal (or None) carrying the playbook id,
the instrument specification, the reason text, and raw sub-scores that the
scoring engine uses to compute the composite confluence score.

All inputs come from the regime_engine result and the chain microstructure
analysis dict — no live network calls are made here.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")

# PB4: 0DTE Gamma Blast only fires after 13:00 IST on expiry day
_PB4_ENTRY_HOUR_IST = 13
# PB4: spot must be within this fraction of gamma_flip_level to count as "crossing"
_PB4_FLIP_PROXIMITY_PCT = 0.005   # 0.5% of spot
# PB4: minimum R:R ratio required
_PB4_MIN_RR = 2.5


@dataclass
class PlaybookSignal:
    """Output of a successful playbook trigger evaluation."""

    playbook_id: str        # "PB1", "PB2", "PB4", "PB6"
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

    # GEX zone fields (Phase 2 — populated by hunter before scoring)
    gex_zone: str = "UNKNOWN"                   # "POSITIVE", "NEGATIVE", "NEAR_FLIP", "UNKNOWN"
    gamma_flip_level: Optional[float] = None
    volume_accelerating: bool = False           # latest bar volume > prior bar volume


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
# PB4: 0DTE Expiry Gamma Blast
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_pb4_gamma_blast(
    symbol: str,
    analysis: dict,
    regime: dict,
    step: int,
    gex_data: dict,
    volume_accelerating: bool = False,
    current_time_ist: Optional[datetime.time] = None,
    _reference_date: Optional[date] = None,
) -> Optional[PlaybookSignal]:
    """PB4: 0DTE Expiry Gamma Blast — highest-expectancy expiry-day setup.

    Requires ALL of:
      * DTE == 0 (expiry day only).
      * Current IST time >= 13:00 (afternoon window; gamma / time decay at peak).
      * Negative GEX zone: total_net_gex < 0 (market makers amplify moves via
        delta hedging, creating self-reinforcing directional momentum).
      * Spot is crossing through / proximal to the gamma_flip_level (or a major
        strike wall if flip is unavailable) with volume acceleration.
      * Risk:Reward >= 1:2.5 (tight stop at flip, target at next strike wall).

    Contract selection:
      * ATM or 1-OTM option in the direction confirmed by regime direction_score.
      * BULL: ATM Call; BEAR: ATM Put.

    Returns None if any gate fails (fail-closed).
    """
    # Gate 1: expiry day only
    expiry = analysis.get("expiry", "")
    dte = _compute_dte(expiry, _reference_date)
    if dte != 0:
        logger.debug("PB4 %s: DTE=%d != 0 — not expiry day", symbol, dte)
        return None

    # Gate 2: time window (>= 13:00 IST)
    if current_time_ist is None:
        current_time_ist = datetime.datetime.now(tz=_IST).time()
    cutoff = datetime.time(_PB4_ENTRY_HOUR_IST, 0)
    if current_time_ist < cutoff:
        logger.debug("PB4 %s: time %s < 13:00 IST — too early", symbol, current_time_ist)
        return None

    # Gate 3: negative GEX zone
    total_net_gex = gex_data.get("total_net_gex", 0.0) or 0.0
    if total_net_gex >= 0:
        logger.debug("PB4 %s: total_net_gex=%.2f >= 0 — not negative GEX zone", symbol, total_net_gex)
        return None

    # Gate 4: spot proximal to gamma_flip_level or a major strike wall
    spot = float(analysis.get("spot", 0))
    gamma_flip = gex_data.get("gamma_flip_level")
    call_wall = float(analysis.get("call_wall", spot + 500))
    put_wall = float(analysis.get("put_wall", spot - 500))

    proximity_threshold = spot * _PB4_FLIP_PROXIMITY_PCT
    near_flip = (
        gamma_flip is not None
        and abs(spot - gamma_flip) <= proximity_threshold
    )
    near_wall = (
        abs(spot - call_wall) <= proximity_threshold
        or abs(spot - put_wall) <= proximity_threshold
    )

    if not near_flip and not near_wall:
        logger.debug(
            "PB4 %s: spot=%.1f not near flip=%.1f or walls (%.1f/%.1f)",
            symbol, spot, gamma_flip or 0, call_wall, put_wall,
        )
        return None

    # Gate 5: volume acceleration required
    if not volume_accelerating:
        logger.debug("PB4 %s: volume_accelerating=False — gate failed", symbol)
        return None

    # Direction from regime direction_score
    direction_score_val = int(regime.get("direction_score", 0))
    if direction_score_val > 0:
        eff_dir = "BULL"
    elif direction_score_val < 0:
        eff_dir = "BEAR"
    else:
        # Neutral regime on expiry day: use spot vs flip to determine direction
        if gamma_flip is not None:
            eff_dir = "BULL" if spot >= gamma_flip else "BEAR"
        else:
            logger.debug("PB4 %s: NEUTRAL regime + no flip — cannot determine direction", symbol)
            return None

    # Gate 6: R:R >= 1:2.5 (stop at flip, target at next strike wall)
    if gamma_flip is not None:
        stop_dist = abs(spot - gamma_flip)
    else:
        # Fall back to 0.5% of spot as proxy stop distance
        stop_dist = spot * 0.005

    target_dist = (call_wall - spot) if eff_dir == "BULL" else (spot - put_wall)

    if stop_dist <= 0:
        logger.debug("PB4 %s: zero stop distance — skipping", symbol)
        return None

    rr = target_dist / stop_dist
    if rr < _PB4_MIN_RR:
        logger.debug("PB4 %s: R:R=%.2f < %.1f — gate failed", symbol, rr, _PB4_MIN_RR)
        return None

    # Contract selection: ATM option in direction
    atm_strike = _atm(spot, step)
    instrument_type = "ATM_CALL" if eff_dir == "BULL" else "ATM_PUT"

    vol_regime = regime.get("vol_regime", "NORMAL_VOL")
    vol_provisional = bool(regime.get("vol_provisional", False))
    pcr = float(analysis.get("pcr_oi", 1.0))
    max_pain = float(analysis.get("max_pain", spot))

    # Determine GEX zone label
    if gamma_flip is not None and near_flip:
        gex_zone_label = "NEAR_FLIP"
    else:
        gex_zone_label = "NEGATIVE"

    reason = (
        f"PB4 0DTE_GAMMA_BLAST {eff_dir} | spot={spot:.0f} | flip={f'{gamma_flip:.0f}' if gamma_flip else 'N/A'} "
        f"| GEX={total_net_gex:.0f} | R:R={rr:.1f} | vol_acc={volume_accelerating}"
    )

    sub_scores = {
        "dte": dte,
        "total_net_gex": round(total_net_gex, 2),
        "rr": round(rr, 2),
        "near_flip": near_flip,
        "near_wall": near_wall,
        "volume_accelerating": volume_accelerating,
    }

    return PlaybookSignal(
        playbook_id="PB4",
        symbol=symbol,
        direction=eff_dir,
        vol_regime=vol_regime,
        vol_provisional=vol_provisional,
        instrument_type=instrument_type,
        atm_strike=atm_strike,
        short_strike_ce=atm_strike if eff_dir == "BULL" else None,
        short_strike_pe=atm_strike if eff_dir == "BEAR" else None,
        reason=reason,
        sub_scores=sub_scores,
        spot=spot,
        max_pain=max_pain,
        call_wall=call_wall,
        put_wall=put_wall,
        pcr=pcr,
        direction_score=direction_score_val,
        expiry=expiry,
        step=step,
        dte=dte,
        gex_zone=gex_zone_label,
        gamma_flip_level=gamma_flip,
        volume_accelerating=volume_accelerating,
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
    gex_data: Optional[dict] = None,
    volume_accelerating: bool = False,
    current_time_ist: Optional[datetime.time] = None,
) -> list[PlaybookSignal]:
    """Evaluate all playbooks for the given symbol and return all that trigger.

    Phase 2 additions:
      gex_data: result of gex_engine.compute_gex — used to populate gex_zone on
                all signals and to gate PB4.
      volume_accelerating: True when latest 15m bar volume > prior bar.
      current_time_ist: inject IST time for PB4 time-window gate (default: now).

    Returns a list (possibly empty) of PlaybookSignal objects.  The caller
    (scoring_engine / auto_trade_hunter) is responsible for ranking and filtering.
    """
    signals: list[PlaybookSignal] = []

    # Compute GEX zone label once and attach to all signals
    spot = float(analysis.get("spot", 0))
    gex_zone_label = "UNKNOWN"
    gamma_flip = None
    if gex_data:
        gamma_flip = gex_data.get("gamma_flip_level")
        total_net_gex = gex_data.get("total_net_gex", 0.0) or 0.0
        if gamma_flip is not None and spot > 0:
            flip_pct_dist = abs(spot - gamma_flip) / spot
            if flip_pct_dist <= 0.0025:   # within 0.25% of flip
                gex_zone_label = "NEAR_FLIP"
            elif spot > gamma_flip:
                gex_zone_label = "POSITIVE"
            else:
                gex_zone_label = "NEGATIVE"
        elif total_net_gex > 0:
            gex_zone_label = "POSITIVE"
        elif total_net_gex < 0:
            gex_zone_label = "NEGATIVE"

    def _attach_gex(sig: PlaybookSignal) -> PlaybookSignal:
        if sig is not None:
            sig.gex_zone = gex_zone_label
            sig.gamma_flip_level = gamma_flip
            sig.volume_accelerating = volume_accelerating
        return sig

    pb1 = evaluate_pb1(symbol, analysis, regime, step, or_high=or_high, or_low=or_low, vwap=vwap)
    if pb1 is not None:
        signals.append(_attach_gex(pb1))

    pb2 = evaluate_pb2(symbol, analysis, regime, step)
    if pb2 is not None:
        signals.append(_attach_gex(pb2))

    pb4 = None
    if gex_data:
        pb4 = evaluate_pb4_gamma_blast(
            symbol, analysis, regime, step,
            gex_data=gex_data,
            volume_accelerating=volume_accelerating,
            current_time_ist=current_time_ist,
            _reference_date=_reference_date,
        )
    if pb4 is not None:
        signals.append(pb4)  # already has gex_zone set

    pb6 = evaluate_pb6(symbol, analysis, regime, step, _reference_date=_reference_date)
    if pb6 is not None:
        signals.append(_attach_gex(pb6))

    return signals
