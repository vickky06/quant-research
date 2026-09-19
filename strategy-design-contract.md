# Strategy Design Contract

**Owner**: Vivek Singh
**Version**: 1.2
**Created**: 2026-09-19
**Last amended**: 2026-09-19 (v1.1 → v1.2 — see Amendments at end)
**Purpose**: Immutable contract defining what this quant system is and isn't. Every future decision is tested against this doc. If a proposed change violates the contract, either the change is rejected or the contract is *explicitly amended and versioned* — never silently drifted.

> **The single hardest discipline in retail quant is not tweaking the rules when a backtest disappoints. This document exists to make that discipline enforceable.**

---

## 1. Market and universe

### Primary market: **India (NSE)**

**Rationale**: Live algo execution on US markets from India is impractical without a direct US brokerage. LRS-based retail platforms (Vested, INDmoney, Groww Global) don't expose algo APIs. The forex + LRS + settlement lag stack destroys any time-sensitive strategy. India via Zerodha Kite Connect is the only path with (a) a real algo API, (b) no forex friction, (c) same-timezone monitoring, (d) mature ecosystem.

**Secondary market: US** — deferred until India strategy has ≥ 12 months of live P&L meeting gates. Then re-evaluate with Interactive Brokers India for direct US algo access.

### Universe definition

```
Primary universe:      Current Nifty 500 constituents
Liquidity filter:      60-day avg daily turnover > ₹5 Cr
Listing filter:        Minimum 3-year listing history
Price filter:          Excluded if trading below ₹50
Sector filter:         None (no sector exclusions)
```

**Rebalance of universe membership**: quarterly. Names entering/leaving Nifty 500 flow through with a 1-week transition window.

**Acknowledged limitations** (documented, not fought):
- Current-membership introduces survivorship bias (delisted historical names not in dataset)
- Point-in-time fundamentals unavailable via free data — signals biased toward price/volume/technical
- No small-cap or SME coverage (illiquidity + slippage would dominate)

---

## 2. North-star metric

### Primary (during research and backtest)

**Deflated Sharpe Ratio (DSR) > 1.0**, computed on rolling 3-year windows, net of realistic costs.

**Why DSR over plain Sharpe**: Bailey & López de Prado (2014) — DSR penalizes Sharpe for the number of independent trials run during strategy search. This is the only Sharpe variant that survives honest self-scrutiny. If we test 30 variants and report the best, plain Sharpe is inflated by selection; DSR corrects it.

### Constraint (hard, non-negotiable)

**Max drawdown < 25%** on 5-year backtest.

### Live-phase metric

Once live and no longer selecting from many strategies, the operational metric switches to **Calmar ratio > 1.0** (annualized return / max drawdown) on rolling 12-month windows. Simpler, more interpretable, still captures both edges.

### Cost model (baked into every backtest)

```
Brokerage (Zerodha equity delivery):    ₹20 or 0.03% (whichever is lower)
STT (equity delivery):                   0.1% on sell
Exchange transaction charges:            ~0.00325%
GST:                                     18% on brokerage + charges
SEBI charges:                            ₹10 per crore
Stamp duty:                              0.015% on buy
Slippage assumption:                     0.10% roundtrip (conservative)
─────────────────────────────────────────────────────────────
Total assumed roundtrip cost:            ~0.20-0.25%
```

**Every backtest must apply this cost model to every simulated trade.** No exceptions.

---

## 3. Data splits — LOCKED

```
┌────────────────────────────────────────────────────────────────┐
│ Research + backtest window:  2015-01-01  →  2023-12-31         │
│                              (9 years — training data)         │
├────────────────────────────────────────────────────────────────┤
│ Held-out validation:         2024-01-01  →  2026-06-30         │
│                              (~2.5 years — LOCKED SET)         │
├────────────────────────────────────────────────────────────────┤
│ Paper trading:               2026-10-01  →  onward             │
│                              (real-time, no money at risk)     │
├────────────────────────────────────────────────────────────────┤
│ Live small money:            After paper trading gate passes   │
│                              (starting ₹50k–₹1L)               │
└────────────────────────────────────────────────────────────────┘
```

