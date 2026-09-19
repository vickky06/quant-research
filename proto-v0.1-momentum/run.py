"""v0.1 momentum prototype — end-to-end runner.

Answers one question: does 12-1 momentum on Nifty 500 (Training Set 2015-2023)
pass Gate G1 with the contract's cost model?

Usage:
    python run.py           # full universe (up to Nifty 500)
    python run.py --fast    # quick check on 30 large-caps
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import pipeline as P
from pipeline import (
    DATA_START,
    HELD_OUT_START,
    LIQUIDITY_THRESHOLD_INR,
    PRICE_FLOOR_INR,
    ROUNDTRIP_COST_BPS,
    TRAINING_END,
    TRAINING_START,
    apply_universe_filters,
    compute_dsr,
    compute_ic_per_rebalance,
    compute_momentum,
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


def main(fast: bool = False) -> int:
    np.random.seed(42)

    proto_root = Path(__file__).parent
    db_path = proto_root / "data" / "prices.duckdb"
    out_dir = proto_root / "output"

    # ---- Held-out lock ----
    assert TRAINING_END < HELD_OUT_START, "training/held-out overlap — contract violation"

    print("=" * 70)
    print("v0.1 Momentum Prototype — Gate G1 evaluation")
    print(f"Training window: {TRAINING_START.date()} → {TRAINING_END.date()}")
    print(f"Data window:     {DATA_START.date()} → {TRAINING_END.date()}")
    print(f"Held-out LOCKED: {HELD_OUT_START.date()} onward — untouched by prototype")
    print(f"Mode: {'FAST (30 large-caps)' if fast else 'FULL (Nifty 500)'}")
    print("=" * 70)

    # ---- Universe ----
    symbols = get_universe(fast=fast)
    print(f"[step] universe: {len(symbols)} symbols")

    # ---- Data ingestion ----
    download_index(db_path, DATA_START, TRAINING_END)
    download_prices(symbols, DATA_START, TRAINING_END, db_path)

    prices_long = load_prices(db_path)
    index_close = load_index(db_path)

    if prices_long.empty:
        print("[fatal] no price data — check yfinance connection or ticker validity")
        return 1

    print(f"[step] loaded {len(prices_long):,} price rows; index rows={len(index_close)}")

    # ---- Universe filter (listing) ----
    prices_long = apply_universe_filters(prices_long)

    # ---- Wide-form transforms ----
    close_wide = prices_long.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices_long.pivot(index="date", columns="symbol", values="volume")
    turnover = close_wide * volume
    liquidity_60d = turnover.rolling(60, min_periods=30).mean()

    # ---- Signal ----
    momentum = compute_momentum(close_wide)
    print(f"[step] momentum computed: shape={momentum.shape}")

    # ---- Regime ----
    regime_df = compute_regime(index_close)
    print(f"[step] regime computed: shape={regime_df.shape}")

    # ---- Backtest ----
    from pipeline import run_backtest

    result = run_backtest(
        close_wide=close_wide,
        momentum=momentum,
        liquidity_60d=liquidity_60d,
        regime_df=regime_df,
        training_start=TRAINING_START,
        training_end=TRAINING_END,
        cost_bps=ROUNDTRIP_COST_BPS,
    )

    n_rebalances = len(result.monthly_returns)
    mean_turnover = float(result.turnover.mean())
    total_return = float((1 + result.monthly_returns).prod() - 1)
    print(f"[step] backtest: {n_rebalances} rebalances")
    print(f"       cumulative net L/S return: {total_return:+.2%}")
    print(f"       avg turnover per rebalance: {mean_turnover:.1%}")

    # ---- Metrics ----
    ic_series = compute_ic_per_rebalance(
        result.signal_at_rebalance, result.forward_returns
    )
    scorecard = compute_regime_scorecard(ic_series, result.regime_at_rebalance)
    dsr_result = compute_dsr(result.monthly_returns)

    print("\n" + "-" * 70)
    print("Regime Scorecard (IC per Regime)")
    print("-" * 70)
    print(scorecard.to_string())
    print("-" * 70)
    print(f"Overall mean IC:           {ic_series.mean():+.4f}")
    print(f"Sharpe (annualized, net):  {dsr_result['sharpe_annualized']:+.3f}")
    print(f"PSR ≈ DSR (N=1 trial):     {dsr_result['psr']:.3f}")
    print(f"Monthly observations (T):  {dsr_result['T']}")
    print("-" * 70)

    # ---- Gate ----
    gate = evaluate_gate_g1(dsr_result, scorecard, threshold_dsr=0.5)

    verdict_banner = "PASS ✓" if gate["verdict"] == "PASS" else "FAIL ✗"
    print("\n" + "=" * 70)
    print(f"GATE G1: {verdict_banner}")
    print("=" * 70)
    print(f"  DSR ≥ 0.5:                       {'✓' if gate['dsr_pass'] else '✗'}  "
          f"(observed {gate['observed_dsr_psr']:.3f})")
    print(f"  Positive IC in ≥ 3 of 4 Regimes: {'✓' if gate['regime_pass'] else '✗'}  "
          f"({gate['regime_positive_count']} positive of {gate['regime_total_evaluated']})")
    print("=" * 70)

    # ---- Persistent run log ----
    scorecard_dict = scorecard_to_dict(scorecard)
    run_id = log_run(
        mode="fast" if fast else "full",
        universe_size=int(close_wide.shape[1]),
        params={
            "lookback_months": P.MOMENTUM_LOOKBACK_MONTHS,
            "skip_months": P.MOMENTUM_SKIP_MONTHS,
            "deciles": P.DECILES,
            "cost_bps": P.ROUNDTRIP_COST_BPS,
            "training_start": str(TRAINING_START.date()),
            "training_end": str(TRAINING_END.date()),
            "universe_symbols_requested": len(symbols),
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
    print(f"[log] run persisted to run_log.sqlite as run_id={run_id}")

    # ---- Save outputs ----
    save_json(scorecard_dict, out_dir / "regime_scorecard.json")
    save_json(gate, out_dir / "gate_g1_result.json")

    summary_lines = [
        "v0.1 Momentum Prototype — Backtest Summary",
        "=" * 70,
        f"Training window: {TRAINING_START.date()} → {TRAINING_END.date()}",
        f"Universe symbols requested: {len(symbols)}",
        f"Universe symbols surviving listing filter: {close_wide.shape[1]}",
        f"Rebalances executed: {n_rebalances}",
        f"Cumulative net long-short return: {total_return:+.2%}",
        f"Avg turnover per rebalance: {mean_turnover:.1%}",
        f"Sharpe (annualized, net): {dsr_result['sharpe_annualized']:+.3f}",
        f"PSR ≈ DSR: {dsr_result['psr']:.3f}",
        f"Overall mean IC: {ic_series.mean():+.4f}",
        "",
        "Regime Scorecard:",
        scorecard.to_string(),
        "",
        f"Gate G1 verdict: {gate['verdict']}",
        f"  DSR ≥ 0.5: {'pass' if gate['dsr_pass'] else 'fail'}",
        f"  Positive IC in ≥ 3 of 4 Regimes: {'pass' if gate['regime_pass'] else 'fail'}",
    ]
    (out_dir / "backtest_summary.txt").write_text("\n".join(summary_lines))

    print(f"\nOutputs written to {out_dir}/")
    return 0 if gate["verdict"] == "PASS" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast", action="store_true", help="30 large-caps only")
    args = parser.parse_args()
    sys.exit(main(fast=args.fast))
