# Held-out Verdict — Gate G3 (India v0.3)

**Verdict**: **PASS**
**Timestamp**: 2026-09-19T23:26:16
**Contract version**: 1.3
**Held-out window**: 2024-01-01 → 2026-06-30

## Strategy
- Signals: mean_reversion, sector_neutral_mr, momentum
- Regime weights: DOWN_TREND → MR-heavy; UP_TREND → momentum-heavy
- No hard regime gate

## Metrics
- Held-out DSR: **0.903** (required ≥ 0.600)
- Held-out Sharpe (annualized, net): **+0.872**
- Held-out cumulative return: **+22.73%**
- Held-out max drawdown: **-9.09%**
- Held-out mean IC: +0.0351
- Rebalances: 29

## Gates
- DSR ≥ 60% of training: ✓ PASS
- Max DD ≤ 25%: ✓ PASS
- Regime spread: ✓ PASS (2/2 eligible)

## Regime Scorecard (held-out)

| Regime | Mean IC | Rebalances |
| --- | --- | --- |
| HIGH_VOL_DOWN_TREND | +0.0513 | 5 |
| HIGH_VOL_UP_TREND | +0.0087 | 12 |
| LOW_VOL_UP_TREND | +0.0546 | 12 |

---

*This verdict is contract-locked. Do not re-run held-out evaluation.*
*override_used = False*