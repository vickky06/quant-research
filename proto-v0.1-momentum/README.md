# v0.1 — 12-1 Momentum Prototype

Throwaway prototype answering **"Can we pass Gate G1 with 12-1 momentum on Nifty 500 (Training Set 2015-2023) using free data?"**

Read `PROTOTYPE_NOTICE.md` first.

## Setup

```bash
cd proto-v0.1-momentum
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python run.py             # full run (Nifty 500 subset — see UNIVERSE below)
python run.py --fast      # quick check on ~50 large-cap names
```

First run downloads ~50-500 tickers × 10 years of daily bars from Yahoo — expect **5-30 minutes**. Data is cached in `./data/prices.duckdb`; subsequent runs are ~10-30 seconds.

## What it does

1. Fetches Nifty 500 constituent list (or a hardcoded large-cap subset in `--fast` mode)
2. Downloads daily OHLC via yfinance
3. Applies Universe filters (liquidity > ₹5 Cr, listing > 3y, price > ₹50)
4. Computes 12-1 momentum Signal per Instrument per Rebalance (monthly)
5. Computes 2×2 Vol×Trend Regime on Nifty index each month
6. Backtests a decile long-short portfolio (top decile long, bottom short, equal weight)
7. Applies 0.20% roundtrip cost per turnover
8. Computes IC (Spearman) overall and per Regime
9. Computes DSR (Bailey-López de Prado PSR; N=1 trial ⇒ PSR ≈ DSR)
10. Evaluates Gate G1 pass/fail

## Output

- `./output/regime_scorecard.json` — IC per Regime table
- `./output/gate_g1_result.json` — Gate G1 verdict + metrics
- `./output/backtest_summary.txt` — human-readable summary
- Console prints `GATE G1: PASS` or `GATE G1: FAIL` with numbers

## Dashboard (visual + interactive)

```bash
streamlit run dashboard.py
```

Opens at `http://localhost:8501`. Five tabs:

- **📖 Glossary** — vocabulary from CONTEXT.md, searchable
- **🌡️ Regime Explorer** — Nifty 50 chart with 2×2 Vol×Trend regime overlay
- **🔍 Signal Explorer** — pick an Instrument, see its momentum rank + price
- **🎛️ Backtest Playground** — tweak lookback, skip, deciles, cost; rerun
- **🚦 Gate Status** — pass/fail badge, regime scorecard bar chart, gate roadmap

The dashboard is read-only over cached data — never re-downloads. If you've never run `python run.py`, the dashboard shows a warning and stops.

## Known limitations

- **Survivorship bias**: uses current Nifty 500 membership (backfilled through history). Free data does not have point-in-time index composition.
- **No point-in-time fundamentals**: not needed for momentum, flagged for future signals.
- **Regime proxy**: Nifty 50 (`^NSEI`) used as market state proxy — Nifty 500 total-return index is not reliably free.
- **Nifty 500 constituent fetch**: uses `nsepython` if available, otherwise falls back to a hardcoded large-cap list.

## After the answer

Once the gate result is known, the validated pure functions (`compute_momentum`, `compute_regime`, `compute_ic`, `compute_dsr`, `compute_gate_g1`) lift into the real codebase. This directory becomes a primary-source snapshot on a throwaway branch.
