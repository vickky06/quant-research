# Quant Trading System

A factor-scoring ensemble that trades Indian equities (Nifty 500) on a daily-to-weekly cadence. Multiple **Agents** produce **Signals**; a **Meta-Learner** weights them into an **Ensemble Score**; a **Portfolio Constructor** turns scores into **Positions**; execution runs through a broker (Zerodha). This document is the shared vocabulary.

## Language

### Producers

**Agent**:
A component that produces one Signal per Rebalance per Instrument. May be rules-based, ML-based, or LLM-based. Identified by a stable `AgentId`; owns a written hypothesis for why its Signal has predictive power.
_Avoid_: strategy, model, alpha (all overloaded)

**Signal**:
The numeric output of an Agent for a specific (Instrument, timestamp) pair, usually a z-score or rank. Data, not code. An Agent produces many Signals; a Signal has exactly one Agent.
_Avoid_: score (reserved for Ensemble Score), alpha, prediction

**Meta-Learner**:
The layer that combines all Agents' Signals into a single Ensemble Score per Instrument. Not itself an Agent — it does not produce Signals, it produces Weights. Updates its Weights monthly on rolling out-of-sample Information Coefficient.
_Avoid_: PM (ambiguous — the traditional "portfolio manager" role also includes sizing, which we separate), signal combiner, judge

**Portfolio Constructor**:
The layer downstream of the Meta-Learner that turns Ensemble Scores into target Positions, applying position sizing (Kelly-lite), single-name caps (5%), sector caps (25%), and the drawdown gate.
_Avoid_: sizer, allocator, PM

### Composite outputs

**Weight**:
A number in `[0.05, 0.30]` assigned by the Meta-Learner to each Agent, summing to 1.0 across Agents. Updated monthly; reset to equal-weight annually.
_Avoid_: allocation (reserved for Position sizing)

**Ensemble Score**:
The composite number per Instrument produced by the Meta-Learner: a weighted, rank-based aggregation of all Agents' Signals for that Instrument. The input to the Portfolio Constructor.
_Avoid_: composite, alpha, signal (reserved for the raw per-Agent number)

### Market state

**Regime**:
The current market state, computed daily on the Nifty 500 index as a member of `{LOW_VOL_UP_TREND, HIGH_VOL_UP_TREND, LOW_VOL_DOWN_TREND, HIGH_VOL_DOWN_TREND}`. Determines gate evaluation and Kill Switch behavior; does *not* itself modify Signal values.
_Avoid_: market state, regime state, environment

**Universe**:
The set of tradeable Instruments at a given time. Reconstructed quarterly from current Nifty 500 constituents subject to liquidity (>₹5 Cr avg daily turnover), listing history (>3 years), and price (>₹50) filters.
_Avoid_: watchlist, basket

**Instrument**:
A single tradeable security in the Universe, identified by NSE symbol. For v1: equity delivery only, no derivatives.
_Avoid_: stock, ticker, security, asset

### Data

**Training Set**:
The date range `2015-01-01 → 2023-12-31`. Freely accessible for research, iteration, hyperparameter tuning, and backtesting.
_Avoid_: in-sample, backtest data, historical data

**Held-out Set**:
The date range `2024-01-01 → 2026-06-30`, locked from all use during research. Accessed *exactly once* per candidate ensemble for Gate G3 evaluation. Never re-used, never previewed, never tuned against.
_Avoid_: validation set (misleading — implies iteration), test set

**Live Feed**:
Real-time market data during Paper and Live Phases, sourced from broker API (Fyers or Zerodha Kite Connect).
_Avoid_: realtime data, stream

**Point-in-time**:
A property of a data record: reflects what was *known on that date*, not what has been restated since. Fundamentals-based Signals are constrained by the lack of free point-in-time data.
_Avoid_: PIT, historical

### Validation and metrics

**Information Coefficient (IC)**:
The Spearman rank correlation between an Agent's Signals and forward returns over a specified window and Regime. First-class per-Agent, per-Regime measurement; every Agent's IC is tracked continuously.
_Avoid_: correlation, predictive power, edge

