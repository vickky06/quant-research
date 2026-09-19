# Held-out Verdict — Gate G3

**Verdict**: **FAIL**
**Timestamp**: 2026-09-19T22:04:12
**Contract version**: 1.2
**Held-out window**: 2024-01-01 → 2026-06-30

## Metrics
- Held-out DSR: **0.000** (required ≥ 0.511)
- Held-out Sharpe (annualized, net): **-2.508**
- Held-out cumulative return: **-67.25%**
- Held-out max drawdown: **-66.18%**
- Held-out mean IC: -0.0661
- Rebalances: 29

## Gates
- DSR ≥ 60% of training: ✗ FAIL
- Max DD ≤ 25%: ✗ FAIL
- Regime spread: ✗ FAIL (0/2 eligible)

## Regime Scorecard (held-out)

| Regime | Mean IC | Rebalances |
| --- | --- | --- |
| HIGH_VOL_DOWN_TREND | -0.0489 | 1 |
| HIGH_VOL_UP_TREND | -0.1129 | 10 |
| LOW_VOL_UP_TREND | -0.0411 | 18 |

---

*This verdict is contract-locked. Do not re-run held-out evaluation.*
*If you did re-run: override_used = False*