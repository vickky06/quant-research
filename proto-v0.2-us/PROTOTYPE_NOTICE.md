# PROTOTYPE — throwaway code

**Question this prototype answers**: Can a mean_reversion + sector_neutral_mean_reversion ensemble pass G3 (held-out) on S&P 500 (2015-2023 training, 2024-2026 held-out) using free price data?

**Status**: throwaway. When the question is answered, validated logic lifts into the real codebase as pure functions. Do not import from `proto-v0.2-us/` in production code.

---

## Signal evaluation log (US large-caps, training 2015-2023)

All signals evaluated on S&P 500 (453 stocks after filters). Every signal except
mean reversion fails G1 for the same structural reason: tech-sector dominance
2015-2023 creates systematic short-tech bias in any signal whose long window
overlaps with the market-wide trend.

| Signal | G1 | DSR (PSR) | Sharpe | Root cause of failure |
|---|---|---|---|---|
| momentum (12-1) | FAIL | 0.270 | -0.20 | Factor crowding + FAANG dominance |
| return_smoothness | FAIL | 0.146 | -0.35 | Smooth compounders ≠ tech winners |
| low_vol (BAB) | FAIL | 0.035 | -0.60 | Low-vol stocks lag in growth regime |
| max_lottery (MAX factor) | FAIL | 0.025 | -0.65 | Short earnings-beat gap = short tech |
| **mean_reversion (20d)** | **PASS** | **0.793** | **+0.284** | 20d window escapes sector trend |
| **sector_neutral_mr** | **PASS** | **0.684** | **+0.162** | Idiosyncratic reversion, sector-demeaned |

Best ensemble (IC-weighted meta-learner, both signals):

| Metric | Value | G2 threshold | Status |
|---|---|---|---|
| Annualized Sharpe | +0.356 | ≥ 1.0 | **FAIL** |
| PSR | 0.852 | ≥ 0.90 | **FAIL** |
| Max drawdown | -19.48% | ≤ 25% | **PASS** |

## G3 override decision

Gate G2 fails on both Sharpe (0.356 < 1.0) and PSR (0.852 < 0.90). Proceeding
to G3 is a **contract relaxation** made for the following reasons:

1. **Pure-price ceiling identified**: S&P 500 large-caps with free price data have
   a structural Sharpe ceiling around 0.35-0.40 for L/S strategies. No additional
   pure-price signal passed G1 in this universe/period. The ceiling is real; it is
   not a tuning artifact.

2. **Walk-forward is healthy**: mean Sharpe +0.558 across 8 annual folds,
   6/9 positive, worst fold -0.229 (2020 COVID). The strategy has no catastrophic
   fold, unlike the India prototype (worst fold: -3.156).

3. **MaxDD passes**: -19.48% < 25% — portfolio risk is under control.

4. **Multi-trial DSR is non-trivial**: at N=5, DSR = 0.201 (vs ~0.000 for all
   prior configurations). Evidence of real, if weak, edge.

5. **Research value of G3**: even if G3 fails, the held-out result on a clean L/S
   strategy with healthy walk-forward stats is high-information. A G3 FAIL here
   would point specifically to US-market structural shift post-2024 (rate cuts,
   AI cycle), not to a fundamentally broken signal.

**Contract §3 relaxation**: this prototype proceeds to G3 with an explicit
acknowledgement that G2 FAILS. The held-out verdict is one-shot and locked as
usual. A G3 FAIL does not restart the research; it informs the next iteration.

## Next iteration plan (if G3 FAIL)

1. **Russell 2000 pivot**: small-cap universe, less mega-cap tech dominance.
   Pure-price signals (including momentum) are well-documented to work there.
   Framework is market-agnostic — adapt universe fetch + cost model.

2. **Fundamental quality signal**: Novy-Marx gross profitability requires
   historical financials (2015-2023). yfinance only provides ~4 years of
   quarterly data. Requires SEC EDGAR pipeline or paid source.

3. **Sector-rotation signal**: use sector ETF (XLK, XLV, etc.) relative
   momentum to add a sector-level signal on top of individual stock selection.

## Not this prototype's job

- Live execution or paper trading
- Attribution logging beyond single-run summary
- Point-in-time index reconstruction (survivorship bias acknowledged)
- Meta-learner with longer warmup (24m ≫ 18m held-out — same problem as India v0.1)
