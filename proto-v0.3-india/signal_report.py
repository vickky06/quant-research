"""On-demand signal report — run anytime to see current ranked positions.

Loads prices from DuckDB, detects current regime, computes all three signals
with regime-conditional weights, and prints a ranked long/short list.

Usage:
    python signal_report.py                 # full report, daily bars
    python signal_report.py --top 30        # show top/bottom 30 instead of 20
    python signal_report.py --interval 1h   # use hourly bars (untrained territory)
    python signal_report.py --fast          # 50-ticker subset (quick)
    python signal_report.py --save          # also write report to output/

Run data_refresh.py first to ensure prices are up to date.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import pipeline as P
from pipeline import (
    AGENTS,
    ROUNDTRIP_COST_BPS,
    TRAINING_END,
    TRAINING_START,
    compute_regime,
    get_sector_map,
    get_universe,
    load_index,
    load_prices,
)
from run import REGIME_SIGNAL_WEIGHTS, SKIP_REGIMES

DB_PATH = Path(__file__).parent / "data" / "prices.duckdb"
OUTPUT_DIR = Path(__file__).parent / "output"

TRAINED_INTERVAL = "1d"


def _blend_signals(
    signals: dict[str, pd.DataFrame],
    weights: dict[str, float],
    date: pd.Timestamp,
    eligible: list[str],
) -> pd.Series:
    """Blend signals at a single date using given weights. Returns ranked score."""
    weighted = pd.Series(0.0, index=eligible)
    mass = pd.Series(0.0, index=eligible)
    for name, sig_df in signals.items():
        w = weights.get(name, 0.0)
        if w == 0.0 or date not in sig_df.index:
            continue
        s = sig_df.loc[date, eligible].dropna()
        weighted.loc[s.index] += s * w
        mass.loc[s.index] += w
    with np.errstate(divide="ignore", invalid="ignore"):
        score = (weighted / mass).replace([np.inf, -np.inf], np.nan).dropna()
    return score.rank(pct=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=20, help="Positions per side")
    parser.add_argument("--interval", default="1d",
                        choices=["1d", "1h", "30m", "15m", "5m", "1m"])
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--save", action="store_true", help="Write report to output/")
    args = parser.parse_args()

    if args.interval != TRAINED_INTERVAL:
        print(f"⚠️  interval={args.interval}: signals were trained on {TRAINED_INTERVAL} bars.")
        print(f"   Results are indicative only — not validated at this frequency.")
        print()

    symbols = get_universe(fast=args.fast)
    sector_map = get_sector_map()

    prices_long = load_prices(DB_PATH)
    index_close = load_index(DB_PATH)

    if prices_long.empty or index_close.empty:
        print("[fatal] no data in DB — run data_refresh.py first")
        return

    # Use last 252 trading days for signal computation (enough for all lookbacks)
    cutoff = prices_long["date"].max() - pd.Timedelta(days=400)
    prices_long = prices_long[prices_long["date"] >= cutoff]
    index_close = index_close[index_close.index >= cutoff]

    close_wide = prices_long.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices_long.pivot(index="date", columns="symbol", values="volume")
    turnover = close_wide * volume
    liquidity_60d = turnover.rolling(60, min_periods=20).mean()

    # Latest available date
    latest_date = close_wide.index.max()

    # Regime
    regime_df = compute_regime(index_close)
    regime_label = "UNKNOWN"
    if latest_date in regime_df.index:
        regime_label = regime_df.loc[latest_date, "regime"]
    else:
        # Use last available regime
        valid = regime_df.dropna(subset=["regime"])
        if not valid.empty:
            regime_label = valid.iloc[-1]["regime"]

    # Signal weights for current regime
    weights = REGIME_SIGNAL_WEIGHTS.get(regime_label, {})
    if not weights:
        # fallback: equal weight
        weights = {name: 1.0 / len(AGENTS) for name in AGENTS}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}

    # Compute signals
    signals = {}
    for name, fn in AGENTS.items():
        signals[name] = fn(close_wide, index_close=index_close, sector_map=sector_map)

    # Eligible stocks at latest date
    eligible = P.per_rebalance_universe(close_wide, liquidity_60d, latest_date)
    if len(eligible) < 10:
        # Relax liquidity filter for report — use all stocks with recent data
        eligible = close_wide.loc[latest_date].dropna().index.tolist()

    ranked = _blend_signals(signals, weights, latest_date, eligible)
    if ranked.empty:
        print("[fatal] no signal scores computed — check price data")
        return

    top_cut = 1.0 - 1.0 / 10
    bot_cut = 1.0 / 10
    longs = ranked[ranked >= top_cut].sort_values(ascending=False)
    shorts = ranked[ranked <= bot_cut].sort_values(ascending=True)

    n = args.top

    # ── Print report ──────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print()
    print("=" * 62)
    print(f"  SIGNAL REPORT — India v0.3          {ts}")
    print("=" * 62)
    print(f"  Data as of:   {latest_date.date()}")
    print(f"  Universe:     {len(eligible)} stocks")
    print(f"  Interval:     {args.interval}")
    print()
    print(f"  Current regime:  {regime_label}")
    print(f"  Signal weights:")
    for name, w in sorted(weights.items(), key=lambda x: -x[1]):
        bar = "█" * int(w * 20)
        print(f"    {name:20s}  {w:5.1%}  {bar}")
    print()

    # Per-signal IC for context
    print(f"  Per-signal scores at {latest_date.date()}:")
    for name, sig_df in signals.items():
        if latest_date in sig_df.index:
            vals = sig_df.loc[latest_date, eligible].dropna()
            print(f"    {name:20s}  mean={vals.mean():.3f}  std={vals.std():.3f}  n={len(vals)}")
    print()

    print(f"  ── LONG  (top {n} by composite score) ──")
    print(f"  {'Rank':>4}  {'Symbol':<20}  {'Score':>6}  {'Sector':<25}")
    print("  " + "-" * 58)
    for rank, (sym, score) in enumerate(longs.head(n).items(), 1):
        sector = sector_map.get(sym, "—")[:24]
        print(f"  {rank:>4}  {sym:<20}  {score:.4f}  {sector:<25}")

    print()
    print(f"  ── SHORT (bottom {n} by composite score) ──")
    print(f"  {'Rank':>4}  {'Symbol':<20}  {'Score':>6}  {'Sector':<25}")
    print("  " + "-" * 58)
    for rank, (sym, score) in enumerate(shorts.head(n).items(), 1):
        sector = sector_map.get(sym, "—")[:24]
        print(f"  {rank:>4}  {sym:<20}  {score:.4f}  {sector:<25}")

    print()
    print(f"  Cost model: {ROUNDTRIP_COST_BPS} bps roundtrip")
    if SKIP_REGIMES and regime_label in SKIP_REGIMES:
        print(f"  ⚠️  Regime {regime_label} is in skip list — strategy would be FLAT")
    print("=" * 62)
    print()

    if args.save:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        fname = OUTPUT_DIR / f"signal_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        payload = {
            "timestamp": ts,
            "data_date": str(latest_date.date()),
            "regime": regime_label,
            "weights": weights,
            "longs": longs.head(n).to_dict(),
            "shorts": shorts.head(n).to_dict(),
            "universe_size": len(eligible),
            "interval": args.interval,
        }
        fname.write_text(json.dumps(payload, indent=2))
        print(f"  Saved → {fname}")


if __name__ == "__main__":
    main()
