"""One-shot held-out validation harness — Gate G3.

⚠️  READ THIS BEFORE RUNNING.

The held-out window (2024-01-01 → 2026-06-30) is contract-locked. This
script is the ONLY place that touches it. Per contract §3:

    • Do not compute statistics on the held-out set during research
    • Do not tune hyperparameters against it — not even "just once to check"
    • One shot: single evaluation before paper trading
    • If held-out fails: back to research window. NO second bite.

Enforcement:
    1. This script REFUSES to run without `--confirm-final-evaluation`.
    2. After a successful run, it writes `output/held_out_verdict.md` and
       `output/held_out_verdict.json`. Both files are read-only markers.
    3. Subsequent invocations detect these markers and REFUSE to run
       unless `--i-am-consciously-violating-the-contract` is passed.
    4. That flag is deliberately awkward. If you use it, you are choosing
       to violate the contract — record why in `HELDOUT_OVERRIDE.md` first.

Usage:
    python run_held_out.py --confirm-final-evaluation

That's it. No parameter tuning. No mode switches. The strategy that
is evaluated is whatever the current `AGENTS` registry + Meta-Learner
config in pipeline.py define. If you want to change that, do so BEFORE
running this — and be aware that each change effectively adds to your
multi-trial count.

The training-set DSR that the G3 evaluation uses as its 60% baseline is
read from the most recent run of `python run.py`. Run that first if
you haven't recently.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import pipeline as P
from pipeline import (
    AGENTS,
    DATA_START,
    HELD_OUT_START,
    ROUNDTRIP_COST_BPS,
    TRAINING_END,
    TRAINING_START,
    apply_universe_filters,
    compute_dsr,
    compute_ic_per_rebalance,
    compute_regime,
    compute_regime_scorecard,
    download_index,
    download_prices,
    evaluate_gate_g3,
    get_sector_map,
    get_universe,
    load_index,
    load_prices,
    save_json,
    scorecard_to_dict,
)
from run_log import log_run

HELDOUT_END = pd.Timestamp("2026-06-30")  # Contract v1.2 §3
# Verdict stored under docs/heldout-us/ to avoid conflict with the India prototype's
# docs/heldout/ verdict (which is a separate locked evaluation).
_WORKSPACE_ROOT = Path(__file__).parent.parent
VERDICT_DIR = _WORKSPACE_ROOT / "docs" / "heldout-us"
VERDICT_MD = VERDICT_DIR / "verdict.md"
VERDICT_JSON = VERDICT_DIR / "verdict.json"
OVERRIDE_MD = _WORKSPACE_ROOT / "HELDOUT_OVERRIDE.md"


def check_lock() -> None:
    if VERDICT_JSON.exists() or VERDICT_MD.exists():
        print("=" * 70)
        print("HELD-OUT LOCK ENGAGED — held-out set has already been evaluated.")
        print("=" * 70)
        print(f"  Verdict recorded at: {VERDICT_JSON}")
        print(f"  Verdict summary at:  {VERDICT_MD}")
        print()
        print("Per contract §3: no second bite of the held-out apple.")
        print()
        print("If you are consciously choosing to violate the contract, ALL of:")
        print("  1. Write your justification in HELDOUT_OVERRIDE.md")
        print("  2. Pass --i-am-consciously-violating-the-contract")
        print("  3. Understand that this invalidates any G3 verdict")
        print()
        sys.exit(2)


def load_last_training_dsr() -> float:
    """Read the most recent training-set meta_ensemble DSR from run_log."""
    from run_log import read_runs

    runs = read_runs()
    if runs.empty:
        print("[fatal] no run_log entries. Execute `python run.py` first to")
        print("        establish a training-set baseline for G3's 60% floor.")
        sys.exit(3)
    meta = runs[runs["agent"] == "meta_ensemble"].sort_values(
        "timestamp", ascending=False
    )
    if meta.empty:
        print("[fatal] no meta_ensemble run in run_log; execute `python run.py` first.")
        sys.exit(3)
    return float(meta.iloc[0]["dsr"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-final-evaluation",
        action="store_true",
        help="Required. You are committing to a one-shot evaluation.",
    )
    parser.add_argument(
        "--i-am-consciously-violating-the-contract",
        action="store_true",
        help="Overrides the lock. Records violation to verdict.",
    )
    args = parser.parse_args()

    if not args.confirm_final_evaluation:
        print("Refused: --confirm-final-evaluation not passed.")
        print("Read the docstring at the top of this file before proceeding.")
        return 1

    if not args.i_am_consciously_violating_the_contract:
        check_lock()

    training_dsr = load_last_training_dsr()
    print("=" * 70)
    print("Gate G3 — One-shot held-out evaluation")
    print("=" * 70)
    print(f"Training-set meta_ensemble DSR (baseline):  {training_dsr:.3f}")
    print(f"Required held-out DSR (60% degradation):    {training_dsr * 0.6:.3f}")
    print(f"Held-out window (LOCKED):                   "
          f"{HELD_OUT_START.date()} → {HELDOUT_END.date()}")
    print("=" * 70)

    proto_root = Path(__file__).parent
    db_path = proto_root / "data" / "prices.duckdb"

    # ---- Data ingestion for held-out window ----
    # Warmup needs 18 months before held-out start (regime warmup + signal lookback).
    # Training DB already covers 2013-2023. We download the NEW data: 2024-01 onward.
    # Cache check uses HELD_OUT_START as lower bound so it detects missing post-2024 rows.
    ho_data_start = pd.Timestamp("2022-06-01")  # used for filtering/loading, not download check
    symbols = get_universe(fast=False)
    print(f"[step] universe: {len(symbols)} symbols")

    download_index(db_path, HELD_OUT_START, HELDOUT_END)
    download_prices(symbols, HELD_OUT_START, HELDOUT_END, db_path)

    prices_long = load_prices(db_path)
    prices_long = prices_long[prices_long["date"] >= ho_data_start]
    prices_long = prices_long[prices_long["date"] <= HELDOUT_END]
    index_close = load_index(db_path)
    index_close = index_close.loc[ho_data_start:HELDOUT_END]

    if prices_long.empty:
        print("[fatal] no held-out price data")
        return 1

    print(f"[step] loaded {len(prices_long):,} price rows")

    # Universe filter (listing) applied against held-out data
    # Note: for held-out we relax listing check to any stock with data in the window.
    close_wide = prices_long.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices_long.pivot(index="date", columns="symbol", values="volume")
    turnover = close_wide * volume
    liquidity_60d = turnover.rolling(60, min_periods=30).mean()

    # ---- Sector map ----
    sector_map = get_sector_map(fast=False)
    print(f"[step] sector map: {len(sector_map)} tickers assigned")

    # ---- Signals ----
    print("[step] computing per-Agent signals on held-out")
    signals = {}
    for name, fn in AGENTS.items():
        signals[name] = fn(close_wide, index_close=index_close, sector_map=sector_map)
        print(f"  {name}: shape={signals[name].shape}")

    regime_df = compute_regime(index_close)

    # ---- Meta-ensemble backtest on held-out ----
    print("[step] backtesting meta_ensemble on held-out")
    result = P.run_meta_ensemble_backtest(
        signals_by_agent=signals,
        close_wide=close_wide,
        liquidity_60d=liquidity_60d,
        regime_df=regime_df,
        training_start=HELD_OUT_START,
        training_end=HELDOUT_END,
        cost_bps=ROUNDTRIP_COST_BPS,
        heldout_mode=True,
    )

    if result.monthly_returns.empty:
        print("[fatal] no monthly returns produced on held-out")
        return 1

    n_rebalances = len(result.monthly_returns)
    mean_turnover = float(result.turnover.mean())
    total_return = float((1 + result.monthly_returns).prod() - 1)
    ic_series = compute_ic_per_rebalance(
        result.signal_at_rebalance, result.forward_returns
    )
    scorecard = compute_regime_scorecard(ic_series, result.regime_at_rebalance)
    dsr_result = compute_dsr(result.monthly_returns)
    dd_result = P.compute_max_drawdown(result.monthly_returns)

    print(f"\n  Rebalances:  {n_rebalances}")
    print(f"  Cum L/S net: {total_return:+.2%}")
    print(f"  Sharpe (ann): {dsr_result['sharpe_annualized']:+.3f}")
    print(f"  DSR (PSR):    {dsr_result['psr']:.3f}")
    print(f"  Max DD:       {dd_result['max_drawdown']:+.2%}")
    print(f"  Mean IC:      {ic_series.mean():+.4f}")
    print(f"  Turnover:     {mean_turnover:.1%}")

    print("\n  Regime Scorecard (held-out):")
    for regime, row in scorecard.iterrows():
        marker = "✓" if row["mean"] > 0 else "✗"
        print(f"    {marker} {regime:22s}  IC={row['mean']:+.4f}  n={int(row['count'])}")

    # ---- Gate G3 evaluation ----
    g3 = evaluate_gate_g3(
        training_dsr=training_dsr,
        heldout_dsr_result=dsr_result,
        heldout_dd_result=dd_result,
        heldout_scorecard=scorecard,
    )

    verdict = g3["verdict"]
    print("\n" + "=" * 70)
    print(f"GATE G3: {'PASS ✓' if verdict == 'PASS' else 'FAIL ✗'}")
    print("=" * 70)
    print(f"  DSR ≥ 60% of training ({g3['required_heldout_dsr']:.3f}):   "
          f"{'✓' if g3['dsr_pass'] else '✗'}  (observed {g3['observed_heldout_dsr']:.3f})")
    print(f"  Max DD ≤ 25%:                        "
          f"{'✓' if g3['dd_pass'] else '✗'}  (observed {g3['observed_max_dd']:.2%})")
    print(f"  Regime spread ≥ {g3['regime_required_positive']}/{g3['regime_eligible']}: "
          f"{'✓' if g3['regime_pass'] else '✗'}  ({g3['regime_positive']} positive)")
    print("=" * 70)

    # ---- Write verdict (locked) ----
    scorecard_dict = scorecard_to_dict(scorecard)
    verdict_payload = {
        "verdict": verdict,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "gate": g3,
        "sharpe_annualized": dsr_result["sharpe_annualized"],
        "cumulative_return": total_return,
        "mean_ic": float(ic_series.mean()),
        "n_rebalances": n_rebalances,
        "avg_turnover": mean_turnover,
        "regime_scorecard": scorecard_dict,
        "contract_version": "1.2",
        "override_used": args.i_am_consciously_violating_the_contract,
    }
    VERDICT_DIR.mkdir(parents=True, exist_ok=True)
    save_json(verdict_payload, VERDICT_JSON)

    md_lines = [
        f"# Held-out Verdict — Gate G3",
        f"",
        f"**Verdict**: **{verdict}**",
        f"**Timestamp**: {verdict_payload['timestamp']}",
        f"**Contract version**: 1.2",
        f"**Held-out window**: {HELD_OUT_START.date()} → {HELDOUT_END.date()}",
        f"",
        f"## Metrics",
        f"- Held-out DSR: **{g3['observed_heldout_dsr']:.3f}** (required ≥ {g3['required_heldout_dsr']:.3f})",
        f"- Held-out Sharpe (annualized, net): **{dsr_result['sharpe_annualized']:+.3f}**",
        f"- Held-out cumulative return: **{total_return:+.2%}**",
        f"- Held-out max drawdown: **{dd_result['max_drawdown']:+.2%}**",
        f"- Held-out mean IC: {ic_series.mean():+.4f}",
        f"- Rebalances: {n_rebalances}",
        f"",
        f"## Gates",
        f"- DSR ≥ 60% of training: {'✓ PASS' if g3['dsr_pass'] else '✗ FAIL'}",
        f"- Max DD ≤ 25%: {'✓ PASS' if g3['dd_pass'] else '✗ FAIL'}",
        f"- Regime spread: {'✓ PASS' if g3['regime_pass'] else '✗ FAIL'} ({g3['regime_positive']}/{g3['regime_eligible']} eligible)",
        f"",
        f"## Regime Scorecard (held-out)",
        f"",
        f"| Regime | Mean IC | Rebalances |",
        f"| --- | --- | --- |",
    ]
    for regime, row in scorecard.iterrows():
        md_lines.append(f"| {regime} | {row['mean']:+.4f} | {int(row['count'])} |")
    md_lines.extend([
        f"",
        f"---",
        f"",
        f"*This verdict is contract-locked. Do not re-run held-out evaluation.*",
        f"*If you did re-run: override_used = {args.i_am_consciously_violating_the_contract}*",
    ])
    VERDICT_MD.write_text("\n".join(md_lines))

    # Also log to SQLite
    log_run(
        mode="held_out",
        agent="meta_ensemble",
        universe_size=int(close_wide.shape[1]),
        params={"contract_version": "1.2", "gate": "G3"},
        verdict=verdict,
        dsr=g3["observed_heldout_dsr"],
        sharpe_annualized=dsr_result["sharpe_annualized"],
        cumulative_return=total_return,
        ic_mean=float(ic_series.mean()),
        ic_positive_regimes=g3["regime_positive"],
        ic_total_regimes=g3["regime_eligible"],
        n_rebalances=n_rebalances,
        n_monthly_observations=dsr_result["T"],
        avg_turnover=mean_turnover,
        scorecard=scorecard_dict,
        max_drawdown=dd_result["max_drawdown"],
        max_dd_duration_months=dd_result.get("duration_months"),
        max_dd_recovery_months=dd_result.get("recovery_months"),
        notes="Gate G3 held-out one-shot evaluation",
    )

    print(f"\n📝 Verdict written to:")
    print(f"   {VERDICT_MD}")
    print(f"   {VERDICT_JSON}")
    print(f"\n⚠️  Do not re-run this script. The verdict is locked.")

    return 0 if verdict == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
