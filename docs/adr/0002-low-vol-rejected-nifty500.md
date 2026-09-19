# Low-volatility L/S Agent rejected for Nifty 500 (2015–2023)

The classical low-vol anomaly (Baker-Bradley-Wurgler 2011; Frazzini-Pedersen 2014) does not survive when implemented as a **long-low-vol / short-high-vol decile portfolio on Nifty 500 over 2015-01 → 2023-12**. Backtest result: mean IC −0.0037, Sharpe −0.77 net, cumulative return −84%. Signal is retired from the Agent registry.

**Why**: the short leg (high-realized-vol names) in Nifty 500 is dominated by mid- and small-caps, which have had a persistent positive size premium in India through this window. Going short those names bled the L/S consistently, and the modest low-vol lift on the long leg was insufficient to offset it. This is a market-composition artifact, not a repudiation of the underlying anomaly — the literature's evidence is US-large-cap and the mechanism there is different from what Nifty 500 provides.

**Considered alternatives before rejecting**:
- Long-only top-decile low-vol (no short leg): defensive tilt without the small-cap bleed. Kept as a future option but not implemented now — the ensemble needs a bear-regime-*positive* signal, and long-only low-vol is more neutral than positive.
- Low-downside-beta (beta measured on index-down days only): more faithful to what we actually want but more complex to compute; deferred.

**Replaced by**: short-term mean reversion (see pipeline `compute_mean_reversion`). Theoretical fit is stronger — mean reversion is the direct counterpart to the 1-month gap in 12-1 momentum (Jegadeesh 1990), making it a natural ensemble diversifier.

**Reversibility**: if a later market regime revives the low-vol premium in India (e.g., end of the mid-cap rally, or a prolonged crisis), this decision should be revisited via a superseding ADR. `compute_low_vol` remains in `pipeline.py` as a reference implementation, but is excluded from `AGENTS`.
