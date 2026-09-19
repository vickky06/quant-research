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


def run_meta_ensemble(
    signals_by_agent: dict,
    close_wide: pd.DataFrame,
    liquidity_60d: pd.DataFrame,
    regime_df: pd.DataFrame,
    mode: str,
    universe_symbols_requested: int,
) -> dict:
    """Backtest the IC-weighted Meta-Learner. Persists to SQLite."""
    print("\n" + "=" * 70)
    print("Backtesting: meta_ensemble  (IC-weighted, shrunk, clipped)")
    print("=" * 70)

    result = P.run_meta_ensemble_backtest(
        signals_by_agent=signals_by_agent,
        close_wide=close_wide,
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
    dd_result = P.compute_max_drawdown(result.monthly_returns)

    print(f"  Rebalances:        {n_rebalances}")
    print(f"  Cum L/S net:       {total_return:+.2%}")
    print(f"  Sharpe (ann.):     {dsr_result['sharpe_annualized']:+.3f}")
    print(f"  DSR (PSR):         {dsr_result['psr']:.3f}")
    print(f"  Mean IC:           {ic_series.mean():+.4f}")
    print(f"  Turnover:          {mean_turnover:.1%}")
    print(f"  Max drawdown:      {dd_result['max_drawdown']:+.2%}  "
          f"({dd_result.get('duration_months')}m peak-to-trough, "
          f"recovery: {dd_result.get('recovery_months')}m)")

    # Weight evolution snapshot
    weights_df = result.weights_at_rebalance
    print(f"  Weight evolution ({len(weights_df)} rebalances):")
    for a in weights_df.columns:
        w_series = weights_df[a]
        print(f"    {a:15s}  mean={w_series.mean():.2%}  min={w_series.min():.2%}  max={w_series.max():.2%}")

    insufficient = set(gate.get("regimes_insufficient_sample", []))
    print(f"  Regime Scorecard (n<{gate.get('regime_min_n', 10)} excluded):")
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
        agent="meta_ensemble",
        universe_size=int(close_wide.shape[1]),
        params={
            "momentum_lookback_months": P.MOMENTUM_LOOKBACK_MONTHS,
            "momentum_skip_months": P.MOMENTUM_SKIP_MONTHS,
            "mean_reversion_window_days": P.MEAN_REVERSION_WINDOW_DAYS,
            "deciles": P.DECILES,
            "cost_bps": P.ROUNDTRIP_COST_BPS,
            "meta_ic_window_months": P.META_IC_WINDOW_MONTHS,
            "meta_min_weight": P.META_MIN_WEIGHT,
            "meta_max_weight": P.dynamic_max_weight(len(signals_by_agent)),
            "meta_shrinkage": P.META_SHRINKAGE,
            "meta_reset_every_months": P.META_RESET_EVERY_MONTHS,
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
        max_drawdown=dd_result["max_drawdown"],
        max_dd_duration_months=dd_result.get("duration_months"),
        max_dd_recovery_months=dd_result.get("recovery_months"),
    )
    print(f"  Logged as run_id={run_id}")

    # Persist weights + IC evolution to output/ for the dashboard
    proto_root = Path(__file__).parent
    (proto_root / "output" / "meta_weights.csv").write_text(weights_df.to_csv())
    (proto_root / "output" / "meta_ic_evolution.csv").write_text(
        result.per_agent_ic_at_rebalance.to_csv()
    )

    return {
        "agent": "meta_ensemble",
        "run_id": run_id,
        "verdict": gate["verdict"],
        "dsr": gate["observed_dsr_psr"],
        "sharpe": dsr_result["sharpe_annualized"],
        "cum_return": total_return,
        "max_drawdown": dd_result["max_drawdown"],
        "dsr_result": dsr_result,
        "dd_result": dd_result,
        "scorecard": scorecard_dict,
        "gate": gate,
    }


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
    dd_result = P.compute_max_drawdown(result.monthly_returns)

    print(f"  Rebalances:        {n_rebalances}")
    print(f"  Cum L/S net:       {total_return:+.2%}")
    print(f"  Sharpe (ann.):     {dsr_result['sharpe_annualized']:+.3f}")
    print(f"  DSR (PSR):         {dsr_result['psr']:.3f}")
    print(f"  Mean IC:           {ic_series.mean():+.4f}")
    print(f"  Turnover:          {mean_turnover:.1%}")
    print(f"  Max drawdown:      {dd_result['max_drawdown']:+.2%}  "
          f"({dd_result.get('duration_months')}m peak-to-trough, "
          f"recovery: {dd_result.get('recovery_months')}m)")
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
        max_drawdown=dd_result["max_drawdown"],
        max_dd_duration_months=dd_result.get("duration_months"),
        max_dd_recovery_months=dd_result.get("recovery_months"),
    )
    print(f"  Logged as run_id={run_id}")

    return {
        "agent": agent_name,
        "run_id": run_id,
        "verdict": gate["verdict"],
        "dsr": gate["observed_dsr_psr"],
        "sharpe": dsr_result["sharpe_annualized"],
        "cum_return": total_return,
        "max_drawdown": dd_result["max_drawdown"],
        "dsr_result": dsr_result,
        "dd_result": dd_result,
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
        signals[name] = fn(close_wide, index_close=index_close)
        print(f"  {name}: shape={signals[name].shape}")

    ensemble_signal = compute_ensemble(signals)
    print(f"  ensemble (equal-weight): shape={ensemble_signal.shape}")

    # ---- Regime ----
    regime_df = compute_regime(index_close)

    # ---- Determine which agents to run ----
    ensemble_kinds = ["ensemble", "meta_ensemble"]
    if agent == "all":
        targets = list(signals.keys()) + ensemble_kinds
    elif agent in ensemble_kinds:
        targets = [agent]
    elif agent in signals:
        targets = [agent]
    else:
        choices = list(signals.keys()) + ensemble_kinds + ["all"]
        print(f"[fatal] unknown agent: {agent}. Choices: {choices}")
        return 1

    mode = "fast" if fast else "full"

    results = []
    for target in targets:
        if target == "ensemble":
            sig = ensemble_signal
            results.append(
                run_for_signal(
                    target, sig, close_wide, liquidity_60d, regime_df, mode, len(symbols)
                )
            )
        elif target == "meta_ensemble":
            results.append(
                run_meta_ensemble(
                    signals, close_wide, liquidity_60d, regime_df, mode, len(symbols)
                )
            )
        else:
            sig = signals[target]
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
    header = (
        f"{'Agent':<15} {'G1':<6} {'DSR':>6} {'Sharpe':>8} {'CumRet':>9} {'MaxDD':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['agent']:<15} {r['verdict']:<6} {r['dsr']:>6.3f} "
            f"{r['sharpe']:>+8.3f} {r['cum_return']:>+9.2%} "
            f"{r['max_drawdown']:>+8.2%}"
        )

    # ---- Gate G2 evaluation on best ensemble ----
    for target in ("meta_ensemble", "ensemble"):
        ensemble_result = next((r for r in results if r["agent"] == target), None)
        if not ensemble_result:
            continue
        g2 = P.evaluate_gate_g2(ensemble_result["dsr_result"], ensemble_result["dd_result"])
        print("\n" + "=" * 70)
        print(f"GATE G2 ({target} → held-out eligibility): {g2['verdict']}")
        print("=" * 70)
        print(f"  DSR ≥ 1.0:        {'✓' if g2['dsr_pass'] else '✗'}  "
              f"(observed {g2['observed_dsr']:.3f})")
        print(f"  Max DD ≤ 25%:     {'✓' if g2['dd_pass'] else '✗'}  "
              f"(observed {g2['observed_max_dd']:.2%})")
        print("=" * 70)

    # ---- Walk-forward validation on meta_ensemble ----
    meta_result = next((r for r in results if r["agent"] == "meta_ensemble"), None)
    if meta_result and hasattr(meta_result.get("dsr_result", {}), "get"):
        pass  # inspect below

    if meta_result:
        # Recover monthly_returns from the run_backtest result — we need to
        # re-run internally to get access. Simpler: pull the equity curve
        # already in the result_summary. Actually, we need the raw series.
        # Alternative: run the meta_ensemble backtest once more, purely for
        # walk-forward slicing. Cheap since data is cached.
        print("\n" + "=" * 70)
        print("Walk-forward validation (meta_ensemble sliced by year)")
        print("=" * 70)

        wf_result = P.run_meta_ensemble_backtest(
            signals_by_agent=signals,
            close_wide=close_wide,
            liquidity_60d=liquidity_60d,
            regime_df=regime_df,
            training_start=TRAINING_START,
            training_end=TRAINING_END,
            cost_bps=ROUNDTRIP_COST_BPS,
        )
        wf_folds = P.compute_walkforward_folds(wf_result.monthly_returns, fold_years=1)
        wf_summary = P.summarize_walkforward(wf_folds)

        print(f"  {'Year':<6} {'N':>4} {'Sharpe':>8} {'DSR':>7} {'CumRet':>9} {'MaxDD':>8}")
        print("  " + "-" * 50)
        for _, row in wf_folds.iterrows():
            print(
                f"  {int(row['fold_start']):<6} {int(row['n_months']):>4} "
                f"{row['sharpe_annualized']:>+8.3f} {row['dsr_psr']:>7.3f} "
                f"{row['cum_return']:>+9.2%} {row['max_drawdown']:>+8.2%}"
            )
        print("  " + "-" * 50)
        print(f"  Aggregate: mean SR = {wf_summary['mean_sharpe']:+.3f}, "
              f"median = {wf_summary['median_sharpe']:+.3f}, "
              f"std = {wf_summary['std_sharpe']:.3f}")
        print(f"             range [{wf_summary['min_sharpe']:+.3f}, {wf_summary['max_sharpe']:+.3f}]")
        print(f"             positive folds: {wf_summary['positive_folds']}/{wf_summary['n_folds']} "
              f"({wf_summary['positive_fold_rate']:.0%})")
        print(f"             mean max DD across folds: {wf_summary['mean_max_dd']:.2%}, "
              f"worst: {wf_summary['worst_max_dd']:.2%}")

        # Multi-trial deflation bracket:
        #   N=3  optimistic (only distinct signal *families* considered)
        #   N=5  moderate (signals we implemented and backtested)
        #   N=8  conservative (every config touch, including retirements + amendments)
        print("\n  Multi-trial Deflated Sharpe (Bailey-López de Prado) — DSR bracket:")
        print(f"    {'N':>4}  {'SR_null_max':>12}  {'DSR':>8}  {'Interpretation':<40}")
        interpretations = {
            3: "distinct signal families only",
            5: "signals actually implemented",
            8: "conservative (incl. retirements)",
        }
        mt_bracket = {}
        for n in (3, 5, 8):
            mt_n = P.compute_multi_trial_deflated_sharpe(
                wf_folds["sharpe_annualized"], T_per_fold=12, n_trials=n,
            )
            mt_bracket[n] = mt_n
            print(f"    {n:>4}  {mt_n['sr_expected_null']:>+12.3f}  "
                  f"{mt_n['dsr_multi_trial']:>8.3f}  {interpretations.get(n, ''):<40}")
        mt = mt_bracket[8]  # keep conservative as canonical
        print(f"    Observed mean SR (all N): {mt['mean_sr']:+.3f}, "
              f"folds: {mt['n_folds']}")

        # Persist walk-forward artifacts
        proto_root = Path(__file__).parent
        (proto_root / "output" / "walkforward_folds.csv").write_text(wf_folds.to_csv(index=False))
        import json as _json
        with open(proto_root / "output" / "walkforward_summary.json", "w") as f:
            _json.dump({
                "summary": wf_summary,
                "multi_trial_bracket": {str(k): v for k, v in mt_bracket.items()},
            }, f, indent=2, default=str)

        print("=" * 70)

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
