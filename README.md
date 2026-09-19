# Quant Trading System

A personal quantitative trading research project targeting Indian equities (Nifty 500), building toward a multi-agent factor-scoring ensemble with strict validation gates.

> **Status**: Research phase — v0.1 prototype (single-signal 12-1 momentum). Not investment advice. See `LICENSE`.

## What's in this repo

| Artifact | Purpose |
|---|---|
| [`strategy-design-contract.md`](strategy-design-contract.md) | **Source of truth.** Gates, thresholds, universe rules, scope. Every decision tests against this. |
| [`CONTEXT.md`](CONTEXT.md) | Domain glossary. Vocabulary for Agent, Signal, Regime, Meta-Learner, etc. |
| [`quant-research.md`](quant-research.md) | Verified primary-source reference on quant systems (factor models, methodology, tooling). |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records — one per non-obvious choice. |
| [`proto-v0.1-momentum/`](proto-v0.1-momentum/) | Working prototype: single-signal 12-1 momentum, backtest + Gate G1 validation + dashboard. |

## Read this before touching code

1. **`strategy-design-contract.md`** — the entire system exists to satisfy this contract. If a proposed change violates it, either the change is rejected or the contract is *explicitly amended and versioned*. Never silently drifted.
2. **`CONTEXT.md`** — vocabulary. Use these terms in code.
3. **`proto-v0.1-momentum/PROTOTYPE_NOTICE.md`** — what the prototype is trying to answer and what it deliberately doesn't do.

## Discipline rules

These are not suggestions. They are what separate this from luck-fitting.

1. **Held-out set is sacred.** Do not touch data from 2024-01-01 to 2026-06-30 during research. One-shot evaluation at Gate G3 only.
2. **Gates gate.** If a gate fails, go back to the previous phase — do not lower the threshold.
3. **Amendment protocol.** Contract changes are versioned and justified in-file, not silently applied.
4. **Attribution is first-class.** Every rebalance in production must be traceable to which Agent contributed what.

## Quick start (prototype)

```bash
cd proto-v0.1-momentum
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Backtest (headless)
python run.py --fast     # ~30 large-caps, 1 min
python run.py            # full Nifty 500, 15–25 min first run

# Dashboard (interactive)
streamlit run dashboard.py
# → http://localhost:8501
```

## Directory layout

```
.
├── README.md                       (this file)
├── LICENSE                          (MIT + disclaimer)
├── .gitignore
├── strategy-design-contract.md     (contract v1.0)
├── CONTEXT.md                       (glossary)
├── quant-research.md                (verified reference)
├── AGENTS.md                        (guidance for AI collaborators)
├── docs/
│   └── adr/
│       └── 0001-universe-exit-force-close.md
└── proto-v0.1-momentum/            (v0.1 prototype)
    ├── PROTOTYPE_NOTICE.md
    ├── README.md
    ├── requirements.txt
    ├── pipeline.py                  (pure logic — signal, regime, backtest, metrics)
    ├── run.py                       (headless entry point)
    ├── run_log.py                   (SQLite audit trail)
    ├── dashboard.py                 (Streamlit UI)
    ├── data/                        (gitignored — cached DuckDB + SQLite)
    └── output/                      (gitignored — per-run JSON + summary)
```

## What's next (roadmap)

Phase-aligned with the contract:

- **v0.1** (current) — 12-1 momentum through Gate G1
- **v0.2** — add 3–5 more signals (quality, low-vol, mean-reversion, sentiment), Meta-Learner combining them, Gate G2
- **v0.3** — held-out validation (single-shot Gate G3)
- **v0.4** — Paper trading via Fyers or Zerodha Kite Connect sandbox
- **v1.0** — Live-Small (₹50k–₹1L)

## Data sources (all free-tier)

- Prices (equity + index): `yfinance` (NSE with `.NS` suffix)
- Nifty 500 constituents: `nsearchives.nseindia.com` CSV
- Macro (later): FRED API for reference, RBI CSVs for India
- No paid feeds, no point-in-time fundamentals

## Contact

Personal project. No external contributions accepted at this stage — but issues, questions, and feedback welcome once the repo is public.
