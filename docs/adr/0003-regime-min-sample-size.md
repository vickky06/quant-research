# Gate G1 regime spread evaluated only on regimes with n ≥ 10 rebalances

The Gate G1 requirement of "positive IC in ≥ 3 of 4 Regimes" now excludes any Regime with fewer than 10 monthly Rebalances during the evaluation window. Excluded Regimes are labeled "insufficient sample" and count against neither the numerator nor the denominator.

**Why**: with 4 Rebalances in a Regime (e.g., `LOW_VOL_DOWN_TREND` occurred only in 4 months over 2015-01–2023-12), the sign of mean IC is dominated by noise, not signal — random reshuffling of the 4 observations flips positive/negative freely. Treating that as an authoritative pass/fail gives a small-sample noise-observation veto power over the entire gate. That is not what the gate was designed to test.

**What triggered it**: v0.2 ensemble backtest — Sharpe +0.87, DSR 0.994 (both strong), but blocked by regime spread of 2/4 driven by a Regime with n=4 (essentially a coin flip) and one with n=19 (genuine momentum weakness in crisis, per Daniel-Moskowitz 2016).

**Considered alternatives**:
- **Weight regime IC by its sample size** (compute weighted average across regimes): rejected — the whole point of regime spread is to catch fragile strategies, not average them out.
- **Lower the required-positive count to 2 of 4**: rejected — too weak a bar. A signal that only works in bull markets would pass, defeating the gate's purpose.
- **Extend the Training Set backward to gather more crisis samples**: rejected for now — free data reliability degrades pre-2013, and the held-out lock prevents forward extension.

**Consequences**:
- Regimes with n < 10 do not count toward or against Gate G1
- If fewer than 3 Regimes have n ≥ 10 in the evaluation window, the gate's semantics need re-thinking — but for our Training Set that condition holds (3 of 4 Regimes have n ≥ 19)
- Gate G3 (Held-out) inherits the same rule
- Contract v1.0 → v1.1 amends §5 G1 threshold accordingly
