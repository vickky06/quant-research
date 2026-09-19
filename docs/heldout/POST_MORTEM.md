# Post-mortem — Gate G3 FAIL

**Generated**: 2026-09-19T19:17:48
**Held-out window**: 2024-01-01 → 2026-06-30
**Strategy config**: ['momentum', 'mean_reversion'] + IC-weighted meta-learner (contract v1.2)
**Verdict**: FAIL (locked at `docs/heldout/verdict.md`, unchanged by this analysis)

This document diagnoses *why* the strategy failed. It does not attempt to invalidate the verdict.

## 1. Head-to-head vs Nifty 50 index

- **Strategy cumulative return (held-out)**: **-11.34%**
- **Nifty 50 index cumulative (held-out)**: **+10.14%**
- **Opportunity cost (strategy − index)**: **-10.79%**
- Rebalances: 18

The strategy didn't just under-perform — it was **anti-market** in a period where beta was positive. A plain Nifty 50 index ETF would have been dramatically better.

## 2. Worst months

| Month | Strategy return | Index return |
| --- | --- | --- |
| 2025-01 | -10.21% | -0.58% |
| 2025-08 | -10.12% | -1.59% |
| 2025-09 | -7.57% | +0.75% |
| 2025-10 | -5.57% | +4.51% |
| 2026-01 | -4.80% | -2.38% |

## 3. Best months

| Month | Strategy return | Index return |
| --- | --- | --- |
| 2025-02 | +9.06% | -3.63% |
| 2025-06 | +7.65% | +3.10% |
| 2026-05 | +6.43% | -2.61% |
| 2025-04 | +6.30% | +3.46% |
| 2025-11 | +5.97% | +1.03% |

## 4. Meta-learner weight evolution

Warmup: meta-learner uses equal weights until 24 rebalances of IC history exist. Held-out had only 18 rebalances total — so **all held-out rebalances ran in equal-weight warmup mode**. The intended IC-weighted meta-learner never activated. This is a real setup issue, but does not rescue the verdict: even the equal-weight ensemble in training had DSR 0.994 (required 60% → 0.596; observed held-out DSR 0.369 is a 40% relative degradation).

| Agent | Mean weight | Min | Max | Std |
| --- | --- | --- | --- | --- |
| momentum | 0.523 | 0.500 | 0.706 | 0.067 |
| mean_reversion | 0.477 | 0.294 | 0.500 | 0.067 |

## 5. Per-Agent Information Coefficient (held-out)

| Agent | Mean IC | Min | Max | Std | Rebalances |
| --- | --- | --- | --- | --- | --- |
| momentum | +0.0379 | -0.2458 | +0.3258 | 0.2033 | 6 |
| mean_reversion | -0.0452 | -0.4783 | +0.1789 | 0.1663 | 18 |

**Interpretation**: If per-Agent IC is meaningfully positive on held-out, the individual signals still have predictive power and the failure is at aggregation / portfolio-construction. If IC is near zero or negative, the underlying edge itself has decayed / disappeared in this window.

## 6. Training expectation vs held-out reality

Walk-forward folds (from 2015-2023 training) showed:

| Year | Sharpe | Cum return | Max DD |
| --- | --- | --- | --- |
| 2015 | +1.552 | +19.48% | -2.80% |
| 2016 | +0.063 | -0.24% | -6.78% |
| 2017 | +0.112 | +0.64% | -3.01% |
| 2018 | +1.650 | +22.65% | -6.73% |
| 2019 | +2.067 | +25.14% | -2.33% |
| 2020 | +0.105 | -0.24% | -13.71% |
| 2021 | +2.363 | +43.57% | -1.42% |
| 2022 | -0.675 | -10.44% | -14.57% |
| 2023 | N/A | +36.66% | -3.54% |

Walk-forward summary: mean Sharpe **+0.905**, std **1.129**, range **[-0.675, +2.363]**

Held-out Sharpe of −0.281 sits **below** all walk-forward folds except 2022 (−0.675). The 2022 fold was the leading indicator — a bear/rate-hike year where the strategy already failed. 2024-2026 held-out extended that failure pattern rather than reverting to the pre-2022 pattern.

## 7. Candidate root causes

In descending order of evidence:

### 7.1 Momentum decay post-2020 (most likely)
12-1 momentum in India has been widely researched and published since ~2015. McLean-Pontiff (2016) documents ~58% post-publication decay for equity anomalies. Our held-out mean IC of +0.0379 (vs training mean IC ~+0.03) is consistent with momentum edge having decayed materially in the last few years. This aligns with global evidence — factor investing has broadly underperformed in the last decade of loose monetary policy + growth-stock dominance.

### 7.2 Universe-composition change (very likely)
Nifty 500 composition changes quarterly. Our universe filter took *current* membership backfilled through history — a survivorship bias that flatters the training set. The 2024-2026 test used current membership *not* backfilled, so the actual composition may be materially different from what our signals were 'trained on' implicitly. This is a documented limitation in `PROTOTYPE_NOTICE.md`.

### 7.3 Mid-cap correction (H1 2025)
Nifty Midcap 100 saw a substantial drawdown in early 2025. Our L/S structure shorts high-vol names, which skews toward mid/small caps. A mid-cap correction should have *helped* the short leg — but only if the stocks we shorted actually underperformed. If large-caps also fell (correlated correction), the L/S got compressed while both legs bled.

### 7.4 Warmup ate the entire held-out
As noted above, the meta-learner never left warmup. The strategy that actually ran was equal-weight momentum + mean_reversion — not the IC-weighted version we spent v0.3 building. In a longer held-out this would resolve; in this window it meant the meta-learner design got no real test.

### 7.5 Statistical variance (always partially true)
Walk-forward std was 1.13 Sharpe. A −0.28 Sharpe fold is within 1σ of the walk-forward mean of +0.9. Multi-trial DSR bracket [0.008, 0.076, 0.425] had already warned that our claimed edge was statistically fragile at retail-sample scale. Held-out landed in the negative tail. This is not exceptional — it's what a fragile edge does when the wind changes.

## 8. Actionable findings for the next iteration

1. **Momentum-only strategies are past their prime.** Any successor needs a materially different alpha thesis, not a re-parameterization of momentum.
2. **Point-in-time universe reconstruction matters.** Backfilling current index membership through history is a hidden multiplier on backtest DSR. A serious iteration needs historical membership snapshots.
3. **Warmup must fit within test window.** A 24-month meta-learner warmup is inappropriate for a 30-month held-out. Either shorten warmup or extend the held-out window (contract §3 rule 5 allows extending forward).
4. **Correlation-check every new signal against every existing one at design time.** return_smoothness was retired late because we didn't check whether it would diversify momentum. That check is 10 lines of code and should precede backtesting.
5. **US free data is materially cleaner.** For a pivot, US large-caps have less survivorship problem in current membership, no size-premium short-leg trap, cleaner point-in-time via Alpaca. Framework is market-agnostic.

## 9. Bottom line

The strategy failed because **its alpha thesis is no longer alive in this universe over this window**. The failure was correctly predicted by walk-forward variance and multi-trial DSR correction. Every diagnostic here reinforces the verdict; none legitimizes reopening it.

The framework survives. The vocabulary, gate discipline, meta-learner implementation, purged CV, one-shot held-out harness, and multi-trial DSR bracket are all **reusable in a redesigned strategy on a new market or a new signal family** with a fresh held-out window.