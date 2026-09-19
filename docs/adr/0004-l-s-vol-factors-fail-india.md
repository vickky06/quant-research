# Long-short vol-based factors fail in Nifty 500 due to size premium

Both **low_vol** (ADR-0002) and **low_downside_beta** implemented as long-short decile portfolios have failed catastrophically on Nifty 500 (2015-2023):

| Signal | Sharpe | DSR | Max DD | HIGH_VOL_DOWN_TREND IC |
|---|---|---|---|---|
| low_vol | −0.77 | 0.010 | −39% (never recovered) | −0.053 |
| low_downside_beta | −0.81 | 0.009 | −79% (never recovered) | −0.121 |

Both signals rank stocks by inverse volatility (or beta) and short the top-volatility bucket. In Nifty 500, that top-vol bucket is dominated by **mid- and small-caps**, which have had a persistent positive size premium in India through this window. The short leg bled continuously; the long leg's modest lift was insufficient to offset. The failure is the same market-composition artifact in both signals, not the specific vol definition.

**General rule established for this Universe**: long-short factor implementations whose short leg systematically overweights Nifty 500 mid/small-caps are structurally disadvantaged. This applies to low_vol, low_downside_beta, and likely any inverse-risk-metric signal.

**Retired**: `compute_low_downside_beta` removed from `AGENTS`. Function retained in `pipeline.py` as a reference implementation.

**Implications for future signal design**:
- Vol-related "defensive" signals should be implemented **long-only** on the low-vol / low-beta bucket, not L/S — this preserves the anomaly's economic content without exposing us to the small-cap short.
- Or use signals **uncorrelated with size** (return smoothness / quality proxy, individual-stock trend filters).
- Crisis-regime coverage may need to come from **regime overlays** (contract §6 kill switches, position-sizing conditional on Regime) rather than from a symmetric L/S Agent.

Supersedes and generalizes: [ADR-0002](0002-low-vol-rejected-nifty500.md).
