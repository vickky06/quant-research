"""v0.2 pipeline runner — backtests each Agent + the equal-weight Ensemble.

Answers three questions in one pass:
    1. Does the momentum Agent pass Gate G1?
    2. Does the low-vol Agent pass Gate G1?
    3. Does the ensemble pass Gate G1 (and hint at Gate G2)?

Usage:
    python run.py                        # all agents + ensemble, full Nifty 500
    python run.py --fast                 # all agents + ensemble, 30 large-caps
    python run.py --agent momentum       # single agent
    python run.py --agent low_vol
    python run.py --agent ensemble
"""

from __future__ import annotations

import argparse
import sys
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
    compute_ensemble,
    compute_ic_per_rebalance,
    compute_regime,
    compute_regime_scorecard,
    download_index,
    download_prices,
    evaluate_gate_g1,
    get_universe,
    load_index,
    load_prices,
    save_json,
    scorecard_to_dict,
)
from run_log import log_run


def run_for_signal(
    agent_name: str,
    signal_df: pd.DataFrame,
    close_wide: pd.DataFrame,
    liquidity_60d: pd.DataFrame,
    regime_df: pd.DataFrame,
    mode: str,
    universe_symbols_requested: int,
) -> dict:
    """Backtest one Agent (or the ensemble). Returns summary dict; persists to SQLite."""
    print("\n" + "=" * 70)
    print(f"Backtesting: {agent_name}")
    print("=" * 70)

    result = P.run_backtest(
        close_wide=close_wide,
        momentum=signal_df,  # generic — any per-Instrument rank signal
        liquidity_60d=liquidity_60d,
        regime_df=regime_df,
        training_start=TRAINING_START,
        training_end=TRAINING_END,
        cost_bps=ROUNDTRIP_COST_BPS,
    )

    n_rebalances = len(result.monthly_returns)
    mean_turnover = float(result.turnover.mean())
    total_return = float((1 + result.monthly_returns).prod() - 1)

    ic_series = P.compute_ic_per_rebalance(
        result.signal_at_rebalance, result.forward_returns
    )
    scorecard = P.compute_regime_scorecard(ic_series, result.regime_at_rebalance)
    dsr_result = compute_dsr(result.monthly_returns)
    gate = evaluate_gate_g1(dsr_result, scorecard, threshold_dsr=0.5)

    print(f"  Rebalances:        {n_rebalances}")
    print(f"  Cum L/S net:       {total_return:+.2%}")
    print(f"  Sharpe (ann.):     {dsr_result['sharpe_annualized']:+.3f}")
    print(f"  DSR (PSR):         {dsr_result['psr']:.3f}")
    print(f"  Mean IC:           {ic_series.mean():+.4f}")
    print(f"  Turnover:          {mean_turnover:.1%}")
    insufficient = set(gate.get("regimes_insufficient_sample", []))
    print(f"  Regime Scorecard (n<{gate.get('regime_min_n', 10)} excluded per Contract v1.1):")
    for regime, row in scorecard.iterrows():
        n = int(row["count"])
        excluded = regime in insufficient
        if excluded:
            marker = "—"
            suffix = " (insufficient sample)"
        else:
            marker = "✓" if row["mean"] > 0 else "✗"
            suffix = ""
        print(f"    {marker} {regime:22s}  IC={row['mean']:+.4f}  n={n}{suffix}")
    print(
        f"  Gate G1:           {'PASS ✓' if gate['verdict'] == 'PASS' else 'FAIL ✗'}"
        f" (DSR pass={gate['dsr_pass']}, regime pass={gate['regime_pass']}: "
        f"{gate['regime_positive_count']}/{gate['regime_total_evaluated']} eligible)"
    )

    scorecard_dict = scorecard_to_dict(scorecard)
    run_id = log_run(
        mode=mode,
        agent=agent_name,
        universe_size=int(close_wide.shape[1]),
        params={
            "momentum_lookback_months": P.MOMENTUM_LOOKBACK_MONTHS,
            "momentum_skip_months": P.MOMENTUM_SKIP_MONTHS,
            "mean_reversion_window_days": P.MEAN_REVERSION_WINDOW_DAYS,
            "deciles": P.DECILES,
            "cost_bps": P.ROUNDTRIP_COST_BPS,
            "training_start": str(TRAINING_START.date()),
            "training_end": str(TRAINING_END.date()),
            "universe_symbols_requested": universe_symbols_requested,
        },
        verdict=gate["verdict"],
        dsr=gate["observed_dsr_psr"],
        sharpe_annualized=dsr_result["sharpe_annualized"],
        cumulative_return=total_return,
        ic_mean=float(ic_series.mean()),
        ic_positive_regimes=gate["regime_positive_count"],
        ic_total_regimes=gate["regime_total_evaluated"],
        n_rebalances=n_rebalances,
        n_monthly_observations=dsr_result["T"],
        avg_turnover=mean_turnover,
        scorecard=scorecard_dict,
    )
    print(f"  Logged as run_id={run_id}")

    return {
        "agent": agent_name,
        "run_id": run_id,
        "verdict": gate["verdict"],
        "dsr": gate["observed_dsr_psr"],
        "sharpe": dsr_result["sharpe_annualized"],
        "cum_return": total_return,
        "scorecard": scorecard_dict,
        "gate": gate,
    }