### Held-out set discipline — HARD RULES

1. **Do not compute any statistics on the held-out set** during research
2. **Do not look at price charts** of held-out period
3. **Do not tune hyperparameters** against it — not even "just once to check"
4. **One shot**: single evaluation before paper trading. Result stands.
5. **If held-out fails**: back to research window. **No second bite of the held-out apple.** If a new hypothesis needs held-out validation, extend the validation window forward in time (wait for new data), do not re-use the same set.

**This is the discipline that separates real quant from luck-fitting. Every retail quant that fails, fails here.**

---

## 4. Regime buckets — 2×2 Volatility × Trend

### Definition

Regimes are computed daily on the **Nifty 500 index** (broad market state).

```python
# Volatility regime
returns_index = index.pct_change()
vol_60d = returns_index.rolling(60).std() * np.sqrt(252)
vol_percentile = vol_60d.rolling(252*5).rank(pct=True)  # 5-year rolling percentile
vol_regime = "LOW" if vol_percentile < 0.5 else "HIGH"

# Trend regime
ma_200 = index.rolling(200).mean()
trend_slope = (ma_200 - ma_200.shift(20)) / ma_200.shift(20)
trend_regime = "UP" if trend_slope > 0 else "DOWN"

# Composite regime
regime = f"{vol_regime}_VOL_{trend_regime}_TREND"
```

### The 4 regimes

| Code | Description | Historical frequency (approx, India 2015-2023) |
|---|---|---|
| `LOW_VOL_UP_TREND` (Calm Bull) | Most common. Momentum + quality work. Danger of over-optimization here. | ~50% |
| `HIGH_VOL_UP_TREND` (Choppy Bull) | Sideways with fake breakouts. Mean-reversion favored. Momentum whipsaws. | ~20% |
| `LOW_VOL_DOWN_TREND` (Grinding Bear) | Slow decline. Quality + low-vol survive. Long-only bleeds slowly. | ~20% |
| `HIGH_VOL_DOWN_TREND` (Crisis) | 2020-Mar, 2022-Q1 pockets. Correlations → 1. Only cash/trend/defensive win. | ~10% |

### The regime requirement

**Every signal AND the ensemble as a whole must show positive Information Coefficient (IC) in ≥ 3 of the 4 regimes.**

A strategy that only works in `LOW_VOL_UP_TREND` is not a strategy — it is a bull market bet in disguise.

---

## 5. Gates between phases

Every phase transition has a quantitative gate. **If a gate fails, we do not tweak — we go back to the previous phase and iterate on the fundamentals.**

| Gate | Test | Threshold |
|---|---|---|
| **G1: Signal → Ensemble** | Deflated Sharpe, purged CV, regime spread | DSR ≥ 0.5 per signal; positive IC in ≥ 3/4 regimes *with n ≥ 10 rebalances each* (regimes with n < 10 are excluded from evaluation; see ADR-0003) |
| **G2: Ensemble → Held-out** | DSR + max DD on 2015-2023 training set | DSR ≥ 1.0 net of costs; max DD ≤ 25% |
| **G3: Held-out → Paper** | One-shot evaluation on 2024-2026 held-out | Realized DSR ≥ 60% of training DSR; max DD ≤ 25%; positive in ≥ 3/4 eligible regimes (n ≥ 10) present in held-out period |
| **G4: Paper → Live small** | 3 months of paper trading | Realized Sharpe ≥ 60% of held-out Sharpe; slippage ≤ 0.15% actual vs 0.10% assumed |
| **G5: Live small → Live scale** | 12 months of live money | Rolling 12-month Calmar ≥ 1.0 net of actual costs |

**Gate failure protocol**:
1. Stop
2. Do not deploy the failing strategy
3. Investigate root cause (data leak, look-ahead, regime bias, cost model wrong, slippage worse than expected)
4. Fix the root cause
5. Re-run all prior gates that could have been affected
6. **Do not proceed by lowering the threshold**

---

## 6. Strategy design principles — locked

These principles are baked into the architecture. Deviations require explicit contract amendment.

