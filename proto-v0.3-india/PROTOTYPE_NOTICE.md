# proto-v0.3-india — Nifty 500 Mean Reversion with Regime Gate

**Status**: In development — G1/G2 evaluation pending  
**Universe**: Nifty 500 (India), ~50-stock hardcoded fallback  
**Index proxy**: ^NSEI (Nifty 50)  
**Training window**: 2017-01-01 → 2023-12-31  
**Data window**: 2015-01-01 → 2023-12-31 (2yr warmup for signal lookbacks)  
**Held-out**: 2024-01-01 onward — LOCKED until G2 passes  

---

## What changed from v0.1

**v0.1** (India, passedG3): ran mean_reversion on Nifty 500 without regime
conditioning. Training Sharpe was acceptable but the regime scorecard in v0.1
already showed weaker IC in LOW_VOL_UP_TREND months — a warning sign.

**v0.3** (this prototype): adds a hard regime gate per **ADR-0007**. When the
market is in LOW_VOL_UP_TREND at a rebalance date, we record 0 return and skip
position construction entirely. No partial position, no soft reduction — a hard
zero. The gate is set pre-backtest and not tuned.

The motivation comes from the US v0.2 post-mortem: the 2024-2026 AI bull market
was 62% LOW_VOL_UP_TREND and produced IC = -0.066 (mean_reversion shorted recent
winners = mega-cap AI names and went long recent losers). The signal correctly
identified the strongest stocks in training — and then those stocks kept winning.
Hard gating removes this catastrophic regime before it compounds.

---

## Gate architecture

- **G1**: per-Agent DSR ≥ 0.5 + positive IC in ≥ 3 of 4 eligible regimes  
- **G2**: meta_ensemble Sharpe ≥ 1.0, PSR ≥ 0.90, MaxDD ≤ 25%  
- **G3**: held-out DSR ≥ 60% of training DSR, MaxDD ≤ 25%  

G3 held-out (`run_held_out.py`) should be written and run only after G2 passes.

---

## Signal registry

| Signal | Status | Notes |
|---|---|---|
| mean_reversion (20d) | Active | Only signal in AGENTS |

No sector_neutral_mr — India's sector data via yfinance is lower quality than
S&P 500 GICS data from Wikipedia. May revisit with a sector classification source.

---

## Cost model

Zerodha equity delivery: ~20 bps roundtrip (brokerage ≈0.1%, STT ≈0.025%,
SEBI + exchange + stamp duty ≈ remainder). Higher than US but Nifty 500
cross-sectional dispersion is also larger, so net edge can still be positive.

---

## Regime gate parameters (fixed before G1 run)

```python
SKIP_REGIMES = frozenset({"LOW_VOL_UP_TREND"})
```

This is set in `run.py` and passed to `run_meta_ensemble_backtest`. Do not
change after the first G1 run — any parameter change resets the trial count.
