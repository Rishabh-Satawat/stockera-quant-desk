"""Composite Confluence Scoring Engine — Phase 1C / Phase 1D.

Scores every evaluated PlaybookSignal 0–100 using 5 weighted pillars:

  Pillar 1  Regime & Structure Alignment          30 pts
  Pillar 2  PCR & Strike Concentration            25 pts
             (TODO Phase 3: attach aggressor CVD delta-flow here)
  Pillar 3  Volatility & Expected Move            20 pts
  Pillar 4  Risk:Reward Metric                    15 pts
  Pillar 5  Data Quality & Freshness              10 pts

Gating rules:
  ≥ 80  Tier 1 — emit alert / dispatch trade
  60–79 Tier 2 — watchlist, log only
  < 60  Dropped

Anti-Correlation Filter:
  If NIFTY and SENSEX both produce identical directional signals,
  select only the highest-scoring candidate to prevent duplicate risk.

When vol_provisional=True (cold-start) the composite score is reduced by 10%
(capped at max 100) before gating, reflecting the missing IV history.
"""

from __future__ import annotations

import logging
from typing import Optional

from playbook_triggers import PlaybookSignal

logger = logging.getLogger(__name__)

TIER1_THRESHOLD = 80
TIER2_THRESHOLD = 60


# ──────────────────────────────────────────────────────────────────────────────
# Pillar scorers
# ──────────────────────────────────────────────────────────────────────────────

def _score_regime_structure(signal: PlaybookSignal) -> float:
    """Pillar 1: Regime & Structure Alignment — max 30 pts.

    Full 30 if playbook perfectly matches 2-axis regime + direction alignment.
    Partial deductions for weaker direction scores.
    """
    pts = 0.0

    # 1a. Playbook matches vol regime (15 pts)
    vol = signal.vol_regime
    pb = signal.playbook_id

    pb1_vols = ("NORMAL_VOL", "ELEVATED_VOL", "HIGH_VOL", "LOW_VOL")
    pb2_vols = ("NORMAL_VOL", "LOW_VOL")
    pb6_vols = ("NORMAL_VOL", "LOW_VOL")

    if pb == "PB1" and vol in pb1_vols:
        pts += 15.0
    elif pb == "PB2" and vol in pb2_vols:
        pts += 15.0
    elif pb == "PB6" and vol in pb6_vols:
        pts += 15.0
    else:
        pts += 7.0  # partial — playbook can still fire but regime is suboptimal

    # 1b. Direction score magnitude (15 pts)
    # Stronger conviction (|score| ≥ 5) = full; moderate (2–4) = partial; weak/neutral = low.
    d = abs(signal.direction_score)
    if d >= 5:
        pts += 15.0
    elif d >= 3:
        pts += 10.0
    elif d >= 2:
        pts += 7.0
    elif d >= 1:
        pts += 4.0
    else:
        pts += 0.0  # NEUTRAL direction — no directional conviction pts

    return min(pts, 30.0)


def _score_microstructure(signal: PlaybookSignal) -> float:
    """Pillar 2: PCR & Strike Concentration — max 25 pts.

    PCR direction confirmation and spot position within the call/put-wall corridor.
    TODO Phase 3: extend with aggressor CVD delta-flow signal when order_flow_cvd_engine
    provides a tick-level net delta delta feed.
    """
    pts = 0.0
    pcr = signal.pcr
    direction = signal.direction
    spot = signal.spot
    call_wall = signal.call_wall
    put_wall = signal.put_wall

    # 2a. PCR confirms direction (12 pts)
    if direction == "BULL" and pcr > 1.0:
        pts += 12.0  # put writing support → bullish
    elif direction == "BULL" and pcr > 0.85:
        pts += 6.0   # moderate support
    elif direction == "BEAR" and pcr < 1.0:
        pts += 12.0  # call-heavy → bearish
    elif direction == "BEAR" and pcr < 1.15:
        pts += 6.0
    elif direction == "NEUTRAL" and 0.85 <= pcr <= 1.15:
        pts += 12.0  # balanced PCR → range-bound confirmed
    else:
        pts += 0.0

    # 2b. Spot position within walls (13 pts)
    wall_range = call_wall - put_wall
    if wall_range > 0:
        relative = (spot - put_wall) / wall_range  # 0 = at put wall, 1 = at call wall
        # Condor / range: centred spot is best (relative ≈ 0.5 = full pts)
        # Directional: spot near the break side is better
        if signal.playbook_id in ("PB2", "PB6"):
            centre_dist = abs(relative - 0.5)
            pts += max(0.0, 13.0 * (1.0 - 2.0 * centre_dist))
        else:  # PB1
            if direction == "BULL" and relative > 0.5:
                pts += 13.0
            elif direction == "BULL" and relative > 0.3:
                pts += 7.0
            elif direction == "BEAR" and relative < 0.5:
                pts += 13.0
            elif direction == "BEAR" and relative < 0.7:
                pts += 7.0
            else:
                pts += 3.0

    return min(pts, 25.0)