1. **Rebalance frequency**: **daily to weekly**. No intraday. Intraday requires infrastructure and data quality free tier cannot provide.
2. **Signal diversity target**: **effective N ≥ 4** across the ensemble. Measured via eigenvalue analysis of the signal correlation matrix. If effective N drops below 4, one signal must be replaced.
3. **Anti-correlated signal requirement**: at least **one signal must be crisis-resilient** (e.g., trend on VIX/gold, low-vol quality, or an explicit defensive rotation).
4. **Signal validation**: every signal ships with a **written hypothesis** (why it should work economically), a **purged k-fold CV** result, and a **regime-conditional IC table**. No signal enters production without all three.
5. **Meta-learner (PM agent) update cadence**: **monthly**, never daily. Daily weight updates fit noise.
6. **PM weight constraints**: floor 5%, cap `max(30%, 1.2/n_agents)` per agent (scales with Agent count per ADR-0005); L2 regularization on weight *changes* between rebalances.
7. **Forced diversification reset**: every 12 months, PM weights are reset to equal-weight regardless of recent performance. Prevents winner-take-all drift.
8. **Position sizing**: Kelly-lite (0.25 × Kelly), single-name cap 5% of portfolio, sector cap 25%.
9. **Drawdown gate**: if realized drawdown exceeds 15% at any point, position sizing is cut 50% until portfolio recovers to prior high-water mark.
10. **Kill switches** (all automatic):
    - 30-day realized Sharpe drops below 2σ of backtest expected → pause + human review
    - Any signal's rolling IC turns negative for 60 consecutive days → replace or retire that signal
    - Data anomaly detected (missing bars, unadjusted split, forex outlier) → pause until resolved
    - Regime transitions to Crisis → auto-reduce sizing 50% until regime clears

---

## 7. Execution and broker stack

### Live execution: **Zerodha Kite Connect**

- Cost: ₹2000/mo (subscribe only when moving to Gate G4)
- Rationale: mature API, largest retail user base, well-documented, works with `pyalgotrade`, `nsepython`, and custom Python
- Backup: **Fyers API** (free) — use for sandbox testing during Phase 1–2

### Development stack (locked for v1)

```
Language:               Python 3.11+
Data ingestion:         yfinance + nsepython + jugaad-data (free tier)
Storage:                DuckDB (local, columnar, no server)
Compute:                pandas, numpy, scipy
Signal analysis:        alphalens-reloaded
Backtest:               vectorbt (primary), zipline-reloaded (secondary for validation)
Attribution:            pyfolio-reloaded
Live execution:         kiteconnect (Zerodha) or fyers-api-v3 (paper phase)
Orchestration:          Prefect or plain cron
Logging:                Postgres + Grafana (or simplest: SQLite + Streamlit)
```

**Rule**: no library outside this list gets added without a written justification and an amendment to this section.

---

## 8. Position and P&L logging (auditability requirement)

Every decision the system makes is logged with:

1. **Timestamp** (UTC + IST both)
2. **Regime detected** at time of decision
3. **Per-agent raw signal** (z-score or rank per ticker)
4. **PM weights** at that time
5. **Composite signal** per ticker
6. **Position change** proposed vs executed
7. **Fill price vs mid** (slippage measurement)
8. **Cost breakdown** (brokerage, STT, other charges)
9. **Rationale** (which signals contributed most; regime-conditional)

**Why**: without this log, you cannot do attribution, cannot detect drift, cannot debug when live diverges from paper. This is not optional.

---

## 9. What this contract does NOT authorize

To make drift-detection easy, the following are **explicitly outside scope for v1**:

- Options, futures, or derivatives (equity delivery only)
- Intraday trading (daily rebalance floor)
- Leverage (cash-only for v1)
- Short selling on individual names (cash-secured only; short via inverse ETFs if needed)
- Any signal source requiring paid data
- Any strategy relying on point-in-time fundamentals
- Alt data feeds (LLM sentiment on news is fine; satellite/credit card data is not)
- Automated strategy invention (LLM writing new signals) — humans design, LLMs may score
- More than 6 base agents in the ensemble (complexity cap)
- US market live execution (see §1)

