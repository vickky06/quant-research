# ADR-0008: Retire S&P SmallCap 600 prototype — pure-price signals not viable

**Status**: Accepted
**Date**: 2026-09-19
**Supersedes**: nothing
**Superseded by**: nothing

## Context

proto-v0.3-r2k evaluated momentum (12-1) and mean_reversion (20d) on the
S&P SmallCap 600 (482 qualifying symbols, 2017-2023 training window, ^RUT
regime proxy, 10 bps roundtrip cost).

Full-universe results:

| Signal | G1 | DSR | Sharpe | MaxDD |
|---|---|---|---|---|
| momentum (12-1) | FAIL | 0.122 | -0.417 | -59.59% |
| mean_reversion (20d) | FAIL | 0.807 | +0.300 | -18.94% |
| meta_ensemble | PASS | 0.746 | +0.242 | -27.95% |

**Multi-trial DSR bracket (meta_ensemble)**:
| N | SR_null_max | DSR |
|---|---|---|
| 3 | +0.992 | 0.014 |
| 5 | +1.388 | 0.000 |
| 8 | +1.698 | 0.000 |

DSR at N=5 = 0.000. After correcting for the number of signal families
tested (momentum, mean_reversion, and the combinations evaluated before
retiring them), the observed mean walk-forward Sharpe (+0.362) falls
entirely within the null distribution. There is no statistically
detectable edge.

## Root causes

**Momentum failure**: The 12-1 momentum signal on S&P 600 produced
Sharpe -0.417 (DSR 0.122) over 2015-2023. The training period includes:
- 2018: late-cycle factor reversal where momentum crowding unwound
- 2020: COVID crash caused extreme momentum reversal (March-June 2020)
- 2022: growth/momentum collapse (rate hike cycle)

All three events are hostile to a standard 12-1 cross-sectional momentum
signal. The 2015-2023 window is structurally unfavorable for small-cap
momentum — the literature documenting small-cap momentum alpha primarily
covers pre-2010 data.

**Mean_reversion regime breakdown**:

| Regime | Mean IC | n |
|---|---|---|
| HIGH_VOL_DOWN_TREND | +0.0615 | 33 (40%) |
| HIGH_VOL_UP_TREND | **-0.0166** | 19 (23%) |
| LOW_VOL_DOWN_TREND | -0.0259 | 6 (insufficient) |
| LOW_VOL_UP_TREND | **-0.0041** | 25 (30%) |

Mean_reversion only works in HIGH_VOL_DOWN_TREND (40% of months). In both
UP_TREND regimes (53% of months combined), IC is negative or flat. This is
the same structural issue as US v0.2 (ADR-0006) but more extreme: small-cap
stocks in UP_TREND regimes exhibit stronger momentum behavior, making
mean_reversion anti-predictive.

**Fast-mode artifact**: The initial 50-ticker fast-mode run showed DSR 0.971
for mean_reversion — a strongly misleading result. The fallback ticker list
was survivorship-biased toward stable, liquid mid-caps that happen to exhibit
cleaner mean-reversion. The full 482-ticker universe (including recently-added
S&P 600 components, volatile names, and sector diversity) reduces IC from
+0.030 to +0.018 and flip the regime scorecard.

## Decision

Retire proto-v0.3-r2k. Do not proceed to G2 or G3.

1. **Momentum on S&P 600 (2015-2023)**: structurally broken. The
   training window is dominated by three momentum-hostile macro events.
   Do not re-evaluate without a different training window or a
   transaction-cost-aware implementation (momentum on small-caps requires
   much lower turnover to survive 10 bps costs).

2. **Mean_reversion on S&P 600**: regime-dependent. Only works in
   HIGH_VOL_DOWN_TREND (40% of months). With hard gating, there would be
   ~33 tradeable months — too few for a statistically meaningful G3
   evaluation. The multi-trial DSR = 0.000 makes this unambiguous.

3. **Small-cap universe pivot**: not the right fix for the problem. The
   US large-cap ceiling (ADR-0006) is a tech-sector contamination issue.
   Small-caps have a different contamination: momentum-regime dominance in
   UP_TREND periods. Pure-price signals require a fundamentals layer or a
   much longer lookback to extract alpha from small-caps.

## Alternatives considered

- **Regime-conditional trading (HIGH_VOL_DOWN_TREND only)**: only 33 of 83
  months tradeable. DSR on those months is unknown but the full-period DSR
  bracket at N=5 = 0.000 makes statistical significance impossible with 33
  observations. Rejected.

- **Shorter momentum lookback (3-1 or 6-1)**: not evaluated; would increase
  turnover and costs further. Deferred — no evidence from current data that
  a different lookback helps.

- **True Russell 2000 universe** (instead of S&P 600): would add 1400 more
  names, but the regime-breakdown problem is a characteristic of small-cap
  stocks in general, not the specific index. Expected to exhibit the same
  pattern with more noise.

## Path forward

India (proto-v0.3-india) is the viable path:
- mean_reversion works across ALL regimes including LOW_VOL_UP_TREND (IC +0.046)
- Walk-forward: 5/7 positive folds, median annual Sharpe +1.045
- Multi-trial DSR at N=5: 0.576 (vs 0.000 for R2K)
- Current constraint: 50-ticker fallback → expanding to 150+ for full G2 evaluation

See proto-v0.3-india/ for the active research branch.
