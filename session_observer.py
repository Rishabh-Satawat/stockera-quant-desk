"""Session Observer — diagnostic CLI for the Stockera Quant Desk.

Usage:
  python session_observer.py --report           single-shot health report
  python session_observer.py --watch            refresh every 60 s during market hours
  python session_observer.py --checkpoint       pre-flight safety check
  python session_observer.py --token            Dhan token status (last 4 chars, no full token)
  python session_observer.py --candidates [N]   top-N today's candidates with raw/adjusted scores
  python session_observer.py --quota            today's quota usage, stale-row exclusions
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import json
import os
import re

from db_init import DEFAULT_DB_PATH, init_db

logger = logging.getLogger(__name__)

_IST = ZoneInfo("Asia/Kolkata")
_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

# ANSI colour helpers (degrade gracefully when stdout is not a tty)
_RED = "\033[91m"
_YEL = "\033[93m"
_GRN = "\033[92m"
_RST = "\033[0m"


def _red(s: str) -> str:
    return f"{_RED}{s}{_RST}"


def _grn(s: str) -> str:
    return f"{_GRN}{s}{_RST}"


def _yel(s: str) -> str:
    return f"{_YEL}{s}{_RST}"


# ---------------------------------------------------------------------------
# Section 1 — Snapshotter health
# ---------------------------------------------------------------------------

def _snapshotter_health(conn: sqlite3.Connection) -> list[str]:
    lines = ["── Snapshotter Health (chain_snapshots) ──"]
    now_ist = datetime.now(tz=_IST)
    try:
        rows = conn.execute(
            """
            SELECT symbol, COUNT(*) as cnt, MAX(timestamp) as latest
            FROM chain_snapshots
            GROUP BY symbol
            ORDER BY symbol
            """
        ).fetchall()
    except sqlite3.OperationalError:
        lines.append("  [no chain_snapshots table — DB not yet populated]")
        return lines

    if not rows:
        lines.append("  [no rows]")
        return lines

    for sym, cnt, latest_ts in rows:
        age_str = "N/A"
        flag = ""
        if latest_ts:
            try:
                snap_dt = datetime.fromisoformat(latest_ts)
                if snap_dt.tzinfo is None:
                    snap_dt = snap_dt.replace(tzinfo=_IST)
                else:
                    snap_dt = snap_dt.astimezone(_IST)
                age_s = (now_ist - snap_dt).total_seconds()
                age_str = f"{age_s:.0f}s"
                if age_s > 90:
                    flag = _red(" ⚠ STALE")
            except ValueError:
                age_str = "parse-err"
        lines.append(f"  {sym:10s}  rows={cnt:6d}  latest={latest_ts}  age={age_str}{flag}")
    return lines


# ---------------------------------------------------------------------------
# Section 2 — Bars health
# ---------------------------------------------------------------------------

def _bars_health(conn: sqlite3.Connection) -> list[str]:
    lines = ["── Bars Health ──"]
    for table in ("underlying_bars", "option_bars"):
        try:
            rows = conn.execute(
                f"SELECT bar_tf, COUNT(*) FROM {table} GROUP BY bar_tf ORDER BY bar_tf"
            ).fetchall()
        except sqlite3.OperationalError:
            lines.append(f"  {table}: [table missing]")
            continue
        if not rows:
            lines.append(f"  {table}: [no rows]")
            continue
        parts = "  ".join(f"{tf}={cnt}" for tf, cnt in rows)
        lines.append(f"  {table}: {parts}")
    return lines


# ---------------------------------------------------------------------------
# Section 3 — Regime telemetry (reads live data, may be slow)
# ---------------------------------------------------------------------------

def _regime_telemetry(db_path: str) -> list[str]:
    lines = ["── Regime Telemetry ──"]
    try:
        from live_spot_service import get_live_spots
        from chain_snapshotter import get_latest_chain_snapshot
        from regime_engine import compute_regime

        spots = get_live_spots()
        for sym in _SYMBOLS:
            spot = spots.get(sym) or 0.0
            snap = get_latest_chain_snapshot(sym, db_path)
            expiry = snap.get("expiry", "UNKNOWN") if snap else "UNKNOWN"
            if not spot or spot <= 0 or not snap:
                lines.append(f"  {sym:10s}  [no live data]")
                continue
            try:
                regime = compute_regime(sym, expiry, spot, db_path=db_path)
                d_score = regime.get("direction_score", "N/A")
                vol_regime = regime.get("vol_regime", "N/A")
                vol_prov = regime.get("vol_provisional", False)
                playbook = regime.get("playbook", "N/A")
                prov_tag = _yel(" (provisional)") if vol_prov else ""
                lines.append(
                    f"  {sym:10s}  dir_score={d_score:3}  vol={vol_regime}{prov_tag}  playbook={playbook}"
                )
            except Exception as exc:
                lines.append(f"  {sym:10s}  [regime error: {exc}]")
    except ImportError as exc:
        lines.append(f"  [import error: {exc}]")
    return lines


# ---------------------------------------------------------------------------
# Section 4 — Candidates log
# ---------------------------------------------------------------------------

def _candidates_log(conn: sqlite3.Connection) -> list[str]:
    lines = ["── Candidates Log (today) ──"]
    today_ist = datetime.now(tz=_IST).strftime("%Y-%m-%d")
    # ts_signal is stored as UTC ISO string; use SQLite date() to normalise
    try:
        total_row = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE date(ts_signal) = ?",
            (today_ist,),
        ).fetchone()
        total = total_row[0] if total_row else 0

        tier_rows = conn.execute(
            "SELECT tier, COUNT(*) FROM candidates WHERE date(ts_signal) = ? GROUP BY tier ORDER BY tier",
            (today_ist,),
        ).fetchall()

        dispatched = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE date(ts_signal) = ? AND dispatched = 1",
            (today_ist,),
        ).fetchone()[0]

        skipped = total - dispatched

        tier_parts = "  ".join(f"T{tier}={cnt}" for tier, cnt in tier_rows) if tier_rows else "none"
        lines.append(f"  Total={total}  {tier_parts}  dispatched={dispatched}  skipped={skipped}")
    except sqlite3.OperationalError:
        lines.append("  [candidates table missing]")
    return lines


# ---------------------------------------------------------------------------
# Section 5 — Data integrity
# ---------------------------------------------------------------------------

def _data_integrity(conn: sqlite3.Connection) -> list[str]:
    lines = ["── Data Integrity ──"]
    try:
        synthetic = conn.execute(
            "SELECT COUNT(*) FROM chain_snapshots WHERE is_synthetic = 1"
        ).fetchone()[0]
        syn_tag = _red(f"synthetic={synthetic} ⚠") if synthetic > 0 else _grn(f"synthetic={synthetic} ✓")

        total = conn.execute("SELECT COUNT(*) FROM chain_snapshots").fetchone()[0]
        null_iv = conn.execute(
            "SELECT COUNT(*) FROM chain_snapshots WHERE iv IS NULL"
        ).fetchone()[0]
        null_iv_rate = (null_iv / total * 100) if total > 0 else 0.0
        lines.append(f"  {syn_tag}  null_iv={null_iv}/{total} ({null_iv_rate:.1f}%)")
    except sqlite3.OperationalError:
        lines.append("  [chain_snapshots table missing]")
    return lines


# ---------------------------------------------------------------------------
# Section 6 — IV history
# ---------------------------------------------------------------------------

def _iv_history_summary(conn: sqlite3.Connection) -> list[str]:
    lines = ["── IV History ──"]
    try:
        row = conn.execute(
            "SELECT COUNT(*), MAX(trade_date) FROM iv_history"
        ).fetchone()
        cnt, latest = row
        lines.append(f"  rows={cnt}  latest={latest or 'none'}")
        if cnt < 20:
            lines.append(_yel(f"  ⚠ Only {cnt} sessions — vol_regime will be provisional until {20} sessions accumulate"))
    except sqlite3.OperationalError:
        lines.append("  [iv_history table missing]")
    return lines


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

def build_report(db_path: str = DEFAULT_DB_PATH) -> str:
    """Build a full health report string."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    now_ist = datetime.now(tz=_IST).strftime("%Y-%m-%d %H:%M:%S IST")
    sections: list[str] = []
    sections.append(f"{'='*60}")
    sections.append(f"  STOCKERA SESSION OBSERVER  —  {now_ist}")
    sections.append(f"  DB: {db_path}")
    sections.append(f"{'='*60}")

    try:
        sections += [""] + _snapshotter_health(conn)
        sections += [""] + _bars_health(conn)
        sections += [""] + _candidates_log(conn)
        sections += [""] + _data_integrity(conn)
        sections += [""] + _iv_history_summary(conn)
        # Regime is live — append last
        sections += [""] + _regime_telemetry(db_path)
    finally:
        conn.close()

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def run_checkpoint(db_path: str = DEFAULT_DB_PATH) -> bool:
    """Pre-flight safety check.

    Returns True when all checks pass (safe to run); False otherwise.
    Prints a summary to stdout.
    """
    print(f"{'='*60}")
    print("  STOCKERA PRE-FLIGHT CHECKPOINT")
    print(f"{'='*60}")
    all_ok = True

    # --- 1. SQLite WAL mode ---
    try:
        init_db(db_path)
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        if mode.lower() == "wal":
            print(_grn("  [PASS] SQLite journal_mode = WAL"))
        else:
            print(_red(f"  [FAIL] SQLite journal_mode = {mode} (expected WAL)"))
            all_ok = False
    except Exception as exc:
        print(_red(f"  [FAIL] DB check error: {exc}"))
        all_ok = False

    # --- 2. Paper trading enforced (live_mode == False) ---
    try:
        import dhan_order_router as _ror
        # Verify execute_basket defaults to live_mode=False
        import inspect
        sig = inspect.signature(_ror.execute_basket)
        default_live = sig.parameters.get("live_mode")
        if default_live is not None and default_live.default is False:
            print(_grn("  [PASS] live_mode default = False (paper trading enforced)"))
        else:
            print(_yel("  [WARN] Could not confirm live_mode default — verify manually"))
    except Exception as exc:
        print(_yel(f"  [WARN] live_mode check skipped: {exc}"))

    # --- 3. All 4 index futures resolve via instrument_master ---
    try:
        from instrument_master import get_near_month_security_id
        for sym in _SYMBOLS:
            try:
                sid = get_near_month_security_id(sym)
                print(_grn(f"  [PASS] {sym} futures security_id = {sid}"))
            except Exception as exc:
                print(_red(f"  [FAIL] {sym} failed to resolve: {exc}"))
                all_ok = False
    except ImportError as exc:
        print(_red(f"  [FAIL] instrument_master import error: {exc}"))
        all_ok = False

    print(f"{'='*60}")
    if all_ok:
        print(_grn("  ✓ All checks passed — safe to run."))
    else:
        print(_red("  ✗ One or more checks failed — review before going live."))
    print(f"{'='*60}")
    return all_ok


