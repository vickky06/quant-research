# Meta-Learner max_weight scales with number of Agents

Contract §6.6 originally specified `max_weight = 0.30` per Agent as a hard cap on Meta-Learner output. Amended to `max_weight = max(0.30, 1.2 / n_agents)` so the cap remains meaningful whether the ensemble has 2 Agents or 6.

**Why**: with 2 Agents the equal-weight prior is 50% each. A hard cap of 30% is *more restrictive* than equal weight — it forces the Meta-Learner to renormalize back toward 50/50 regardless of IC evidence. The cap was designed for the 4-6 Agent regime where equal weight is 16-25% and a 30% cap represents a meaningful +5pp tilt. The scaling formula preserves the original intent (~1.2× equal weight allowed as tilt ceiling) at any Agent count.

**Values by N**:

| N | Equal weight | Amended max_weight | Original max_weight |
|---|---|---|---|
| 2 | 50% | 60% | 30% ← more restrictive than equal |
| 3 | 33% | 40% | 30% ← more restrictive than equal |
| 4 | 25% | 30% | 30% (unchanged) |
| 5 | 20% | 30% | 30% (unchanged) |
| 6 | 16.7% | 30% | 30% (unchanged) |

At N ≥ 4 the formula returns 30%, preserving the contract's original constraint. min_weight remains 5%.

**Empirically motivated**: v0.3 backtest with 2 Agents showed meta_ensemble weights of momentum=50.5% and mean_reversion=49.5% — barely different from equal weight, because 30% cap → renormalized back to 50/50. The Meta-Learner had no room to express IC evidence.

**Contract v1.1 → v1.2**.
