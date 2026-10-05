"""Black-76 implied volatility solver (bisection method).

Black-76 prices options on a forward price F:
  Call = e^(-r*T) * [F*N(d1) - K*N(d2)]
  Put  = e^(-r*T) * [K*N(-d2) - F*N(-d1)]
  d1 = (ln(F/K) + 0.5*sigma^2*T) / (sigma*sqrt(T))
  d2 = d1 - sigma*sqrt(T)

Session annualization: T = get_dte_minutes() / (375 * 252)
"""

import math
from typing import Optional


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_price(
    option_type: str,
    forward: float,
    strike: float,
    tte_years: float,
    rate: float,
    sigma: float,
) -> float:
    """Black-76 analytical option price.

    Raises ValueError on invalid inputs so callers can distinguish bad data
    from a valid near-zero price.
    """
    if forward <= 0:
        raise ValueError(f"forward must be > 0, got {forward}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if tte_years <= 0:
        raise ValueError(f"tte_years must be > 0, got {tte_years}")
    if sigma <= 0:
        raise ValueError(f"sigma must be > 0, got {sigma}")
    if option_type not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, got {option_type!r}")

    sqrt_t = math.sqrt(tte_years)
    d1 = (math.log(forward / strike) + 0.5 * sigma ** 2 * tte_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc = math.exp(-rate * tte_years)

    if option_type == "CE":
        return disc * (forward * _norm_cdf(d1) - strike * _norm_cdf(d2))
    else:
        return disc * (strike * _norm_cdf(-d2) - forward * _norm_cdf(-d1))


def solve_iv(
    option_type: str,
    forward: float,
    strike: float,
    tte_years: float,
    rate: float,
    market_price: float,
) -> Optional[float]:
    """Bisection IV solver.  Returns None (not 0) if unsolvable.

    Returns None when:
      - market_price is 0 or None
      - bisection fails to converge within bounds
      - intrinsic-only pricing (no vol content)

    Raises ValueError on structurally invalid inputs (negative price,
    non-positive forward/strike/tte).
    """
    if market_price is None:
        return None
    if market_price < 0:
        raise ValueError(f"market_price must be >= 0, got {market_price}")
    if market_price == 0:
        return None
    if forward <= 0:
        raise ValueError(f"forward must be > 0, got {forward}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if tte_years <= 0:
        raise ValueError(f"tte_years must be > 0, got {tte_years}")
    if option_type not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, got {option_type!r}")

    lo, hi = 1e-6, 20.0          # 0.0001 % to 2000 % IV
    tol = 1e-7
    max_iter = 200

    def f(sigma: float) -> float:
        try:
            return black76_price(option_type, forward, strike, tte_years, rate, sigma) - market_price
        except (ValueError, OverflowError, ZeroDivisionError):
            return float("inf")

    f_lo = f(lo)
    f_hi = f(hi)

    if f_lo * f_hi > 0:
        return None  # root not bracketed — unsolvable

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        if (hi - lo) / 2.0 < tol:
            return mid
        f_mid = f(mid)
        if f_mid == 0:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    return (lo + hi) / 2.0  # best estimate after max iterations