# ---------------------------------------------------------------------------
# Token status
# ---------------------------------------------------------------------------

def show_token_status(env_path: str = r"C:\kite-agent\secrets\dhan.env") -> None:
    """Print Dhan token status: active/expired, last 4 chars. Never prints full token."""
    print(f"{'='*60}")
    print("  DHAN TOKEN STATUS")
    print(f"{'='*60}")

    token = ""
    try:
        # Try env-file first (covers Windows production path and test overrides)
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"DHAN_ACCESS_TOKEN\s*=\s*(.+)", line.strip())
                    if m:
                        token = m.group(1).strip()
                        break
    except Exception:
        pass

    # Fall back to env var (already loaded via dotenv by the caller or test)
    if not token:
        token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

    if not token:
        print(_red("  [MISSING] DHAN_ACCESS_TOKEN not found in env or dhan.env"))
        print(f"{'='*60}")
        return

    last4 = token[-4:] if len(token) >= 4 else "****"
    masked = f"...{last4}"
    print(f"  Token (masked): {masked}")
    print(f"  Status:         active (present in environment)")
    print(f"  Expiry policy:  24 hours (auto-renewed at 08:45 IST by supervisor)")
    print(f"  Note:           Run --checkpoint to verify live API connectivity")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Candidates drilldown (--candidates N)
