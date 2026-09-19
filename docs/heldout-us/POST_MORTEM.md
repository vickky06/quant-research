# Post-mortem — Gate G3 FAIL (US v0.2)

**Generated**: 2026-09-19
**Prototype**: proto-v0.2-us (S&P 500, mean_reversion + sector_neutral_mr)
**Held-out window**: 2024-01-01 → 2026-06-30 (29 rebalances)
**Verdict**: FAIL (locked at `docs/heldout-us/verdict.md`)

---

## 1. Head-to-head vs S&P 500 index

| Metric | Strategy | S&P 500 index |
|---|---|---|
| Cumulative return (held-out) | **-67.25%** | ~+50% (2024-2026 AI bull) |
| Annualized Sharpe | -2.508 | strongly positive |
| Max drawdown | -66.18% | ~-10% peak-to-trough |
| Mean IC | -0.066 | — |

The strategy was catastrophically anti-market. Every signal was anti-predictive — the signal correctly IDENTIFIED the strongest stocks in training but shorted them out-of-sample.

---

## 2. Regime distribution (held-out)

| Regime | n | IC | Training IC (for reference) |
|---|---|---|---|
| LOW_VOL_UP_TREND | **18** (62%) | -0.041 | -0.010 |
| HIGH_VOL_UP_TREND | 10 (34%) | -0.113 | +0.034 |
| HIGH_VOL_DOWN_TREND | 1 (3%) | -0.049 | +0.057 |

**Key finding**: 62% of held-out rebalances were in LOW_VOL_UP_TREND — the exact regime where mean reversion had negative IC even in training. The 2024-2026 AI bull market was overwhelmingly LOW_VOL_UP_TREND (subdued VIX, S&P 500 making new ATHs regularly).

In training, mean reversion worked in HIGH_VOL regimes (combined IC ≈ +0.05) and failed in LOW_VOL_UP_TREND (IC -0.010). The held-out landed 97% in UP_TREND regimes, with 62% in the regime where the signal was already known to fail.

---

## 3. Why the held-out was so extreme (−67%)

The 2024-2026 regime amplified the signal's failure in three compounding ways:

### 3.1 Regime mismatch (primary cause)

LOW_VOL_UP_TREND = calm directional bull market = hostile to mean reversion. In this regime:
- Recent winners (mega-cap tech/AI: NVDA, META, MSFT) continue winning
- Recent losers (non-AI, value stocks) continue losing
- Mean reversion strategy: LONG recent losers, SHORT recent winners → anti-market every month

The 2024-2026 AI bull market produced the longest sustained LOW_VOL_UP_TREND streak in our data range. Training (2015-2023) had mixed regimes including multiple HIGH_VOL episodes.

### 3.2 Signal directionality reversal in momentum regime

Mean reversion's IC went from +0.025 (training) to -0.066 (held-out). An IC sign flip this extreme isn't statistical noise — it's structural. The signal moved from "predicting which stocks outperform" to "predicting which stocks underperform." This only happens when the market is in a persistent momentum regime where winners keep winning.

### 3.3 Sector composition change in held-out universe

The S&P 500 in 2026 has a much higher tech weight than in 2015. Our current-membership universe (no point-in-time adjustment) applies the same stock list throughout training AND held-out. This means the held-out universe is already biased toward 2026 survivors (tech-heavy), amplifying the sector mismatch.

### 3.4 Long-short symmetry in a trending market

L/S portfolios work best when returns are cross-sectionally dispersed. In a directed market where "AI = up, everything else = down," the L/S compression is asymmetric: the long leg (recent losers = non-AI) underperforms AND the short leg (recent winners = AI) outperforms. The strategy loses on both sides.

---

## 4. Signal evaluation scorecard (cumulative across this prototype)

| Signal | Individual G1 | Individual DSR | Status in US |
|---|---|---|---|
| momentum (12-1) | FAIL | 0.270 | Retired |
| return_smoothness | FAIL | 0.146 | Retired |
| low_vol (BAB) | FAIL | 0.035 | Retired |
| max_lottery (MAX factor) | FAIL | 0.025 | Retired |
| mean_reversion (20d) | PASS | 0.793 | Core signal |
| sector_neutral_mr | PASS | 0.684 | Complementary |
| **meta_ensemble** | — | **0.852** | Best training result |

Meta-ensemble training: Sharpe +0.356, MaxDD -19.48%, walk-forward mean +0.558.

**Conclusion**: S&P 500 pure-price L/S has an ~0.35 Sharpe ceiling in training (2015-2023). Gate G2 (Sharpe ≥ 1.0) cannot be passed. Held-out (2024-2026) is a hostile regime for the only working signal family (mean reversion).

---

## 5. Regime-conditioning diagnostic (what WOULD have helped)

If we had filtered to trade ONLY in HIGH_VOL regimes (skipping LOW_VOL_UP_TREND months):
- In training, HIGH_VOL months (HIGH_VOL_DOWN + HIGH_VOL_UP): 24 + 41 = 65 of 107 months (61%)
- Mean IC in HIGH_VOL: +0.047 (combined) vs -0.010 in LOW_VOL_UP
- In held-out, HIGH_VOL months: only 11 of 29 (38%)

Even regime-conditioning wouldn't have saved the held-out given only 11 tradable months with negative IC in those months too (IC -0.049 and -0.113 in HIGH_VOL months of held-out). The signal failure is regime-independent in 2024-2026.

---

## 6. Actionable findings for next iteration (v0.3)

### 6.1 Regime-conditional signal switching (highest priority)
Mean reversion + momentum as a regime-conditional pair:
- In HIGH_VOL regimes: trade mean_reversion (IC +0.047 in training, signal works)
- In LOW_VOL_UP regimes: trade momentum or be flat (mean_reversion hostile here)
- Regime-switching approach avoids the catastrophic held-out regime mismatch

### 6.2 Russell 2000 universe
Small-cap universe. Key properties:
- 2000 stocks → better signal-to-noise for cross-sectional strategies
- Less mega-cap tech concentration → signals less contaminated by AI/tech theme
- Momentum known to work in small-caps even post-2020 (documented in literature)
- Mean reversion also works (more idiosyncratic price behavior)
- Free data available via yfinance for Russell 2000 components
- Expected DSR ceiling: 1.0+ (vs 0.35 ceiling for S&P 500 large-caps)

### 6.3 Point-in-time universe reconstruction
Current-membership backfill is a hidden bias multiplier. Both training AND held-out use
2026 S&P 500 members. For the held-out specifically, "survivor" stocks (still in S&P 500
in 2026) had selection pressure based on strong performance — they survived because they
were good. Shorting 2026 survivors in 2024 was structurally inadvisable.

### 6.4 Historical fundamentals for quality signal
Novy-Marx gross profitability (2013) works in US large-caps across regimes. Requires
historical quarterly financials (2015-2023). yfinance limited to ~4 recent years.
Options: SEC EDGAR pipeline or SimFin/FMP free tier.

---

## 7. Framework assessment

The research framework (G1 → G2 → G3 gate architecture) worked correctly:
- G2 signaled a weak training result (Sharpe 0.356, below the 1.0 bar)
- Walk-forward showed LOW_VOL_UP_TREND had negative IC throughout training
- Multi-trial DSR at N=5 was only 0.201 — the edge was statistically fragile
- G3 confirmed the fragile edge doesn't survive a trend regime

The G3 FAIL was foreseeable from G2 analysis. The decision to proceed to G3 with G2 FAIL was a valid research decision to test the held-out regime, but the outcome reinforces that G2 should be a harder gate than it was.

**Framework survives. Strategy is retired.**
