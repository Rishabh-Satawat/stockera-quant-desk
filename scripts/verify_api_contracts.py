#!/usr/bin/env python3
"""
verify_api_contracts.py — Dhan HQ v2 API contract verification script.

Requires env vars (or .env file):
  DHAN_CLIENT_ID
  DHAN_ACCESS_TOKEN

Checks:
  1. One raw strike dict from /v2/optionchain showing security_id,
     implied_volatility, and greeks field names.
  2. Null/zero rate of implied_volatility across near-the-money strikes
     (confirms P0.3 zero-IV trap is real).
  3. That expirylist returns dates in ascending order.

Run:
  cd stockera-quant-desk
  DHAN_CLIENT_ID=xxx DHAN_ACCESS_TOKEN=yyy python scripts/verify_api_contracts.py
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

# Load from project secrets directory first, then CWD .env
for env_path in [
    r"C:\kite-agent\secrets\dhan.env",
    os.path.join(os.path.dirname(__file__), "..", "secrets", "dhan.env"),
    ".env",
]:
    if os.path.exists(env_path):
        load_dotenv(env_path)

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

SCRIP_MAP = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51}
NTM_WINDOW = 5  # strikes either side of ATM to check for IV nulls

BASE_URL = "https://api.dhan.co/v2"


def headers():
    return {
        "access-token": DHAN_ACCESS_TOKEN,
        "client-id": DHAN_CLIENT_ID,
        "Content-Type": "application/json",
    }


def abort(msg):
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def verify_expiry_list(symbol="NIFTY"):
    print(f"\n{'='*60}")
    print(f"CHECK 3 — expirylist order for {symbol}")
    print(f"{'='*60}")
    scrip_id = SCRIP_MAP[symbol]
    r = requests.post(
        f"{BASE_URL}/optionchain/expirylist",
        headers=headers(),
        json={"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"},
        timeout=6,
    )
    if r.status_code != 200:
        abort(f"expirylist returned {r.status_code}: {r.text[:200]}")

    exp_list = r.json().get("data", [])
    print(f"  Raw expirylist ({len(exp_list)} entries): {exp_list[:6]} ...")

    if len(exp_list) < 2:
        print("  WARNING: fewer than 2 expiries returned — cannot verify ordering.")
        return exp_list

    sorted_list = sorted(exp_list)
    if exp_list != sorted_list:
        print(f"  [FAIL] expirylist is NOT in ascending order!")
        print(f"    Got:      {exp_list[:6]}")
        print(f"    Expected: {sorted_list[:6]}")
    else:
        print(f"  [PASS] expirylist is in ascending order.")

    return exp_list


def verify_option_chain(symbol="NIFTY", expiry=None):
    scrip_id = SCRIP_MAP[symbol]
    payload = {"UnderlyingScrip": scrip_id, "UnderlyingSeg": "IDX_I"}
    if expiry:
        payload["Expiry"] = expiry

    print(f"\n{'='*60}")
    print(f"CHECK 1 — raw strike dict field names for {symbol} expiry={expiry}")
    print(f"{'='*60}")

    r = requests.post(
        f"{BASE_URL}/optionchain",
        headers=headers(),
        json=payload,
        timeout=8,
    )
    if r.status_code != 200:
        abort(f"optionchain returned {r.status_code}: {r.text[:200]}")

    data = r.json().get("data", {})
    last_price = data.get("last_price", 0.0)
    oc = data.get("oc", {})

    if not oc:
        abort("Empty oc dict returned from optionchain.")

    spot = float(last_price) if last_price else 0.0
    step = 100 if symbol in ("SENSEX", "BANKNIFTY") else 50
    atm = int(round(spot / step) * step) if spot > 0 else int(list(oc.keys())[len(oc) // 2])

    # Find a strike close to ATM to show as sample
    sample_key = None
    sample_val = None
    for k, v in oc.items():
        try:
            if abs(float(k) - atm) < step * 2:
                sample_key = k
                sample_val = v
                break
        except Exception:
            pass

    if sample_val is None:
        sample_key, sample_val = next(iter(oc.items()))

    print(f"\n  Underlying spot (last_price): {last_price}")
    print(f"  ATM estimate: {atm}")
    print(f"\n  Sample strike key: {sample_key}")
    print(f"\n  CE fields:")
    ce = sample_val.get("ce", {})
    for fld in ["security_id", "implied_volatility", "greeks", "last_price", "oi", "volume"]:
        print(f"    {fld}: {ce.get(fld, '<MISSING>')}")

    print(f"\n  PE fields:")
    pe = sample_val.get("pe", {})
    for fld in ["security_id", "implied_volatility", "greeks", "last_price", "oi", "volume"]:
        print(f"    {fld}: {pe.get(fld, '<MISSING>')}")

    # Security ID validation
    ce_sec = ce.get("security_id")
    pe_sec = pe.get("security_id")
    print(f"\n  security_id CE={ce_sec!r}  PE={pe_sec!r}")
    if ce_sec is None or pe_sec is None:
        print("  [WARN] security_id is None for at least one leg.")
    else:
        try:
            int(ce_sec)
            int(pe_sec)
            print("  [PASS] security_id values are numeric.")
        except (TypeError, ValueError):
            print(f"  [FAIL] security_id is not numeric: CE={ce_sec!r} PE={pe_sec!r}")

    # IV trap check (CHECK 2)
    print(f"\n{'='*60}")
    print(f"CHECK 2 — IV null/zero rate for {symbol} near-ATM (±{NTM_WINDOW} strikes)")
    print(f"{'='*60}")

    strikes_sorted = sorted([float(k) for k in oc.keys()])
    atm_idx = min(range(len(strikes_sorted)), key=lambda i: abs(strikes_sorted[i] - atm))
    lo = max(0, atm_idx - NTM_WINDOW)
    hi = min(len(strikes_sorted), atm_idx + NTM_WINDOW + 1)
    ntm_strikes = strikes_sorted[lo:hi]

    total_legs = 0
    null_zero_legs = 0
    for k_float in ntm_strikes:
        k_str = None
        for raw_k in oc.keys():
            try:
                if abs(float(raw_k) - k_float) < 0.5:
                    k_str = raw_k
                    break
            except Exception:
                pass
        if k_str is None:
            continue
        v = oc[k_str]
        for side in ("ce", "pe"):
            iv = v.get(side, {}).get("implied_volatility")
            total_legs += 1
            if iv is None or iv == 0 or iv == 0.0:
                null_zero_legs += 1
                print(f"  ZERO/NULL IV: strike={k_float} {side.upper()} iv={iv!r}")

    if total_legs > 0:
        null_rate = null_zero_legs / total_legs * 100
        print(f"\n  Near-ATM legs checked  : {total_legs}")
        print(f"  Zero/null IV count     : {null_zero_legs}")
        print(f"  Zero/null IV rate      : {null_rate:.1f}%")
        if null_rate > 0:
            print(f"  [CONFIRMED] Zero-IV trap exists — P0.3 guard is necessary.")
        else:
            print(f"  [INFO] No zero-IV strikes in NTM window this run (may vary by time/liquidity).")
    else:
        print("  [WARN] No near-ATM strikes found in oc dict.")

    return oc


def main():
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        print(
            "\n[ERROR] DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN not set.\n"
            "Set them as environment variables or in secrets/dhan.env and re-run:\n"
            "  DHAN_CLIENT_ID=xxx DHAN_ACCESS_TOKEN=yyy python scripts/verify_api_contracts.py\n"
        )
        sys.exit(1)

    print("=" * 60)
    print("STOCKERA API CONTRACT VERIFICATION")
    print("=" * 60)

    for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]:
        print(f"\n\n{'#'*60}")
        print(f"  SYMBOL: {sym}")
        print(f"{'#'*60}")

        exp_list = verify_expiry_list(sym)
        first_expiry = exp_list[0] if exp_list else None
        verify_option_chain(sym, first_expiry)

    print(f"\n{'='*60}")
    print("VERIFICATION COMPLETE")
    print("="*60)


if __name__ == "__main__":
    main()
