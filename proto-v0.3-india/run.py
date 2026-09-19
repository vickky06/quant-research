"""v0.3 India pipeline runner — mean_reversion on Nifty 500.

Note: The LOW_VOL_UP_TREND regime gate (ADR-0007) was derived from US v0.2
data. India fast-mode evaluation shows mean_reversion has POSITIVE IC
(+0.032) in LOW_VOL_UP_TREND — the gate is NOT applicable to India.
Running without skip_regimes (all months traded).

Usage:
    python run.py                        # full Nifty 500 universe
    python run.py --fast                 # 50 large-caps only
    python run.py --agent mean_reversion # single agent
    python run.py --agent meta_ensemble  # meta_ensemble only
"""

from __future__ import annotations

import argparse
import json
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
    get_sector_map,
    get_universe,
    load_index,
    load_prices,
    save_json,
    scorecard_to_dict,
)
from run_log import log_run

# No hard regime gate for India (LOW_VOL_UP_TREND IC is positive here).
SKIP_REGIMES: frozenset[str] | None = None

# Regime-conditional signal weights:
# - DOWN_TREND months: mean_reversion dominates (IC +0.074 vs momentum -0.080)
# - UP_TREND months: momentum dominates (IC +0.052 vs mean_reversion +0.033)
# Weights are normalised internally; sector_neutral_mr always contributes.
REGIME_SIGNAL_WEIGHTS: dict[str, dict[str, float]] = {
    "HIGH_VOL_DOWN_TREND": {"mean_reversion": 0.45, "sector_neutral_mr": 0.45, "momentum": 0.10},
    "HIGH_VOL_UP_TREND":   {"mean_reversion": 0.15, "sector_neutral_mr": 0.20, "momentum": 0.65},
    "LOW_VOL_UP_TREND":    {"mean_reversion": 0.15, "sector_neutral_mr": 0.20, "momentum": 0.65},
    "LOW_VOL_DOWN_TREND":  {"mean_reversion": 0.45, "sector_neutral_mr": 0.45, "momentum": 0.10},
}


