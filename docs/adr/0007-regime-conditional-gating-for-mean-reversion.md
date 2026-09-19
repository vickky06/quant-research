# ADR-0007: Regime-conditional gating for mean_reversion strategies

**Status**: Accepted
**Date**: 2026-09-19
**Supersedes**: nothing
**Superseded by**: nothing

## Context

Both India v0.1 and US v0.2 held-out evaluations showed mean_reversion failing in
LOW_VOL_UP_TREND regimes. The data is consistent across both markets:

**India (proto-v0.1, held-out 2024-2026)**:
- mean_reversion held-out mean IC: -0.045
- Held-out period: predominantly UP_TREND (India bull market continued in 2024)

**US (proto-v0.2, held-out 2024-2026)**:
- mean_reversion held-out mean IC: -0.066
- Held-out regime distribution: 62% LOW_VOL_UP_TREND, 34% HIGH_VOL_UP_TREND

**US training scorecard by regime** (where the signal WORKS):
| Regime | Mean IC | n |
|---|---|---|
| HIGH_VOL_DOWN_TREND | +0.057 | 24 |
| HIGH_VOL_UP_TREND | +0.034 | 41 |
| LOW_VOL_DOWN_TREND | +0.040 | 1 (insufficient) |
| LOW_VOL_UP_TREND | **-0.010** | 41 |

Mean reversion is reliable in HIGH_VOL regimes and anti-predictive in LOW_VOL_UP_TREND.

## Decision

Introduce **regime-conditional hard gating** for mean_reversion strategies:

- In HIGH_VOL months (HIGH_VOL_DOWN_TREND or HIGH_VOL_UP_TREND): trade normally
- In LOW_VOL_UP_TREND months: **flat** — no portfolio, 0 return for that month
- In LOW_VOL_DOWN_TREND months: trade (too few observations to characterize; no evidence against)

Implementation: `skip_regimes = frozenset({"LOW_VOL_UP_TREND"})` parameter in
`run_meta_ensemble_backtest`. When regime at rebalance date is in `skip_regimes`,
record return = 0.0 and skip position construction.

**Expected effects**:
- Training window: ~38% of months are LOW_VOL_UP_TREND → ~66 tradeable months out of 107
- Fewer observations reduces absolute DSR (shorter T) but IC improves (hostile months removed)
- Held-out: if 2024-2026 is 62% LOW_VOL_UP_TREND → ~11 tradeable months → very few observations
  for G3. This is acceptable — the gate explicitly accepts lower held-out power in exchange
  for removing catastrophic anti-market trades.

## Trade-offs

**Pro**: Removes the -2.5 Sharpe months (held-out failure was driven by 18 LOW_VOL_UP_TREND
months with IC -0.041). Even if gated periods have 0 return, eliminating -67% drawdowns is
worth the reduction in sample size.

**Con**: Reduces backtest sample size. DSR will not improve proportionally with IC because T
drops from 107 to ~66 monthly observations. The strategy becomes regime-timing dependent.

**Alternative rejected**: Soft gating (position size reduction in hostile regimes). Rejected
because the evidence is too strong — IC is negative in LOW_VOL_UP_TREND, not merely weak.
A fractional position would still lose money. Hard gate is cleaner.

## Constraints

- Regime gate must use ONLY data available at rebalance time (no look-ahead)
- Regime is computed from index returns up to rebalance date — this is satisfied by the
  existing `compute_regime()` function which uses rolling windows on historical data
- Gate parameters (which regimes to skip) must be set before G3 evaluation and not
  changed afterward (one-shot constraint applies)