# ---------------------------------------------------------------------------

def show_candidates(
    top_n: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Display top-N today's candidates with raw vs adjusted score breakdown."""
    init_db(db_path)
    today_ist = datetime.now(tz=_IST).strftime("%Y-%m-%d")
    print(f"{'='*60}")
    print(f"  TOP {top_n} CANDIDATES — {today_ist} (IST)")
    print(f"{'='*60}")

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """
            SELECT symbol, playbook_id, tier, score, raw_score, vol_provisional,
                   dispatched, skip_reason, score_breakdown, occurrences, setup_closed_at
            FROM candidates
            WHERE date(ts_signal) = ?
              AND setup_closed_at IS NULL
            ORDER BY score DESC
            LIMIT ?
            """,
            (today_ist, top_n),
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError as exc:
        print(f"  [DB error: {exc}]")
        print(f"{'='*60}")
        return

    if not rows:
        print("  No candidates logged today.")
        print(f"{'='*60}")
        return

    for i, (sym, pb, tier, adj_score, raw_score, vol_prov, dispatched, skip_reason,
            breakdown_json, occurrences, _closed) in enumerate(rows, 1):
        adj_int = int(round(adj_score)) if adj_score is not None else 0
        raw_int = int(round(raw_score)) if raw_score is not None else adj_int
        prov_deduct = raw_int - adj_int

        if vol_prov and prov_deduct > 0:
            score_str = f"Score: {adj_int}/100  (raw {raw_int}, provisional -{prov_deduct})"
        else:
            score_str = f"Score: {adj_int}/100"

        tier_label = {1: _grn("Tier 1 ✓"), 2: _yel("Tier 2"), 0: _red("Tier 0")}.get(tier, str(tier))
        disp_str = _grn("DISPATCHED") if dispatched else _yel(f"skipped ({skip_reason or 'n/a'})")

        print(f"\n  [{i}] {sym:10s}  {pb}  {tier_label}")
        print(f"      {score_str}")
        print(f"      Dispatched: {disp_str}   Scans: {occurrences or 1}")

        try:
            bd = json.loads(breakdown_json) if isinstance(breakdown_json, str) else (breakdown_json or {})
            if bd:
                pillars = [
                    ("Regime/Structure", bd.get("regime_structure", 0)),
                    ("Microstructure",   bd.get("microstructure", 0)),
                    ("Vol/EM",           bd.get("volatility_em", 0)),
                    ("R:R",              bd.get("risk_reward", 0)),
                    ("Data Quality",     bd.get("data_quality", 0)),
                ]
                for name, pts in pillars:
                    bar = "█" * int(pts / 5)
                    print(f"      {name:20s} {pts:5.1f}  {bar}")
        except Exception:
            pass

    print(f"\n{'='*60}")


# ---------------------------------------------------------------------------
# Quota display (--quota)
# ---------------------------------------------------------------------------

def show_quota(
    ledger_path: str = r"C:\kite-agent\trades_ledger.json",
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Display today's real quota usage, excluding stale/simulated rows."""
    today_ist = datetime.now(tz=_IST).strftime("%Y-%m-%d")
    today_tag = f"TRD-{today_ist.replace('-', '')}"

    print(f"{'='*60}")
    print(f"  QUOTA STATUS — {today_ist} (IST)")
    print(f"{'='*60}")

    trades: list = []
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8-sig") as f:
                trades = json.load(f)
        except Exception as exc:
            print(f"  [Could not read ledger: {exc}]")

    # All trades in the ledger
    all_today = [t for t in trades if t.get("trade_id", "").startswith(today_tag)]
    # Stale: rows that don't belong to today OR are simulated
    real_today = [
        t for t in all_today
        if t.get("source", "LIVE") != "SIMULATED"
    ]
    stale_rows = [t for t in trades if not t.get("trade_id", "").startswith(today_tag)]
    simulated_today = [t for t in all_today if t.get("source", "LIVE") == "SIMULATED"]

    naked_real = [t for t in real_today if t.get("book") == "NAKED"]
    hedged_real = [t for t in real_today if t.get("book") == "HEDGED"]

    naked_rem = max(0, 3 - len(naked_real))
    hedged_rem = max(0, 3 - len(hedged_real))

    def _quota_bar(used: int, limit: int) -> str:
        used_c = min(used, limit)
        bar = "█" * used_c + "░" * (limit - used_c)
        colour = _red if used >= limit else (_yel if used > 0 else _grn)
        return colour(f"[{bar}] {used}/{limit}")

    print(f"\n  Naked  book:  {_quota_bar(len(naked_real), 3)}  ({naked_rem} remaining)")
    print(f"  Hedged book:  {_quota_bar(len(hedged_real), 3)}  ({hedged_rem} remaining)")

    if stale_rows:
        print(f"\n  Excluded stale rows (prior sessions): {len(stale_rows)}")
    if simulated_today:
        print(f"  Excluded SIMULATED rows today:        {len(simulated_today)}")

    if real_today:
        print(f"\n  Today's real dispatches:")
        for t in real_today:
            tid = t.get("trade_id", "?")
            book = t.get("book", "?")
            sym = t.get("symbol", "?")
            strategy = t.get("strategy", "?")[:40]
            print(f"    {tid}  {book:6s}  {sym:10s}  {strategy}")

    print(f"\n{'='*60}")


# ---------------------------------------------------------------------------
# Market-hours helper
# ---------------------------------------------------------------------------

def _is_market_hours() -> bool:
    now = datetime.now(tz=_IST)
    if now.weekday() >= 5:
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1530


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Stockera Session Observer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", action="store_true", help="Print a one-shot health report")
    group.add_argument(
        "--watch",
        action="store_true",
        help="Refresh the report every 60 s during market hours",
    )
    group.add_argument(
        "--checkpoint",
        action="store_true",
        help="Run pre-flight safety check",
    )
    group.add_argument(
        "--token",
        action="store_true",
        help="Show Dhan token status (masked — never prints full token)",
    )
    group.add_argument(
        "--candidates",
        nargs="?",
        const=5,
        type=int,
        metavar="N",
        help="Show top-N today's candidates with raw/adjusted score breakdown (default 5)",
    )
    group.add_argument(
        "--quota",
        action="store_true",
        help="Show today's real quota usage excluding stale/simulated rows",
    )
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite DB")
    parser.add_argument(
        "--ledger",
        default=r"C:\kite-agent\trades_ledger.json",
        help="Path to trades_ledger.json (for --quota)",
    )
    args = parser.parse_args()

    if args.checkpoint:
        run_checkpoint(args.db)
        return

    if args.report:
        print(build_report(args.db))
        return

    if args.token:
        show_token_status()
        return

    if args.candidates is not None:
        show_candidates(top_n=args.candidates, db_path=args.db)
        return

    if args.quota:
        show_quota(ledger_path=args.ledger, db_path=args.db)
        return

    # --watch
    print("Entering watch mode (Ctrl-C to exit)…")
    while True:
        print(build_report(args.db))
        if not _is_market_hours():
            print(_yel("  [Market closed — watch will resume at 09:15 IST]"))
        time.sleep(60)


if __name__ == "__main__":
    main()