Any expansion here requires an explicit amendment with rationale and re-running of prior gates.

---

## 10. Amendment protocol

This contract is not immutable — but changes must be:

1. **Explicit** — written as an amendment to this file
2. **Versioned** — the top of this doc increments (1.0 → 1.1 → 2.0)
3. **Justified** — the amendment must state *what changed and why*
4. **Gate-preserving** — if the amendment affects a prior gate, that gate must be re-run

**What amendment protocol prevents**: the classic retail failure mode of "just this once, let's ignore the DD limit / retry the held-out set / add a lookback tweak because it works better". Every one of those is a contract violation. If they're worth doing, they're worth writing down.

---

## 11. Definitions of done (v1 scope)

The v1 system is "done" when:

- [ ] All data ingestion is automated, idempotent, and produces reproducible datasets
- [ ] At least 4 signals are validated through G1 with regime-conditional IC tables
- [ ] Effective N of the signal set is measured and ≥ 4
- [ ] Ensemble + PM passes G2 with DSR ≥ 1.0, max DD ≤ 25%
- [ ] Held-out evaluation (single-shot, G3) meets threshold
- [ ] 3 months of paper trading completed with G4 threshold met
- [ ] Full logging (§8) is in place and audited
- [ ] Kill switches (§6.10) are implemented and tested (simulated triggers)
- [ ] `strategy-design-contract.md` (this file) has been reviewed and no drift has occurred

Once v1 is done and live small money runs for 12 months meeting G5, the system is ready for scale-up. That's when we re-open the contract for v2 amendments.

---

## Appendix: quick reference

**North-star**: DSR > 1.0 net of costs, Max DD < 25%
**Universe**: Nifty 500, ₹5Cr turnover, 3-year listing, >₹50 price
**Training data**: 2015–2023
**Held-out (LOCKED)**: 2024 → 2026-Q2
**Paper trade start**: 2026-Q4
**Regime buckets**: LOW_VOL × HIGH_VOL × UP_TREND × DOWN_TREND (2×2 = 4)
**Live broker**: Zerodha Kite Connect
**Paper broker**: Fyers API
**Rebalance**: daily to weekly (never intraday)
**Max agents**: 6
**PM update cadence**: monthly
**Position sizing**: 0.25 × Kelly, 5% single name, 25% sector

---

## Amendments

### v1.1 → v1.2 (2026-09-19)

**Change**: §6.6 PM weight constraint `cap 30%` → `cap max(30%, 1.2/n_agents)`. The cap now scales with the number of Agents in the ensemble.

**Reason**: v0.3 empirically demonstrated that a fixed 30% cap is *more restrictive* than the equal-weight prior when N < 4 Agents. With N=2, equal weight is 50% each — a 30% cap forces renormalization back to ~50/50 regardless of Meta-Learner IC evidence. The scaling formula preserves the original constraint intent (~1.2× equal-weight as tilt ceiling) at any Agent count. At N ≥ 4 the formula returns 30%, unchanged from v1.1.

**Justification**: see [ADR-0005](docs/adr/0005-meta-weight-bounds-scale-with-n.md).

**Gates affected**: none directly. Meta-Learner weights change; ensemble backtest re-runs under new bounds.

### v1.0 → v1.1 (2026-09-19)

**Change**: §5 Gate G1 and G3 regime spread threshold now requires *n ≥ 10 rebalances* per Regime being evaluated. Regimes with fewer observations are excluded from the numerator and denominator, marked "insufficient sample".

**Reason**: v0.2 backtest exposed that `LOW_VOL_DOWN_TREND` had only 4 Rebalances in the 9-year Training Set, making its IC sign a coin flip. The original strict "3 of 4 regimes" rule allowed a noise-observation Regime to veto Gate G1 for ensembles that had genuine edge on the other three Regimes with meaningful samples.

**Justification**: see [ADR-0003](docs/adr/0003-regime-min-sample-size.md).

**Gates affected**: G1, G3. G2 does not use regime spread. Prior gate results must be re-run under the amended rule.

---

*End of contract. Every future decision starts with: "does this violate the contract?"*
