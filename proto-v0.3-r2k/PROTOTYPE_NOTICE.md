# proto-v0.3-r2k — S&P SmallCap 600 Prototype

**Status**: In evaluation (G1 pending)
**Universe**: S&P SmallCap 600 (Wikipedia scraped, ~600 tickers)
**Index proxy**: ^RUT (Russell 2000)
**Training window**: 2017-01-01 → 2023-12-31 (7 years)
**Held-out window**: 2024-01-01 → 2026-06-30 (LOCKED — untouched until G2 passes)
**Signals**: momentum (12-1) + mean_reversion (20d)
**Cost model**: 10 bps roundtrip (wider than large-cap; small-cap spread assumption)
**Liquidity floor**: $1M avg daily turnover (small-cap appropriate)
**Price floor**: $1.00 (excludes penny stocks)

---

## Thesis

S&P 500 large-caps have a ~0.35 Sharpe ceiling for pure-price L/S strategies
(ADR-0006). The root cause: tech-sector dominance 2015-2023 causes any
cross-sectional ranking signal to systematically short high-momentum/high-vol
tech names, bleeding on the short leg throughout the bull market.

S&P SmallCap 600 / Russell 2000 small-caps differ in three key ways:

1. **Less tech concentration**: Small-caps span Industrials, Financials, Consumer,
   Healthcare more evenly. The AI/FAANG dominance that broke large-cap signals
   has less weight in small-cap indices.

2. **Momentum literature support**: Fama-French (1993, 2012) and subsequent work
   document that momentum works in small-caps even in periods where it fails in
   large-caps. The size premium and momentum premium interact positively.

3. **More idiosyncratic behavior**: 600 names with less correlated returns than
   S&P 500 mega-caps → better signal-to-noise for cross-sectional strategies.

## Key difference from proto-v0.2-us

- `AGENTS = {"momentum": ..., "mean_reversion": ...}` — momentum re-enabled
  (was retired in v0.2-us: Sharpe -0.20 on S&P 500 large-caps)
- `skip_regimes=None` by default — evaluate unconditionally first; R2K regime
  behavior may differ from large-caps (hypothesis: momentum works across regimes
  in small-caps, unlike large-cap mean_reversion which fails in LOW_VOL_UP_TREND)
- The `skip_regimes` parameter exists in `run_meta_ensemble_backtest` and can be
  activated post-G1 analysis if regime diagnostics warrant it

## Gate architecture

- **G1** (this evaluation): Per-signal DSR ≥ 0.5 + IC positive in ≥ 3-of-4 regimes
- **G2** (after G1 passes): Meta-ensemble Sharpe ≥ 1.0 + PSR ≥ 0.90 + MaxDD ≤ 25%
- **G3** (one-shot held-out): Held-out DSR ≥ 60% of training + MaxDD ≤ 25%

## Expected DSR ceiling

Hypothesis: 1.0+ (vs. ~0.35 for S&P 500 large-caps). If momentum passes G1
on small-caps as expected from literature, the meta-ensemble can combine two
anti-correlated signals (momentum and mean_reversion are naturally negatively
correlated) for further Sharpe improvement.

---

## Lineage

Adapted from proto-v0.2-us (S&P 500). Key architectural decisions retained:
- IC-weighted Meta-Learner with shrinkage (Contract §6)
- 2×2 regime detection (Vol × Trend) on index returns
- Purged walk-forward validation with multi-trial DSR bracket
- DuckDB price caching with date-range-aware cache check (ADR-0006 bug fix)
- One-shot G3 evaluation lock (Contract §3)

Lessons incorporated:
- ADR-0006: Large-cap structural ceiling; small-cap pivot justified
- ADR-0007: `skip_regimes` parameter present for future regime-conditional gating
- Contract v1.3 §5: corrected G2 thresholds (Sharpe ≥ 1.0, PSR ≥ 0.90)
