# ADR-0006: US large-cap pure-price L/S signals have a structural Sharpe ceiling

**Status**: Accepted
**Date**: 2026-09-19
**Supersedes**: nothing
**Superseded by**: nothing

## Context

proto-v0.2-us evaluated 6 pure-price signals on S&P 500 (453 stocks, 2015-2023 training):

| Signal | G1 | DSR | Sharpe |
|---|---|---|---|
| momentum (12-1) | FAIL | 0.270 | -0.20 |
| return_smoothness | FAIL | 0.146 | -0.35 |
| low_vol (BAB) | FAIL | 0.035 | -0.60 |
| max_lottery (MAX) | FAIL | 0.025 | -0.65 |
| mean_reversion (20d) | PASS | 0.793 | +0.284 |
| sector_neutral_mr | PASS | 0.684 | +0.162 |
| meta_ensemble (best) | — | 0.852 | +0.356 |

Gate G2 (Sharpe ≥ 1.0) was not reached with any combination. The four failing
signals share a common root cause:

**US large-cap tech dominance 2015-2023** creates a systematic short-tech tilt in
any cross-sectional signal whose ranking window is long enough to capture the
sector trend. Signals that long low-vol/smooth/non-tech names and short high-vol/
momentum/tech names bled on the short leg throughout the training window.

Mean reversion works because its 20-day window is below the regime's correlation
length — within-month oscillations are independent of the sector-level trend.
But its individual Sharpe (~0.3) caps the ensemble at ~0.35, short of G2.

The G3 held-out confirmed the structural issue: 2024-2026 was 62% LOW_VOL_UP_TREND
(AI bull market), exactly the regime hostile to mean reversion. Held-out Sharpe: -2.51.

## Decision

1. **Retire for S&P 500**: momentum, return_smoothness, low_vol (BAB), max_lottery
   are all structurally broken on US large-caps for the foreseeable AI-driven regime.
   Do not re-evaluate these on S&P 500 without a structural market-regime change.

2. **Mean_reversion cap acknowledged**: S&P 500 mean_reversion has a Sharpe ceiling
   of ~0.35 (training) due to the tech-dominance suppression of cross-sectional
   dispersion. G2 (Sharpe ≥ 1.0) cannot be achieved on this universe with pure-price
   signals alone.

3. **Regime-conditioning required**: any future US large-cap strategy must condition
   on regime and trade only in HIGH_VOL months (where mean_reversion IC is positive)
   or must source a fundamentals-based signal that survives LOW_VOL_UP_TREND.

## Alternatives considered

- **Sector-neutral mean reversion**: implemented and tested. Reduces MaxDD to -19.5%
  and marginally improves G2 results (MaxDD passes, Sharpe/DSR still fail). Not a
  path to G2 on its own; useful as a secondary signal.

- **Historical fundamentals (Novy-Marx quality)**: expected to work across regimes.
  Blocked by data availability — yfinance provides ~4 years of financials, insufficient
  for 2015-2023 training window. Deferred to future iteration with EDGAR pipeline.

- **Russell 2000 pivot**: 2000 small-cap stocks, less tech concentration. Expected
  to work for both momentum and mean_reversion. Pursued in proto-v0.3-r2k.
