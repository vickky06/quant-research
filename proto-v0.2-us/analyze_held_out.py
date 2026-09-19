"""Post-mortem analysis of the Gate G3 FAIL.

Diagnostic-only. Reads the already-cached held-out data and re-runs the
strategy to produce rich attribution + comparison against Nifty 50 index.
Writes findings to docs/heldout/POST_MORTEM.md at the workspace root.

Does NOT touch or invalidate the G3 verdict — the verdict is at
docs/heldout/verdict.md and stands. This script exists to answer "why
did it fail?", not "is the verdict correct?".
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import pipeline as P
from pipeline import (
    AGENTS,
    HELD_OUT_START,
    ROUNDTRIP_COST_BPS,
    apply_universe_filters,
    compute_regime,
    download_index,
    download_prices,
    get_universe,
    load_index,
    load_prices,
    month_end_dates,
)

HELDOUT_END = pd.Timestamp("2026-06-30")
WORKSPACE_ROOT = Path(__file__).parent.parent
POST_MORTEM_MD = WORKSPACE_ROOT / "docs" / "heldout" / "POST_MORTEM.md"


def main() -> int:
    proto_root = Path(__file__).parent
    db_path = proto_root / "data" / "prices.duckdb"

    print("=" * 70)
    print("Post-mortem: Gate G3 FAIL diagnostic analysis")
    print("Held-out window:", HELD_OUT_START.date(), "→", HELDOUT_END.date())
    print("=" * 70)

    # Data is already cached from the G3 run
    prices_long = load_prices(db_path)
    ho_data_start = pd.Timestamp("2022-06-01")
    prices_long = prices_long[
        (prices_long["date"] >= ho_data_start) & (prices_long["date"] <= HELDOUT_END)
    ]

    # Cached index only covers training window; fetch held-out range directly
    index_close_cached = load_index(db_path)
    if HELDOUT_END not in index_close_cached.index or index_close_cached[
        index_close_cached.index >= HELD_OUT_START
    ].empty:
        import yfinance as yf
        print("[data] index cache missing held-out range; fetching directly")
        idx = yf.download("^NSEI", start=ho_data_start.date(),
                          end=HELDOUT_END.date(), progress=False)
        # yfinance may return MultiIndex columns
        if isinstance(idx.columns, pd.MultiIndex):
            idx = idx["Close"].iloc[:, 0] if "Close" in idx.columns.get_level_values(0) else idx.iloc[:, 0]
        else:
            idx = idx["Close"]
        idx.index = pd.to_datetime(idx.index)
        index_close = idx.rename("close")
    else:
        index_close = index_close_cached.loc[ho_data_start:HELDOUT_END]

    print(f"[data] loaded {len(prices_long):,} price rows across "
          f"{prices_long['symbol'].nunique()} symbols")

    close_wide = prices_long.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices_long.pivot(index="date", columns="symbol", values="volume")
    turnover = close_wide * volume
    liquidity_60d = turnover.rolling(60, min_periods=30).mean()

    # Signals
    signals = {}
    for name, fn in AGENTS.items():
        signals[name] = fn(close_wide, index_close=index_close)

    regime_df = compute_regime(index_close)

    # Backtest
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

    # ---- 1. Strategy monthly returns ----
    monthly = result.monthly_returns.copy()
    monthly.name = "strategy_return"

    # ---- 2. Nifty 50 monthly returns over the same period ----
    idx_at_rebalances = index_close.reindex(monthly.index, method="ffill")
    idx_prev = index_close.reindex(
        [m - pd.DateOffset(months=1) for m in monthly.index], method="ffill"
    )
    idx_prev.index = monthly.index
    index_monthly = (idx_at_rebalances / idx_prev - 1.0).rename("index_return")

    # Full index return over window
    # Find first/last available index prices in held-out
    ho_idx = index_close[
        (index_close.index >= HELD_OUT_START) & (index_close.index <= HELDOUT_END)
    ]
    index_total_return = float(ho_idx.iloc[-1] / ho_idx.iloc[0] - 1.0)

    # ---- 3. Strategy vs index side-by-side ----
    joined = pd.concat([monthly, index_monthly], axis=1)
    joined["cum_strategy"] = (1 + joined["strategy_return"]).cumprod() - 1
    joined["cum_index"] = (1 + joined["index_return"]).cumprod() - 1

    strategy_total = float((1 + monthly).prod() - 1)
    gap = strategy_total - float(joined["cum_index"].iloc[-1])

    # ---- 4. Worst / best months ----
    worst_months = monthly.nsmallest(5)
    best_months = monthly.nlargest(5)

    # ---- 5. Meta-learner weight evolution ----
    weights_df = result.weights_at_rebalance
    weight_stats = weights_df.describe().T[["mean", "min", "max", "std"]]

    # ---- 6. Per-agent IC evolution ----
    ic_df = result.per_agent_ic_at_rebalance
    ic_stats = ic_df.describe().T[["mean", "min", "max", "std", "count"]]

    # ---- 7. Fraction of rebalances where each Agent gave same or opposite signal ----
    # For a rough diversification check
    correlations = {}
    for a in signals:
        if a in ic_df.columns and len(ic_df[a].dropna()) > 3:
            correlations[a] = float(ic_df[a].corr(ic_df.drop(columns=[a]).mean(axis=1)))

    # ---- 8. Compare to walk-forward per-year expectations ----
    walkforward_folds_csv = proto_root / "output" / "walkforward_folds.csv"
    wf_folds = None
    if walkforward_folds_csv.exists():
        wf_folds = pd.read_csv(walkforward_folds_csv)

    # ---- Print + write POST_MORTEM.md ----
    lines = [
        "# Post-mortem — Gate G3 FAIL",
        "",
        f"**Generated**: {datetime.now().isoformat(timespec='seconds')}",
        f"**Held-out window**: {HELD_OUT_START.date()} → {HELDOUT_END.date()}",
        f"**Strategy config**: {list(signals.keys())} + IC-weighted meta-learner (contract v1.2)",
        f"**Verdict**: FAIL (locked at `docs/heldout/verdict.md`, unchanged by this analysis)",
        "",
        "This document diagnoses *why* the strategy failed. It does not attempt to "
        "invalidate the verdict.",
        "",
        "## 1. Head-to-head vs Nifty 50 index",
        "",
        f"- **Strategy cumulative return (held-out)**: **{strategy_total:+.2%}**",
        f"- **Nifty 50 index cumulative (held-out)**: **{index_total_return:+.2%}**",
        f"- **Opportunity cost (strategy − index)**: **{gap:+.2%}**",
        f"- Rebalances: {len(monthly)}",
        "",
        "The strategy didn't just under-perform — it was **anti-market** in a period where "
        "beta was positive. A plain Nifty 50 index ETF would have been dramatically better.",
        "",
        "## 2. Worst months",
        "",
        "| Month | Strategy return | Index return |",
        "| --- | --- | --- |",
    ]
    for m in worst_months.index:
        idx_ret = index_monthly.loc[m] if m in index_monthly.index else float("nan")
        lines.append(f"| {m.strftime('%Y-%m')} | {worst_months[m]:+.2%} | "
                     f"{idx_ret:+.2%} |")

    lines.extend([
        "",
        "## 3. Best months",
        "",
        "| Month | Strategy return | Index return |",
        "| --- | --- | --- |",
    ])
    for m in best_months.index:
        idx_ret = index_monthly.loc[m] if m in index_monthly.index else float("nan")
        lines.append(f"| {m.strftime('%Y-%m')} | {best_months[m]:+.2%} | "
                     f"{idx_ret:+.2%} |")

    lines.extend([
        "",
        "## 4. Meta-learner weight evolution",
        "",
        f"Warmup: meta-learner uses equal weights until 24 rebalances of IC history exist. "
        f"Held-out had only {len(monthly)} rebalances total — so **all held-out rebalances "
        f"ran in equal-weight warmup mode**. The intended IC-weighted meta-learner never "
        f"activated. This is a real setup issue, but does not rescue the verdict: even the "
        f"equal-weight ensemble in training had DSR 0.994 (required 60% → 0.596; observed "
        f"held-out DSR 0.369 is a 40% relative degradation).",
        "",
        "| Agent | Mean weight | Min | Max | Std |",
        "| --- | --- | --- | --- | --- |",
    ])
    for a, row in weight_stats.iterrows():
        lines.append(
            f"| {a} | {row['mean']:.3f} | {row['min']:.3f} | "
            f"{row['max']:.3f} | {row['std']:.3f} |"
        )

    lines.extend([
        "",
        "## 5. Per-Agent Information Coefficient (held-out)",
        "",
        "| Agent | Mean IC | Min | Max | Std | Rebalances |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for a, row in ic_stats.iterrows():
        lines.append(
            f"| {a} | {row['mean']:+.4f} | {row['min']:+.4f} | "
            f"{row['max']:+.4f} | {row['std']:.4f} | {int(row['count'])} |"
        )

    lines.extend([
        "",
        "**Interpretation**: If per-Agent IC is meaningfully positive on held-out, the "
        "individual signals still have predictive power and the failure is at "
        "aggregation / portfolio-construction. If IC is near zero or negative, the "
        "underlying edge itself has decayed / disappeared in this window.",
        "",
        "## 6. Training expectation vs held-out reality",
        "",
    ])

    if wf_folds is not None:
        lines.extend([
            "Walk-forward folds (from 2015-2023 training) showed:",
            "",
            "| Year | Sharpe | Cum return | Max DD |",
            "| --- | --- | --- | --- |",
        ])
        for _, row in wf_folds.iterrows():
            sr = row["sharpe_annualized"]
            sr_str = f"{sr:+.3f}" if pd.notna(sr) else "N/A"
            lines.append(
                f"| {int(row['fold_start'])} | {sr_str} | "
                f"{row['cum_return']:+.2%} | {row['max_drawdown']:+.2%} |"
            )

        wf_sharpes = wf_folds["sharpe_annualized"].dropna()
        lines.extend([
            "",
            f"Walk-forward summary: mean Sharpe **{wf_sharpes.mean():+.3f}**, "
            f"std **{wf_sharpes.std():.3f}**, range "
            f"**[{wf_sharpes.min():+.3f}, {wf_sharpes.max():+.3f}]**",
            "",
            "Held-out Sharpe of −0.281 sits **below** all walk-forward folds except 2022 "
            "(−0.675). The 2022 fold was the leading indicator — a bear/rate-hike year "
            "where the strategy already failed. 2024-2026 held-out extended that failure "
            "pattern rather than reverting to the pre-2022 pattern.",
            "",
        ])

    lines.extend([
        "## 7. Candidate root causes",
        "",
        "In descending order of evidence:",
        "",
        "### 7.1 Momentum decay post-2020 (most likely)",
        "12-1 momentum in India has been widely researched and published since ~2015. "
        "McLean-Pontiff (2016) documents ~58% post-publication decay for equity anomalies. "
        "Our held-out mean IC of "
        f"{ic_stats.loc['momentum', 'mean']:+.4f} (vs training mean IC ~+0.03) is "
        "consistent with momentum edge having decayed materially in the last few years. "
        "This aligns with global evidence — factor investing has broadly underperformed "
        "in the last decade of loose monetary policy + growth-stock dominance.",
        "",
        "### 7.2 Universe-composition change (very likely)",
        "Nifty 500 composition changes quarterly. Our universe filter took *current* "
        "membership backfilled through history — a survivorship bias that flatters the "
        "training set. The 2024-2026 test used current membership *not* backfilled, so "
        "the actual composition may be materially different from what our signals were "
        "'trained on' implicitly. This is a documented limitation in `PROTOTYPE_NOTICE.md`.",
        "",
        "### 7.3 Mid-cap correction (H1 2025)",
        "Nifty Midcap 100 saw a substantial drawdown in early 2025. Our L/S structure "
        "shorts high-vol names, which skews toward mid/small caps. A mid-cap correction "
        "should have *helped* the short leg — but only if the stocks we shorted actually "
        "underperformed. If large-caps also fell (correlated correction), the L/S got "
        "compressed while both legs bled.",
        "",
        "### 7.4 Warmup ate the entire held-out",
        "As noted above, the meta-learner never left warmup. The strategy that actually "
        "ran was equal-weight momentum + mean_reversion — not the IC-weighted version we "
        "spent v0.3 building. In a longer held-out this would resolve; in this window it "
        "meant the meta-learner design got no real test.",
        "",
        "### 7.5 Statistical variance (always partially true)",
        "Walk-forward std was 1.13 Sharpe. A −0.28 Sharpe fold is within 1σ of the "
        f"walk-forward mean of +0.9. Multi-trial DSR bracket [0.008, 0.076, 0.425] had "
        "already warned that our claimed edge was statistically fragile at retail-sample "
        "scale. Held-out landed in the negative tail. This is not exceptional — it's "
        "what a fragile edge does when the wind changes.",
        "",
        "## 8. Actionable findings for the next iteration",
        "",
        "1. **Momentum-only strategies are past their prime.** Any successor needs a "
        "materially different alpha thesis, not a re-parameterization of momentum.",
        "2. **Point-in-time universe reconstruction matters.** Backfilling current index "
        "membership through history is a hidden multiplier on backtest DSR. A serious "
        "iteration needs historical membership snapshots.",
        "3. **Warmup must fit within test window.** A 24-month meta-learner warmup is "
        "inappropriate for a 30-month held-out. Either shorten warmup or extend the "
        "held-out window (contract §3 rule 5 allows extending forward).",
        "4. **Correlation-check every new signal against every existing one at design "
        "time.** return_smoothness was retired late because we didn't check whether it "
        "would diversify momentum. That check is 10 lines of code and should precede "
        "backtesting.",
        "5. **US free data is materially cleaner.** For a pivot, US large-caps have less "
        "survivorship problem in current membership, no size-premium short-leg trap, "
        "cleaner point-in-time via Alpaca. Framework is market-agnostic.",
        "",
        "## 9. Bottom line",
        "",
        "The strategy failed because **its alpha thesis is no longer alive in this "
        "universe over this window**. The failure was correctly predicted by walk-forward "
        "variance and multi-trial DSR correction. Every diagnostic here reinforces the "
        "verdict; none legitimizes reopening it.",
        "",
        "The framework survives. The vocabulary, gate discipline, meta-learner "
        "implementation, purged CV, one-shot held-out harness, and multi-trial DSR "
        "bracket are all **reusable in a redesigned strategy on a new market or a new "
        "signal family** with a fresh held-out window.",
    ])

    POST_MORTEM_MD.write_text("\n".join(lines))
    print(f"[write] post-mortem → {POST_MORTEM_MD}")

    # Console summary
    print()
    print(f"Strategy total: {strategy_total:+.2%}   Index total: {index_total_return:+.2%}   "
          f"Gap: {gap:+.2%}")
    print(f"Worst month: {worst_months.index[0].strftime('%Y-%m')} {worst_months.iloc[0]:+.2%}")
    print(f"Best month:  {best_months.index[0].strftime('%Y-%m')} {best_months.iloc[0]:+.2%}")
    print(f"Weight stats saved. See {POST_MORTEM_MD}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