def _score_volatility_em(signal: PlaybookSignal) -> float:
    """Pillar 3: Volatility & Expected Move — max 20 pts.

    Vol regime suitability for the playbook's risk profile.
    Provisional vol (cold-start) halves this pillar.
    """
    pts = 0.0
    vol = signal.vol_regime
    pb = signal.playbook_id

    if pb == "PB1":
        # Buyers want moderate vol for pricing; low vol = cheap premiums (good); high = expensive
        if vol == "NORMAL_VOL":
            pts = 20.0
        elif vol == "ELEVATED_VOL":
            pts = 14.0
        elif vol == "HIGH_VOL":
            pts = 8.0
        else:  # LOW_VOL — cheap but delta moves are small
            pts = 16.0

    elif pb in ("PB2", "PB6"):
        # Sellers want lower vol; premium rich but manageable
        if vol == "NORMAL_VOL":
            pts = 20.0
        elif vol == "LOW_VOL":
            pts = 18.0
        elif vol == "ELEVATED_VOL":
            pts = 8.0
        else:  # HIGH_VOL — wings explode
            pts = 4.0

    # Cold-start provisional: halve this pillar since IVR/IVP unknown
    if signal.vol_provisional:
        pts *= 0.5

    return min(pts, 20.0)


def _score_risk_reward(signal: PlaybookSignal) -> float:
    """Pillar 4: Risk:Reward Metric — max 15 pts.

    PB1 (debit/naked): score based on implied R:R from strike placement.
    PB2/PB6 (credit/hedged): score based on PoP proxy from width vs distance.
    """
    pts = 0.0
    pb = signal.playbook_id
    spot = signal.spot
    step = signal.step

    if pb == "PB1":
        # Naked/debit: ATM option. Assume 1:1.5 R:R as baseline = 15 pts;
        # weaker conviction gets partial.
        d = abs(signal.direction_score)
        if d >= 4:
            pts = 15.0
        elif d >= 2:
            pts = 10.0
        else:
            pts = 5.0

    elif pb in ("PB2", "PB6"):
        # Credit spread: PoP proxy = distance from spot to short strike / wing width
        short_ce = signal.short_strike_ce or (spot + 2 * step)
        short_pe = signal.short_strike_pe or (spot - 2 * step)
        long_ce = signal.long_strike_ce or (short_ce + 2 * step)
        long_pe = signal.long_strike_pe or (short_pe - 2 * step)

        wing_width = (long_ce - short_ce + short_pe - long_pe) / 2.0
        if wing_width > 0:
            dist_call = short_ce - spot
            dist_put = spot - short_pe
            min_dist = min(dist_call, dist_put)
            # PoP proxy: min_dist / (min_dist + wing_width)
            pop = min_dist / (min_dist + wing_width) if (min_dist + wing_width) > 0 else 0
            if pop >= 0.70:
                pts = 15.0
            elif pop >= 0.55:
                pts = 10.0
            elif pop >= 0.40:
                pts = 6.0
            else:
                pts = 2.0

    return min(pts, 15.0)


def _score_data_quality(signal: PlaybookSignal, data_age_seconds: float = 0.0) -> float:
    """Pillar 5: Data Quality & Freshness — max 10 pts.

    Full 10 if data is live (≤ 30s old).
    0 if provisional (vol cold-start or data is stale).
    """
    if data_age_seconds > 30.0:
        return 0.0
    if signal.vol_provisional:
        return 5.0  # partial — data is live but vol history is cold
    return 10.0


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def score_candidate(
    signal: PlaybookSignal,
    data_age_seconds: float = 0.0,
) -> dict:
    """Compute composite confluence score for a PlaybookSignal.

    Returns:
        {
            "score": int,          # 0–100, after vol_provisional -10% reduction
            "raw_score": float,    # before reduction
            "tier": int,           # 1 (≥80), 2 (60–79), 0 (dropped)
            "breakdown": dict,     # per-pillar raw points
        }
    """
    p1 = _score_regime_structure(signal)
    p2 = _score_microstructure(signal)
    p3 = _score_volatility_em(signal)
    p4 = _score_risk_reward(signal)
    p5 = _score_data_quality(signal, data_age_seconds)

    raw = p1 + p2 + p3 + p4 + p5  # max 100

    # Cold-start penalty: 10% reduction when vol is provisional
    final = raw * 0.90 if signal.vol_provisional else raw
    final = min(final, 100.0)

    score_int = int(round(final))

    if score_int >= TIER1_THRESHOLD:
        tier = 1
    elif score_int >= TIER2_THRESHOLD:
        tier = 2
    else:
        tier = 0

    breakdown = {
        "regime_structure": round(p1, 1),
        "microstructure": round(p2, 1),
        "volatility_em": round(p3, 1),
        "risk_reward": round(p4, 1),
        "data_quality": round(p5, 1),
    }

    return {
        "score": score_int,
        "raw_score": round(raw, 2),
        "tier": tier,
        "breakdown": breakdown,
    }


