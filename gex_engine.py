"""GEX Engine — Phase 1B.

Reads from chain_snapshots (latest snapshot per strike, today only, 90s
staleness gate) via get_latest_chain_snapshot from chain_snapshotter.

Computes:
  - Net GEX per strike (dealer net gamma exposure)
  - Total Net GEX
  - Gamma Flip Level
  - Max Pain
  - Pin Score
"""

import math
import logging
from typing import Optional

from db_init import DEFAULT_DB_PATH
from chain_snapshotter import get_latest_chain_snapshot

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Per-strike GEX
# ──────────────────────────────────────────────────────────────────────────────

def _gex_strike(gamma: float, oi: int, lot_size: int, spot: float) -> float:
    """GEX for one side: gamma * oi * lot_size * (spot/100)^2."""
    return gamma * oi * lot_size * (spot / 100.0) ** 2


def compute_per_strike_gex(oc: dict, lot_size: int, spot: float) -> list[dict]:
    """Compute net GEX per strike from option chain dict.

    Args:
        oc: {strike_str: {"ce": {...}, "pe": {...}}} from get_latest_chain_snapshot
        lot_size: contract lot size
        spot: underlying spot price

    Returns:
        List of dicts sorted by strike: {strike, call_gex, put_gex, net_gex}
        call_gex is positive (dealer long gamma), put_gex is negative.
    """
    result = []
    for strike_str, sides in oc.items():
        try:
            strike = float(strike_str)
        except (ValueError, TypeError):
            continue

        call_gex = 0.0
        put_gex = 0.0

        ce = sides.get("ce") or {}
        pe = sides.get("pe") or {}

        ce_greeks = ce.get("greeks") or {}
        pe_greeks = pe.get("greeks") or {}

        ce_gamma = ce_greeks.get("gamma")
        ce_oi = ce.get("oi", 0) or 0
        if ce_gamma is not None and ce_gamma > 0 and ce_oi > 0:
            call_gex = _gex_strike(ce_gamma, ce_oi, lot_size, spot)

        pe_gamma = pe_greeks.get("gamma")
        pe_oi = pe.get("oi", 0) or 0
        if pe_gamma is not None and pe_gamma > 0 and pe_oi > 0:
            # Puts: dealer is short gamma, so negative contribution
            put_gex = -_gex_strike(pe_gamma, pe_oi, lot_size, spot)

        net_gex = call_gex + put_gex
        result.append({
            "strike": strike,
            "call_gex": call_gex,
            "put_gex": put_gex,
            "net_gex": net_gex,
        })

    return sorted(result, key=lambda x: x["strike"])


# ──────────────────────────────────────────────────────────────────────────────
# Gamma Flip Level
# ──────────────────────────────────────────────────────────────────────────────

def find_gamma_flip(per_strike: list[dict]) -> Optional[float]:
    """Strike where cumulative net GEX (from low to high) transitions negative→positive.

    Returns the first strike where the cumulative sum crosses from negative to positive.
    Returns None if no flip exists.
    """
    if not per_strike:
        return None

    cumulative = 0.0
    prev_cumulative = None
    for row in per_strike:
        prev_cumulative = cumulative
        cumulative += row["net_gex"]
        if prev_cumulative is not None and prev_cumulative < 0 and cumulative >= 0:
            return row["strike"]

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Max Pain
# ──────────────────────────────────────────────────────────────────────────────

def compute_max_pain(oc: dict) -> Optional[float]:
    """Standard max pain: strike minimizing total option writer pain.

    For each candidate strike K:
      pain = sum over all strikes S of:
        call pain: max(0, S - K) * call_oi_at_S
        put pain:  max(0, K - S) * put_oi_at_S

    Returns the strike K with minimum total pain.
    """
    strikes_data = []
    for strike_str, sides in oc.items():
        try:
            strike = float(strike_str)
        except (ValueError, TypeError):
            continue
        ce = sides.get("ce") or {}
        pe = sides.get("pe") or {}
        call_oi = ce.get("oi", 0) or 0
        put_oi = pe.get("oi", 0) or 0
        strikes_data.append((strike, call_oi, put_oi))

    if not strikes_data:
        return None

    strikes_data.sort(key=lambda x: x[0])
    all_strikes = [s[0] for s in strikes_data]

    min_pain = float("inf")
    max_pain_strike = None

    for k_strike in all_strikes:
        pain = 0.0
        for s, call_oi, put_oi in strikes_data:
            # Call writer pain at candidate strike K: calls expire worthless below K
            pain += max(0.0, s - k_strike) * call_oi
            # Put writer pain at candidate strike K: puts expire worthless above K
            pain += max(0.0, k_strike - s) * put_oi
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = k_strike

    return max_pain_strike


# ──────────────────────────────────────────────────────────────────────────────
# Pin Score
# ──────────────────────────────────────────────────────────────────────────────

def compute_pin_score(spot: float, max_pain: Optional[float]) -> float:
    """Pin Score 0–100 based on distance from spot to max pain.

    pin_score = 100 * exp(-|spot - max_pain| / (spot * 0.005))
    Returns 0 if max_pain is None.
    """
    if max_pain is None:
        return 0.0
    distance = abs(spot - max_pain)
    pin_unit = spot * 0.005  # 0.5% of spot
    if pin_unit <= 0:
        return 0.0
    return 100.0 * math.exp(-distance / pin_unit)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def compute_gex(
    symbol: str,
    expiry: str,
    spot: float,
    lot_size: int,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    """Compute GEX metrics for symbol+expiry at given spot.

    Returns dict with keys:
      total_net_gex, gamma_flip_level, max_pain, pin_score, per_strike_gex
    Uses get_latest_chain_snapshot (90s staleness gate, today only).
    Returns zeros/None on missing or stale data (fail-closed).
    """
    snap = get_latest_chain_snapshot(symbol, db_path)
    if not snap:
        logger.warning("compute_gex: no fresh snapshot for %s — returning zeros", symbol)
        return {
            "total_net_gex": 0.0,
            "gamma_flip_level": None,
            "max_pain": None,
            "pin_score": 0.0,
            "per_strike_gex": [],
        }

    oc = snap.get("oc", {})
    per_strike = compute_per_strike_gex(oc, lot_size, spot)
    total_net_gex = sum(r["net_gex"] for r in per_strike)
    gamma_flip = find_gamma_flip(per_strike)
    max_pain_val = compute_max_pain(oc)
    pin_score = compute_pin_score(spot, max_pain_val)

    return {
        "total_net_gex": total_net_gex,
        "gamma_flip_level": gamma_flip,
        "max_pain": max_pain_val,
        "pin_score": pin_score,
        "per_strike_gex": per_strike,
    }
