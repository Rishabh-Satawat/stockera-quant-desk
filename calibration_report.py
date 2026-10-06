"""Calibration Reporter — Phase 1D.

Read-only diagnostic module.  Produces performance metrics per
(playbook_id × vol_regime) from the `candidates` table.

Statistical rule: if n < 50, display "INSUFFICIENT DATA (n < 50)" instead
of potentially-misleading early win-rate numbers.

Does NOT auto-tune weights or modify any scoring parameters.

Usage:
    python calibration_report.py [--db path] [--start YYYY-MM-DD] [--end YYYY-MM-DD]
    python calibration_report.py --json   # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Optional

import pandas as pd

from candidate_logger import load_candidates

logger = logging.getLogger(__name__)

MIN_SAMPLE_SIZE = 50


def compute_calibration_report(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute per (playbook_id, vol_regime) metrics from a candidates DataFrame.

    Input must contain columns: playbook_id, vol_regime, outcome_label,
    pnl_points, mae_points (NaNs accepted for unlabelled rows).

    Returns a summary DataFrame with one row per group.
    """
    required_cols = {"playbook_id", "vol_regime", "outcome_label", "pnl_points", "mae_points"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"calibration_report: missing columns {missing}")

    labelled = df[df["outcome_label"].notna()].copy()
    if labelled.empty:
        return pd.DataFrame(columns=[
            "playbook_id", "vol_regime", "n", "win_rate_pct",
            "avg_payoff_ratio", "expectancy", "profit_factor", "avg_mae_pts",
        ])

    rows = []
    for (playbook_id, vol_regime), group in labelled.groupby(["playbook_id", "vol_regime"]):
        n = len(group)
        winners = group[group["outcome_label"] == "WINNER"]
        losers = group[group["outcome_label"] == "LOSER"]

        if n < MIN_SAMPLE_SIZE:
            rows.append({
                "playbook_id": playbook_id,
                "vol_regime": vol_regime,
                "n": n,
                "win_rate_pct": f"INSUFFICIENT DATA (n < {MIN_SAMPLE_SIZE})",
                "avg_payoff_ratio": None,
                "expectancy": None,
                "profit_factor": None,
                "avg_mae_pts": None,
            })
            continue

        win_count = len(winners)
        loss_count = len(losers)
        win_rate = win_count / n * 100.0

        avg_win = winners["pnl_points"].mean() if win_count > 0 else 0.0
        avg_loss = abs(losers["pnl_points"].mean()) if loss_count > 0 else 0.0

        payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else None
        win_frac = win_rate / 100.0
        expectancy = (win_frac * avg_win) - ((1 - win_frac) * avg_loss)
        gross_profit = winners["pnl_points"].sum() if win_count > 0 else 0.0
        gross_loss = abs(losers["pnl_points"].sum()) if loss_count > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
        avg_mae = group["mae_points"].mean() if "mae_points" in group.columns else None

        rows.append({
            "playbook_id": playbook_id,
            "vol_regime": vol_regime,
            "n": n,
            "win_rate_pct": round(win_rate, 1),
            "avg_payoff_ratio": round(payoff_ratio, 2) if payoff_ratio is not None else None,
            "expectancy": round(expectancy, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "avg_mae_pts": round(avg_mae, 2) if avg_mae is not None else None,
        })

    return pd.DataFrame(rows).sort_values(["playbook_id", "vol_regime"]).reset_index(drop=True)


def format_report_text(report_df: pd.DataFrame) -> str:
    """Format calibration report as a human-readable string."""
    if report_df.empty:
        return "Calibration Report: no labelled candidates found."

    lines = [
        "═══════════════════════════════════════════════════════════",
        "  STOCKERA QUANT DESK — CALIBRATION REPORT",
        "  (Read-only diagnostic — does NOT auto-tune weights)",
        "═══════════════════════════════════════════════════════════",
        f"{'Playbook':<8} {'Vol Regime':<16} {'n':>5} "
        f"{'Win%':>8} {'Payoff':>8} {'Expect':>9} {'PF':>7} {'MAE':>8}",
        "───────────────────────────────────────────────────────────",
    ]

    for _, row in report_df.iterrows():
        win_rate_str = (
            row["win_rate_pct"]
            if isinstance(row["win_rate_pct"], str)
            else f"{row['win_rate_pct']:.1f}%"
        )
        payoff_str = f"{row['avg_payoff_ratio']:.2f}" if row["avg_payoff_ratio"] is not None else "—"
        expect_str = f"{row['expectancy']:.2f}" if row["expectancy"] is not None else "—"
        pf_str = f"{row['profit_factor']:.2f}" if row["profit_factor"] is not None else "—"
        mae_str = f"{row['avg_mae_pts']:.2f}" if row["avg_mae_pts"] is not None else "—"

        lines.append(
            f"{row['playbook_id']:<8} {row['vol_regime']:<16} {row['n']:>5} "
            f"{win_rate_str:>8} {payoff_str:>8} {expect_str:>9} {pf_str:>7} {mae_str:>8}"
        )

    lines.append("═══════════════════════════════════════════════════════════")
    return "\n".join(lines)


def run_report(
    db_path: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load candidates and compute calibration metrics."""
    df = load_candidates(db_path, start_date=start_date, end_date=end_date)
    if df.empty:
        return pd.DataFrame()
    return compute_calibration_report(df)


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    from db_init import DEFAULT_DB_PATH

    parser = argparse.ArgumentParser(description="Calibration report: performance by playbook × regime.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to chain_timeseries.db")
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="Filter start date")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="Filter end date")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    report_df = run_report(args.db, start_date=args.start, end_date=args.end)

    if args.json:
        print(report_df.to_json(orient="records", indent=2))
    else:
        print(format_report_text(report_df))


if __name__ == "__main__":
    main()