def main(fast: bool = False, agent: str = "all") -> int:
    np.random.seed(42)

    proto_root = Path(__file__).parent
    db_path = proto_root / "data" / "prices.duckdb"
    out_dir = proto_root / "output"

    assert TRAINING_END < HELD_OUT_START, "training/held-out overlap — contract violation"

    print("=" * 70)
    print("v0.2 Multi-Agent Prototype — Gate G1 evaluation per Agent + Ensemble")
    print(f"Training window: {TRAINING_START.date()} → {TRAINING_END.date()}")
    print(f"Data window:     {DATA_START.date()} → {TRAINING_END.date()}")
    print(f"Held-out LOCKED: {HELD_OUT_START.date()} onward — untouched")
    print(f"Mode: {'FAST (30 large-caps)' if fast else 'FULL (Nifty 500)'}")
    print(f"Target: {agent}")
    print("=" * 70)

    # ---- Universe + data ingestion ----
    symbols = get_universe(fast=fast)
    print(f"[step] universe: {len(symbols)} symbols")

    download_index(db_path, DATA_START, TRAINING_END)
    download_prices(symbols, DATA_START, TRAINING_END, db_path)

    prices_long = load_prices(db_path)
    index_close = load_index(db_path)

    if prices_long.empty:
        print("[fatal] no price data")
        return 1

    print(f"[step] loaded {len(prices_long):,} price rows; index rows={len(index_close)}")

    # ---- Filters + wide-form ----
    prices_long = apply_universe_filters(prices_long)
    close_wide = prices_long.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices_long.pivot(index="date", columns="symbol", values="volume")
    turnover = close_wide * volume
    liquidity_60d = turnover.rolling(60, min_periods=30).mean()

    # ---- Signals ----
    print("[step] computing per-Agent signals")
    signals = {}
    for name, fn in AGENTS.items():
        signals[name] = fn(close_wide)
        print(f"  {name}: shape={signals[name].shape}")

    ensemble_signal = compute_ensemble(signals)
    print(f"  ensemble (equal-weight): shape={ensemble_signal.shape}")

    # ---- Regime ----
    regime_df = compute_regime(index_close)

    # ---- Determine which agents to run ----
    if agent == "all":
        targets = list(signals.keys()) + ["ensemble"]
    elif agent == "ensemble":
        targets = ["ensemble"]
    elif agent in signals:
        targets = [agent]
    else:
        print(f"[fatal] unknown agent: {agent}. Choices: {list(signals.keys()) + ['ensemble', 'all']}")
        return 1

    mode = "fast" if fast else "full"

    results = []
    for target in targets:
        sig = ensemble_signal if target == "ensemble" else signals[target]
        results.append(
            run_for_signal(
                target, sig, close_wide, liquidity_60d, regime_df, mode, len(symbols)
            )
        )

    # ---- Summary + last-run-on-disk artifacts (from the final result — typically ensemble) ----
    final = results[-1]
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    header = f"{'Agent':<12} {'Verdict':<8} {'DSR':>6} {'Sharpe':>8} {'CumRet':>9}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['agent']:<12} {r['verdict']:<8} {r['dsr']:>6.3f} "
            f"{r['sharpe']:>+8.3f} {r['cum_return']:>+9.2%}"
        )

    save_json(final["scorecard"], out_dir / "regime_scorecard.json")
    save_json(final["gate"], out_dir / "gate_g1_result.json")

    summary_lines = [
        "v0.2 Multi-Agent Backtest Summary",
        "=" * 70,
        f"Training window: {TRAINING_START.date()} → {TRAINING_END.date()}",
        f"Mode: {mode}",
        f"Universe symbols requested: {len(symbols)}",
        f"Universe symbols after filters: {close_wide.shape[1]}",
        "",
        header,
        "-" * len(header),
    ]
    for r in results:
        summary_lines.append(
            f"{r['agent']:<12} {r['verdict']:<8} {r['dsr']:>6.3f} "
            f"{r['sharpe']:>+8.3f} {r['cum_return']:>+9.2%}"
        )
    summary_lines.extend([
        "",
        f"Final regime scorecard (agent = {final['agent']}):",
        pd.DataFrame(final["scorecard"]).T.to_string(),
    ])
    (out_dir / "backtest_summary.txt").write_text("\n".join(summary_lines))

    print(f"\nOutputs written to {out_dir}/")
    return 0 if all(r["verdict"] == "PASS" for r in results) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="30 large-caps only")
    parser.add_argument(
        "--agent",
        default="all",
        help="momentum | low_vol | ensemble | all (default)",
    )
    args = parser.parse_args()
    sys.exit(main(fast=args.fast, agent=args.agent))