**Regime Scorecard**:
The table of IC values for one Agent across all four Regimes. An Agent must show positive IC in at least 3 of 4 Regimes to pass Gate G1.
_Avoid_: performance breakdown, IC table

**Deflated Sharpe Ratio (DSR)**:
Bailey-López de Prado's overfit-corrected Sharpe ratio; penalizes for the number of Agents/configurations tested. Computed on the Ensemble as a whole for Gate G2 and G3. Threshold: > 1.0 net of costs.
_Avoid_: adjusted Sharpe, corrected Sharpe

**Gate**:
A named quantitative checkpoint (G1 through G5) between Phases. Gate failure means returning to the prior Phase, not lowering the threshold or tweaking to pass.
_Avoid_: milestone, checkpoint (too soft), stage

### Phases

**Phase**:
A stage of the strategy lifecycle: `Research → Held-out → Paper → Live-Small → Live-Scale`. Progression is one-directional; regression to a prior Phase is allowed on Gate failure but re-progression must re-clear the Gate.
_Avoid_: stage, step

**Research (Phase)**:
The Phase during which Agents are hypothesized, implemented, and tuned against the Training Set. Gate G1 (per-Agent) and G2 (ensemble) are cleared here.
_Avoid_: backtest phase (ambiguous — backtesting also happens in Held-out)

**Held-out (Phase)**:
A single-shot evaluation Phase where the candidate ensemble is run against the Held-out Set exactly once. Gate G3 pass/fail determines Paper eligibility.
_Avoid_: OOS, validation

**Paper (Phase)**:
Real-time Phase where the system consumes Live Feed and produces Orders that are logged but not sent to the broker. Duration: minimum 3 months before Gate G4.
_Avoid_: simulation, dry-run

**Live-Small (Phase)**:
Real-money Phase with capital limited to ₹50k–₹1L, intended to expose slippage, timing, and psychological risks that Paper cannot. Duration: minimum 12 months before Gate G5.
_Avoid_: pilot, small trade

**Live-Scale (Phase)**:
Real-money Phase with capital sized per the user's discretion, entered only after Gate G5. The system runs in this Phase indefinitely; any material change requires a Contract Amendment.
_Avoid_: production, full-size

### Execution

**Rebalance**:
The atomic decision cycle. On each Rebalance, the system computes current Signals, produces an Ensemble Score per Instrument, compares to current Positions, and emits Orders to close the gap. Cadence: daily to weekly (never intraday).
_Avoid_: cycle, rebalancing (verb form ok)

**Order**:
An instruction sent to the broker (or logged in Paper) to buy or sell a specific quantity of an Instrument. May be filled in whole, in part, or not at all.
_Avoid_: instruction, trade (reserved for round-trip)

**Fill**:
An execution event reported by the broker: quantity, price, timestamp, fees. One Order may produce zero, one, or many Fills.
_Avoid_: execution, transaction

**Position**:
The current net holding of an Instrument (long quantity — v1 has no shorts on names). Aggregated over all past Fills less exits.
_Avoid_: holding, exposure

**Trade**:
A round-trip: a Position opened and later fully closed. Trade P&L is defined; individual Fills do not have P&L until they close a Position.
_Avoid_: round-trip (verbose), transaction

**Slippage**:
The difference between the Ensemble-Score-implied target price at Order emission and the volume-weighted average Fill price. Measured per Rebalance and reported in attribution.
_Avoid_: execution cost, drift

### Safety mechanisms

**Kill Switch**:
An automatic pause of the trading pipeline triggered by a defined condition (drawdown, IC decay, data anomaly, Regime transition to Crisis). Does not require human approval to activate; does require human review to resume.
_Avoid_: circuit breaker, pause

**Contract**:
The `strategy-design-contract.md` document. The source of truth for gates, thresholds, universe rules, and scope constraints. Amended only through the Amendment Protocol (§10 of the Contract).
_Avoid_: spec, design doc

**Attribution**:
The per-Rebalance record of which Agents contributed how much to each Ensemble Score, plus which Signals fired against which Positions. First-class output of every Rebalance; required for post-hoc analysis and Kill Switch investigation.
_Avoid_: explanation, decomposition
