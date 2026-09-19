# Held-out Verdict — Gate G3

**Verdict**: **FAIL**
**Timestamp**: 2026-09-19T19:06:09
**Contract version**: 1.2
**Held-out window**: 2024-01-01 → 2026-06-30

## Metrics
- Held-out DSR: **0.369** (required ≥ 0.598)
- Held-out Sharpe (annualized, net): **-0.281**
- Held-out cumulative return: **-11.34%**
- Held-out max drawdown: **-22.59%**
- Held-out mean IC: -0.0102
- Rebalances: 18

## Gates
- DSR ≥ 60% of training: ✗ FAIL
- Max DD ≤ 25%: ✓ PASS
- Regime spread: ✗ FAIL (0/0 eligible)

## Regime Scorecard (held-out)

| Regime | Mean IC | Rebalances |
| --- | --- | --- |
| UNKNOWN | -0.0102 | 18 |

---

*This verdict is contract-locked. Do not re-run held-out evaluation.*
*If you did re-run: override_used = False*