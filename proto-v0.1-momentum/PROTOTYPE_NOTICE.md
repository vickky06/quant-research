# PROTOTYPE — throwaway code

**Question this prototype answers**: Can we pass Gate G1 (per-signal validation) with 12-1 momentum on Nifty 500 (2015-2023) using free data?

**Success criterion (Gate G1)**:
- DSR ≥ 0.5 net of 0.20% roundtrip cost
- Positive IC in ≥ 3 of 4 Regimes

**Status**: throwaway. When the question is answered, the validated logic (Signal computation, Regime detection, IC/DSR math) lifts into the real codebase as pure functions. This directory itself is a primary-source snapshot — do not import from `proto-v0.1-momentum/` in production code.

**Not this prototype's job**:
- Meta-Learner / Portfolio Constructor / ensemble
- Paper trade or live execution
- Attribution logging beyond a single-run summary
- Multi-signal validation
- Held-out Set evaluation (explicitly asserted-against)

**Deviations from the skill's LOGIC/UI branches**: neither the shareable-HTML nor UI-variations format fits a computational research prototype. Following the general skill principles instead: throwaway + trivial-to-run + no-polish + surface-state.

---

## Answer captured (2026-09-19, `--fast` mode, 31 large-cap subset)

**Verdict**: Gate G1 **PASS** (mechanically). Interpret with the caveats below.

- DSR (≈PSR, N=1 trial): **0.695** ≥ 0.5 threshold ✓
- Positive IC in ≥3 of 4 Regimes: **3 of 4** ✓ (HIGH_VOL_DOWN_TREND was −0.077 — momentum reverses in crisis, matches theory)
- Overall mean IC: **+0.0307**
- Sharpe (annualized, net of 0.20% roundtrip): **+0.173**
- Cumulative 9-year net L/S return: **+9.97%**
- Turnover: avg 30.8% per rebalance
- Monthly observations: 107

**Honest interpretation**: the *pipeline* works end-to-end and the *sign* of momentum's edge is correct. But the *economic magnitude* is thin — Sharpe 0.17 means noisy positive edge, not a viable standalone strategy. The DSR of 0.695 says "69% confident true Sharpe > 0"; it does not say the strategy makes money after implementation frictions we haven't modelled (slippage worse than 10 bps, gap fills, borrow costs on shorts, tax drag).

**What this tells us for v0.2**:
- Pipeline mechanics are correct — regime detection, monthly rebalance, IC and DSR computation all produce sane numbers
- Momentum passes G1 individually — it can *enter* the ensemble
- Momentum alone is not enough — the ensemble hypothesis (multiple weakly-correlated signals combined) is validated as necessary, not optional
- Full Nifty 500 run needed before treating this as a real G1 pass — 31 stocks is too thin for stable deciles

**Not yet answered** (defer to v0.2+):
- Does momentum pass G1 on the full Nifty 500 universe? (larger deciles, more stable IC)
- Does adding quality/low-vol/mean-reversion signals produce ensemble Sharpe > 1.0?
- Does the ensemble survive Gate G2 (Deflated Sharpe on ensemble net of overfit trials)?