def rank_and_filter(
    candidates: list[tuple[PlaybookSignal, dict]],
) -> list[tuple[PlaybookSignal, dict]]:
    """Apply anti-correlation filter and return sorted list.

    Anti-Correlation Filter: if NIFTY and SENSEX both produce identical
    directional signals, select only the highest-scoring one to prevent
    duplicate risk.

    Input: list of (signal, score_result) tuples.
    Returns: filtered + sorted by score descending.
    """
    # Sort descending by score
    sorted_candidates = sorted(candidates, key=lambda x: x[1]["score"], reverse=True)

    # Anti-correlation filter: prevent doubled sector risk by deduplicating
    # same-direction signals within each correlated group.
    #
    # Group A: NIFTY ↔ SENSEX  (broad-market indices — near-identical composition)
    # Group B: NIFTY ↔ BANKNIFTY  (banking sector drives ~35% of NIFTY weight)
    #
    # Within each group, if two PB1 directional signals share the same direction,
    # only the highest-scoring one is kept.
    _CORR_GROUPS = [
        frozenset(("NIFTY", "SENSEX")),
        frozenset(("NIFTY", "BANKNIFTY")),
    ]

    # Map each (group_index, direction) → the best-scoring (sig, score_result) so far
    seen: dict[tuple[int, str], tuple[PlaybookSignal, dict]] = {}
    # Track which symbols we already emitted, so we don't double-count NIFTY
    # if it wins both group A and group B competitions.
    filtered: list[tuple[PlaybookSignal, dict]] = []
    dropped_ids: set[int] = set()

    for sig, score_result in sorted_candidates:
        if id(sig) in dropped_ids:
            continue
        if sig.playbook_id == "PB1":
            for grp_idx, grp in enumerate(_CORR_GROUPS):
                if sig.symbol in grp:
                    key = (grp_idx, sig.direction)
                    if key in seen:
                        prev_sig, prev_sr = seen[key]
                        if score_result["score"] >= prev_sr["score"]:
                            # Current signal is better — drop the previously-added one
                            dropped_ids.add(id(prev_sig))
                            filtered = [(s, sr) for s, sr in filtered if id(s) != id(prev_sig)]
                            seen[key] = (sig, score_result)
                            logger.info(
                                "anti_correlation_filter: grp=%d dropping %s %s (score=%d) "
                                "— %s score=%d is higher",
                                grp_idx, prev_sig.symbol, prev_sig.direction, prev_sr["score"],
                                sig.symbol, score_result["score"],
                            )
                        else:
                            # Current signal is worse — drop it
                            dropped_ids.add(id(sig))
                            logger.info(
                                "anti_correlation_filter: grp=%d dropping %s %s (score=%d) "
                                "— %s already selected (score=%d)",
                                grp_idx, sig.symbol, sig.direction, score_result["score"],
                                prev_sig.symbol, prev_sr["score"],
                            )
                            break
                    else:
                        seen[key] = (sig, score_result)

        if id(sig) not in dropped_ids:
            filtered.append((sig, score_result))

    return filtered


def format_confluence_breakdown(signal: PlaybookSignal, score_result: dict) -> str:
    """Format a human-readable confluence breakdown for the Telegram card."""
    b = score_result["breakdown"]
    lines = [
        f"📊 *Confluence Score: {score_result['score']}/100* (Tier {score_result['tier']})",
        f"  • Regime & Structure:    {b['regime_structure']:.0f}/30",
        f"  • PCR & Strike Conc.:    {b['microstructure']:.0f}/25",
        f"  • Volatility / EM:       {b['volatility_em']:.0f}/20",
        f"  • Risk:Reward:           {b['risk_reward']:.0f}/15",
        f"  • Data Quality:          {b['data_quality']:.0f}/10",
    ]
    if signal.vol_provisional:
        lines.append("  ⚠️ _vol_provisional=True — score reduced 10% (cold-start)_")
    return "\n".join(lines)