def run_meta_ensemble(
    signals_by_agent: dict,
    close_wide: pd.DataFrame,
    liquidity_60d: pd.DataFrame,
    regime_df: pd.DataFrame,
    mode: str,
    universe_symbols_requested: int,
) -> dict:
    """Backtest the IC-weighted Meta-Learner with regime-conditional weights."""
    print("\n" + "=" * 70)
    print("Backtesting: meta_ensemble  (regime-conditional weights)")
    print("=" * 70)

    result = P.run_meta_ensemble_backtest(
        signals_by_agent=signals_by_agent,
        close_wide=close_wide,
        liquidity_60d=liquidity_60d,
        regime_df=regime_df,
        training_start=TRAINING_START,
        training_end=TRAINING_END,
        cost_bps=ROUNDTRIP_COST_BPS,
        skip_regimes=SKIP_REGIMES,
        regime_signal_weights=REGIME_SIGNAL_WEIGHTS,
    )

    n_rebalances = len(result.monthly_returns)
    n_traded = n_rebalances - result.skipped_months
    mean_turnover = float(result.turnover.mean())
    total_return = float((1 + result.monthly_returns).prod() - 1)

    print(f"  Rebalances:        {n_rebalances}")

    ic_series = P.compute_ic_per_rebalance(
        result.signal_at_rebalance, result.forward_returns
    )
    scorecard = P.compute_regime_scorecard(ic_series, result.regime_at_rebalance)
    dsr_result = compute_dsr(result.monthly_returns)
    gate = evaluate_gate_g1(dsr_result, scorecard, threshold_dsr=0.5)
    dd_result = P.compute_max_drawdown(result.monthly_returns)

    print(f"  Cum L/S net:       {total_return:+.2%}")
    print(f"  Sharpe (ann.):     {dsr_result['sharpe_annualized']:+.3f}")
    print(f"  DSR (PSR):         {dsr_result['psr']:.3f}")
    print(f"  Mean IC:           {ic_series.mean():+.4f}")
    print(f"  Turnover:          {mean_turnover:.1%}")
    print(f"  Max drawdown:      {dd_result['max_drawdown']:+.2%}  "
          f"({dd_result.get('duration_months')}m peak-to-trough, "
          f"recovery: {dd_result.get('recovery_months')}m)")

    if not result.weights_at_rebalance.empty:
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
        gated = SKIP_REGIMES is not None and regime in SKIP_REGIMES
        if excluded:
            marker = "—"
            suffix = " (insufficient sample)"
        elif gated:
            marker = "⊘"
            suffix = f" (GATED — {n} months skipped)"
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
            "mean_reversion_window_days": P.MEAN_REVERSION_WINDOW_DAYS,
            "deciles": P.DECILES,
            "cost_bps": P.ROUNDTRIP_COST_BPS,
            "meta_ic_window_months": P.META_IC_WINDOW_MONTHS,
            "meta_min_weight": P.META_MIN_WEIGHT,
            "meta_max_weight": P.dynamic_max_weight(len(signals_by_agent)),
            "meta_shrinkage": P.META_SHRINKAGE,
            "meta_reset_every_months": P.META_RESET_EVERY_MONTHS,
            "skip_regimes": list(SKIP_REGIMES) if SKIP_REGIMES else [],
            "skipped_months": result.skipped_months,
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

    proto_root = Path(__file__).parent
    out_dir = proto_root / "output"
    out_dir.mkdir(exist_ok=True)
    if not result.weights_at_rebalance.empty:
        (out_dir / "meta_weights.csv").write_text(result.weights_at_rebalance.to_csv())
    if not result.per_agent_ic_at_rebalance.empty:
        (out_dir / "meta_ic_evolution.csv").write_text(
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
        "skipped_months": result.skipped_months,
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
    """Backtest one Agent (no regime gate — gate applies only to meta_ensemble)."""
    print("\n" + "=" * 70)
    print(f"Backtesting: {agent_name}")
    print("=" * 70)

    result = P.run_backtest(
        close_wide=close_wide,
        momentum=signal_df,
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
        agent=agent_name,
        universe_size=int(close_wide.shape[1]),
        params={
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
    out_dir.mkdir(exist_ok=True)

    assert TRAINING_END < HELD_OUT_START, "training/held-out overlap — contract violation"

    print("=" * 70)
    print("v0.3 India — Nifty 500 mean_reversion (no regime gate)")
    print(f"Training window: {TRAINING_START.date()} → {TRAINING_END.date()}")
    print(f"Data window:     {DATA_START.date()} → {TRAINING_END.date()}")
    print(f"Held-out LOCKED: {HELD_OUT_START.date()} onward — untouched")
    print(f"Regime weights:  DOWN→MR-heavy, UP→momentum-heavy (regime-conditional)")
    print(f"Mode: {'FAST (50 large-caps)' if fast else 'FULL (Nifty 500)'}")
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

    # ---- Sector map (for sector_neutral_mr) ----
    sector_map = get_sector_map(fast=fast)
    print(f"[step] sector map: {len(sector_map)} tickers assigned")

    # ---- Signals ----
    print("[step] computing per-Agent signals")
    signals = {}
    for name, fn in AGENTS.items():
        signals[name] = fn(close_wide, index_close=index_close, sector_map=sector_map)
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
            results.append(
                run_for_signal(
                    target, ensemble_signal, close_wide, liquidity_60d, regime_df, mode, len(symbols)
                )
            )
        elif target == "meta_ensemble":
            results.append(
                run_meta_ensemble(
                    signals, close_wide, liquidity_60d, regime_df, mode, len(symbols)
                )
            )
        else:
            results.append(
                run_for_signal(
                    target, signals[target], close_wide, liquidity_60d, regime_df, mode, len(symbols)
                )
            )

    # ---- Summary ----
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
        skipped = f"  [{r.get('skipped_months',0)} gated]" if "skipped_months" in r else ""
        print(
            f"{r['agent']:<15} {r['verdict']:<6} {r['dsr']:>6.3f} "
            f"{r['sharpe']:>+8.3f} {r['cum_return']:>+9.2%} "
            f"{r['max_drawdown']:>+8.2%}{skipped}"
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
        print(f"  Sharpe ≥ 1.0:     {'✓' if g2['sharpe_pass'] else '✗'}  "
              f"(observed {g2['observed_sharpe']:+.3f})")
        print(f"  PSR ≥ 0.90:       {'✓' if g2['psr_pass'] else '✗'}  "
              f"(observed {g2['observed_psr']:.3f})")
        print(f"  Max DD ≤ 25%:     {'✓' if g2['dd_pass'] else '✗'}  "
              f"(observed {g2['observed_max_dd']:.2%})")
        print("=" * 70)

    # ---- Walk-forward on meta_ensemble ----
    meta_result = next((r for r in results if r["agent"] == "meta_ensemble"), None)
    if meta_result:
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
            skip_regimes=SKIP_REGIMES,
            regime_signal_weights=REGIME_SIGNAL_WEIGHTS,
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
        if wf_summary:
            print(f"  Aggregate: mean SR = {wf_summary['mean_sharpe']:+.3f}, "
                  f"median = {wf_summary['median_sharpe']:+.3f}, "
                  f"std = {wf_summary['std_sharpe']:.3f}")
            print(f"             positive folds: {wf_summary['positive_folds']}/{wf_summary['n_folds']} "
                  f"({wf_summary['positive_fold_rate']:.0%})")

        print("\n  Multi-trial Deflated Sharpe — DSR bracket:")
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

        (out_dir / "walkforward_folds.csv").write_text(wf_folds.to_csv(index=False))
        with open(out_dir / "walkforward_summary.json", "w") as f:
            json.dump({
                "summary": wf_summary,
                "multi_trial_bracket": {str(k): v for k, v in mt_bracket.items()},
            }, f, indent=2, default=str)

        print("=" * 70)

    save_json(final["scorecard"], out_dir / "regime_scorecard.json")
    save_json(final["gate"], out_dir / "gate_g1_result.json")

    print(f"\nOutputs written to {out_dir}/")
    return 0 if all(r["verdict"] == "PASS" for r in results) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="50 large-caps only")
    parser.add_argument(
        "--agent",
        default="all",
        help="mean_reversion | ensemble | meta_ensemble | all (default)",
    )
    args = parser.parse_args()
    sys.exit(main(fast=args.fast, agent=args.agent))
