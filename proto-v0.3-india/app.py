"""India v0.3 Signal Dashboard — Streamlit app.

Run with:
    streamlit run app.py

Tabs:
    Today's Picks — Plain-English buy/sell cards with expected return + hold period
    Data          — DB status, incremental refresh, price chart
    Signals       — Current regime, ranked longs/shorts, per-signal breakdown
    Trades        — Log paper trades, open positions with live P&L
    Performance   — Equity curve, win rate, trade history
    Playground    — Scenario analysis for individual stocks
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "prices.duckdb"          # India default (kept for compat)
TRADES_FILE = ROOT / "output" / "paper_trades.csv"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── market configs ────────────────────────────────────────────────────────────
MARKET_CFG: dict[str, dict] = {
    "india": {
        "label": "🇮🇳 India (Nifty 500)",
        "db_path": ROOT / "data" / "prices.duckdb",
        "index_ticker": "^NSEI",
        "currency": "₹",
        "validated": True,
        "disclaimer": None,
    },
    "us": {
        "label": "🇺🇸 USA (S&P 500)",
        "db_path": ROOT / "data" / "prices_us.duckdb",
        "index_ticker": "^GSPC",
        "currency": "$",
        "validated": False,
        "disclaimer": (
            "⚠️ **US signals are unvalidated** — exploratory use only. "
            "No backtesting has been run on US data. Equal-weight signals "
            "(no regime-conditional weights). Do not use for real trading decisions."
        ),
    },
}

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="India v0.3 — Signal Dashboard",
    page_icon="📊",
    layout="wide",
)

# ── lazy imports (only after path setup) ─────────────────────────────────────
import pipeline as P
from pipeline import (
    AGENTS, EXTRA_SIGNALS, ROUNDTRIP_COST_BPS, compute_regime,
    get_sector_map, get_universe, load_index, load_prices,
)
from run import REGIME_SIGNAL_WEIGHTS, SKIP_REGIMES
from data_refresh import run_refresh
from strategies import STRATEGIES, DEFAULT_STRATEGY


# ══════════════════════════════════════════════════════════════════════════════
# Cached data loaders
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _load_prices_cached(market: str = "india") -> tuple[pd.DataFrame, pd.Series]:
    cfg = MARKET_CFG[market]
    db = cfg["db_path"]
    if not db.exists():
        return pd.DataFrame(), pd.Series(dtype=float)
    prices = load_prices(db)
    index = load_index(db, index_ticker=cfg["index_ticker"])
    return prices, index


@st.cache_data(ttl=300, show_spinner=False)
def _load_signals_cached(market: str = "india") -> tuple:
    prices, index = _load_prices_cached(market)
    if prices.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None

    cutoff = prices["date"].max() - pd.Timedelta(days=400)
    prices = prices[prices["date"] >= cutoff]
    index = index[index.index >= cutoff]

    close = prices.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices.pivot(index="date", columns="symbol", values="volume")
    liq = (close * volume).rolling(60, min_periods=20).mean()

    sector_map = get_sector_map(market=market)
    signals = {
        name: fn(close, index_close=index, sector_map=sector_map, volume=volume)
        for name, fn in AGENTS.items()
    }
    # Compute extra signals (volume_mr etc.) — kept separate from AGENTS to
    # avoid affecting validated backtests in run.py
    for name, fn in EXTRA_SIGNALS.items():
        signals[name] = fn(close, volume=volume)
    regime_df = compute_regime(index)
    latest = close.index.max()
    return signals, close, liq, regime_df, latest


def _get_regime_and_weights(regime_df: pd.DataFrame, latest: pd.Timestamp,
                            market: str = "india", strategy_key: str = DEFAULT_STRATEGY):
    regime = "UNKNOWN"
    if latest in regime_df.index:
        regime = regime_df.loc[latest, "regime"]
    else:
        valid = regime_df.dropna(subset=["regime"])
        if not valid.empty:
            regime = valid.iloc[-1]["regime"]

    strategy = STRATEGIES.get(strategy_key, STRATEGIES[DEFAULT_STRATEGY])

    if strategy["use_regime_weights"] and market == "india":
        raw = dict(REGIME_SIGNAL_WEIGHTS.get(regime, {}))
        if not raw:
            raw = {n: 1 / len(AGENTS) for n in AGENTS}
        raw["volume_mr"] = 0.0   # validated strategy never uses volume_mr
    else:
        raw = dict(strategy["weights"])

    raw = {k: v for k, v in raw.items() if v > 0}
    total = sum(raw.values())
    weights = {k: v / total for k, v in raw.items()} if total else raw
    return regime, weights


def _blend_signals(signals, weights, date, eligible):
    weighted = pd.Series(0.0, index=eligible)
    mass = pd.Series(0.0, index=eligible)
    for name, sig_df in signals.items():
        w = weights.get(name, 0.0)
        if w == 0 or date not in sig_df.index:
            continue
        s = sig_df.loc[date, eligible].dropna()
        weighted.loc[s.index] += s * w
        mass.loc[s.index] += w
    with np.errstate(divide="ignore", invalid="ignore"):
        score = (weighted / mass).replace([np.inf, -np.inf], np.nan).dropna()
    return score.rank(pct=True)


# ══════════════════════════════════════════════════════════════════════════════
# Paper log helpers
# ══════════════════════════════════════════════════════════════════════════════

TRADE_FIELDS = ["id", "symbol", "direction", "qty", "entry_price", "entry_date",
                "exit_price", "exit_date", "pnl", "pnl_pct", "status", "notes"]


def _load_trades() -> pd.DataFrame:
    if not TRADES_FILE.exists():
        return pd.DataFrame(columns=TRADE_FIELDS)
    df = pd.read_csv(TRADES_FILE, dtype=str).fillna("")
    return df


def _save_trades(df: pd.DataFrame) -> None:
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(TRADES_FILE, index=False)


def _next_id(df: pd.DataFrame) -> int:
    if df.empty:
        return 1
    return int(df["id"].astype(int).max()) + 1


def _live_price(symbol: str) -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="2d", interval="1d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Regime colour helper
# ══════════════════════════════════════════════════════════════════════════════

REGIME_COLORS = {
    "LOW_VOL_UP_TREND":    "#2ecc71",
    "HIGH_VOL_UP_TREND":   "#f39c12",
    "HIGH_VOL_DOWN_TREND": "#e74c3c",
    "LOW_VOL_DOWN_TREND":  "#3498db",
    "UNKNOWN":             "#95a5a6",
}


def _regime_badge(regime: str) -> str:
    color = REGIME_COLORS.get(regime, "#95a5a6")
    return f'<span style="background:{color};color:#fff;padding:4px 12px;border-radius:12px;font-weight:600">{regime}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# App layout
# ══════════════════════════════════════════════════════════════════════════════

# ── Sidebar: market selector + glossary ──────────────────────────────────────
with st.sidebar:
    st.markdown("## 🌍 Market")
    _market_labels = [v["label"] for v in MARKET_CFG.values()]
    _selected_label = st.radio(
        "market_radio", _market_labels, index=0, label_visibility="collapsed"
    )
    _market = next(k for k, v in MARKET_CFG.items() if v["label"] == _selected_label)
    st.session_state["market"] = _market

    st.markdown("---")
    st.markdown("## 🧠 Strategy")
    _strategy_key = st.selectbox(
        "strategy_select",
        options=list(STRATEGIES.keys()),
        format_func=lambda k: STRATEGIES[k]["name"],
        index=list(STRATEGIES.keys()).index(DEFAULT_STRATEGY),
        label_visibility="collapsed",
    )
    st.session_state["strategy"] = _strategy_key
    _strat = STRATEGIES[_strategy_key]
    _tag_color = {"Validated": "#2ecc71", "Exploratory": "#3498db", "Experimental": "#e67e22"}
    _tc = _tag_color.get(_strat["tag"], "#95a5a6")
    st.markdown(
        f'<span style="background:{_tc};color:#fff;padding:2px 8px;border-radius:8px;font-size:0.8em">'
        f'{_strat["tag"]}</span>',
        unsafe_allow_html=True,
    )
    st.caption(_strat["description"])
    if _strategy_key == "regime_ensemble" and _market == "us":
        st.warning("Regime weights not validated for US — equal weights used instead.")

    st.markdown("---")
    st.markdown("## 📖 Glossary")
    st.markdown("""
**Regime**
Market environment detected from Nifty 50. Drives which signals get higher weight.
4 regimes: `LOW/HIGH_VOL` × `UP/DOWN_TREND`.

---
**Signal score (0 → 1)**
Percentile rank of a stock across the universe.
`1.0` = ranked #1, `0.0` = ranked last.
≥ 0.90 → long candidate. ≤ 0.10 → short candidate.

---
**mean_reversion**
Stocks that fell significantly relative to their 20-day average are expected to bounce back.
Works best in down-trend regimes.

---
**sector_neutral_mr**
Same as mean-reversion but compares each stock only against peers in its GICS sector.
Removes market-wide sector moves from the signal — e.g. if all IT stocks sold off, it won't flag every IT stock as a bounce candidate.

---
**momentum (12-1)**
Stocks with strong 12-month returns (excluding last month) tend to keep outperforming.
Works best in up-trend regimes.

---
**IC (Information Coefficient)**
Rank correlation between signal score and actual next-period returns. Range −1 to +1.
`IC = 0.05` means the signal explains ~5% of return variation — modest but profitable at scale.

---
**Composite score**
Weighted blend of all 3 signals using regime-conditional weights. This is what the ranked tables show.

---
**R:R (Reward-to-Risk)**
`(Target P&L) ÷ (Stop P&L)`. Aim for ≥ 2x — meaning you expect to make at least twice what you're willing to lose.

---
**DSR (Deflated Sharpe Ratio)**
Sharpe ratio adjusted for the number of strategies tested and non-normality of returns.
More honest than raw Sharpe. DSR ≥ 0.5 means the edge is likely real.

---
**Paper trade**
A simulated trade with no real money. You execute it manually on Zerodha but log it here to track if the algo's signals lead to real profits before committing capital.

---
**Notional**
Total ₹ value of a position = entry price × quantity.

---
**NSE ticker format**
Indian stocks on yfinance use `.NS` suffix: `RELIANCE.NS`, `TCS.NS`.
    """)
    st.markdown("---")
    st.caption("v0.3 · 3-signal ensemble · India validated · US exploratory")


# ── resolve market after sidebar renders ──────────────────────────────────────
market = st.session_state.get("market", "india")
cfg = MARKET_CFG[market]

_flag = "📊" if market == "india" else "🗽"
st.title(f"{_flag} Signal Dashboard — {cfg['label']}")

tab_picks, tab_data, tab_signals, tab_trades, tab_perf, tab_pg, tab_coach = st.tabs(
    ["🎯 Today's Picks", "📁 Data", "📈 Signals", "📝 Trades", "💰 Performance", "🧪 Playground", "🎓 Coach"]
)

if cfg["disclaimer"]:
    st.warning(cfg["disclaimer"])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 0 — Today's Picks  (simple consumer view)
# ══════════════════════════════════════════════════════════════════════════════

with tab_picks:
    _VALIDATED_IC = 0.05   # validated Information Coefficient from India backtests

    if not cfg["db_path"].exists():
        st.warning("No data yet. Go to the **Data** tab and click **Refresh Data**.")
    else:
        with st.spinner("Loading signals…"):
            _picks_result = _load_signals_cached(market)

        if len(_picks_result) != 5 or not _picks_result[0]:
            st.warning("Not enough data. Run data refresh first.")
        else:
            _signals_p, _close_p, _liq_p, _regime_df_p, _latest_p = _picks_result
            _sk = st.session_state.get("strategy", DEFAULT_STRATEGY)
            _strat_p = STRATEGIES.get(_sk, STRATEGIES[DEFAULT_STRATEGY])
            _regime_p, _weights_p = _get_regime_and_weights(
                _regime_df_p, _latest_p, market=market, strategy_key=_sk
            )
            _hold_lo, _hold_hi = _strat_p["hold_days"]
            _currency = cfg["currency"]
            _regime_colour = REGIME_COLORS.get(_regime_p, "#95a5a6")

            # ── Context banner — native Streamlit components ──────────────────
            _b1, _b2, _b3 = st.columns(3)
            _b1.markdown(
                f"**Market**  \n{cfg['label']}"
            )
            _b2.markdown(
                f"**Strategy**  \n"
                f"<span style='background:{_strat_p['color']};color:#fff;"
                f"border-radius:4px;padding:2px 8px;font-size:0.82em'>"
                f"{_strat_p['name']}</span>",
                unsafe_allow_html=True,
            )
            _b3.markdown(
                f"**Market Mood**  \n"
                f"<span style='background:{_regime_colour};color:#fff;"
                f"border-radius:4px;padding:2px 8px;font-size:0.82em'>"
                f"{_regime_p.replace('_', ' ')}</span>",
                unsafe_allow_html=True,
            )
            st.caption(f"{_strat_p['simple_description']}  |  Hold window: **{_hold_lo}–{_hold_hi} days**  |  As of {_latest_p.date()}")
            st.markdown("---")

            if SKIP_REGIMES and _regime_p in SKIP_REGIMES:
                st.error("⚠️ Current market regime is uncertain — strategy would stay flat. No picks today.")
            else:
                # ── Compute ranked scores ─────────────────────────────────────
                _eligible_p = P.per_rebalance_universe(_close_p, _liq_p, _latest_p)
                if len(_eligible_p) < 10:
                    _eligible_p = _close_p.loc[_latest_p].dropna().index.tolist()
                _ranked_p = _blend_signals(_signals_p, _weights_p, _latest_p, _eligible_p)
                _sector_map_p = get_sector_map(market=market)

                _n_picks = st.slider("Number of picks per side", 3, 10, 5, key="picks_n")
                _longs_p  = _ranked_p[_ranked_p >= 0.88].sort_values(ascending=False).head(_n_picks)
                _shorts_p = _ranked_p[_ranked_p <= 0.12].sort_values(ascending=True).head(_n_picks)

                def _expected_return(score: float, ic: float) -> tuple[float, float]:
                    edge = ic * abs(score - 0.5) * 2 * 100
                    return round(edge * 0.6, 1), round(edge * 1.4, 1)

                def _picks_card(sym: str, score: float, direction: str) -> None:
                    sector = _sector_map_p.get(sym, "—")
                    is_long = direction == "long"
                    action_label = "BUY" if is_long else "SHORT / AVOID"
                    action_colour = "#27ae60" if is_long else "#e74c3c"
                    ret_lo, ret_hi = _expected_return(score, _VALIDATED_IC)
                    ret_sign = "+" if is_long else "−"
                    try:
                        _px = float(_close_p.loc[_latest_p, sym])
                        _px_default = round(_px, 2)
                    except Exception:
                        _px = 100.0
                        _px_default = 100.0

                    with st.container(border=True):
                        _ca, _cb = st.columns([3, 1])
                        with _ca:
                            st.markdown(
                                f"**{'📈' if is_long else '📉'} {sym}** &nbsp; "
                                f"<span style='background:{action_colour};color:#fff;"
                                f"border-radius:4px;padding:1px 7px;font-size:0.78em'>{action_label}</span>",
                                unsafe_allow_html=True,
                            )
                            st.caption(f"Sector: {sector}  |  Price: {_currency}{_px:,.2f}")
                        with _cb:
                            st.metric(
                                label=f"Expected ({_hold_lo}–{_hold_hi}d)",
                                value=f"{ret_sign}{ret_hi}%",
                                delta=f"range {ret_lo}–{ret_hi}%",
                                delta_color="normal" if is_long else "inverse",
                            )
                        with st.expander(f"Log paper trade for {sym}"):
                            _c1, _c2, _c3 = st.columns(3)
                            _qty_p = _c1.number_input("Qty", min_value=1, value=10,
                                                      key=f"picks_qty_{sym}_{direction}")
                            _epx_p = _c2.number_input("Entry price", min_value=0.01,
                                                      value=_px_default,
                                                      key=f"picks_epx_{sym}_{direction}")
                            with _c3:
                                st.write("")
                                st.write("")
                                if st.button("Log", key=f"picks_log_{sym}_{direction}"):
                                    _tdf = _load_trades()
                                    _new = {
                                        "id": str(_next_id(_tdf)),
                                        "symbol": sym, "direction": direction,
                                        "qty": str(_qty_p), "entry_price": str(_epx_p),
                                        "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                        "exit_price": "", "exit_date": "", "pnl": "", "pnl_pct": "",
                                        "status": "open",
                                        "notes": (f"picks | score={score:.4f} "
                                                  f"strategy={_sk} target={ret_hi}%"),
                                    }
                                    _tdf = pd.concat([_tdf, pd.DataFrame([_new])], ignore_index=True)
                                    _save_trades(_tdf)
                                    st.success(f"✓ Logged {direction.upper()} {sym}")

                lcol_p, rcol_p = st.columns(2)
                with lcol_p:
                    st.subheader("🟢 Buy")
                    if _longs_p.empty:
                        st.info("No strong buy signals right now.")
                    for _sym, _sc in _longs_p.items():
                        _picks_card(_sym, _sc, "long")

                with rcol_p:
                    st.subheader("🔴 Sell / Avoid")
                    if _shorts_p.empty:
                        st.info("No strong sell signals right now.")
                    for _sym, _sc in _shorts_p.items():
                        _picks_card(_sym, _sc, "short")

                st.caption("Algo signals based on statistical models. Not financial advice. Always verify with fundamentals before acting.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Data
# ══════════════════════════════════════════════════════════════════════════════

with tab_data:
    st.subheader("Price Database")
    with st.expander("ℹ️ How to use this tab", expanded=False):
        st.markdown("""
**Data tab** keeps the local price database up to date. Nothing else in the app works without fresh data.

| Step | What to do |
|---|---|
| 1 | Leave **Interval** as `1d` (daily). The signals were trained on daily bars — intraday is for monitoring only. |
| 2 | Leave **Fast mode** off unless you want a quick test with 50 tickers. |
| 3 | Click **Refresh Data**. A progress bar shows each batch. First run takes ~2 min; subsequent runs only fetch new days (incremental). |
| 4 | Check the metrics row — **Latest date** should be yesterday (NSE data lags ~1 day on yfinance). |

The price chart at the bottom lets you inspect any symbol's history.
        """)


    col1, col2, col3 = st.columns([1, 1, 2])

    interval = col1.selectbox("Interval", ["1d", "1h", "5m", "1m"], index=0)
    fast_mode = col2.checkbox("Fast mode (50 tickers)", value=False)

    if st.button("🔄 Refresh Data", type="primary"):
        _load_prices_cached.clear()
        _load_signals_cached.clear()
        prog = st.progress(0, text="Starting…")
        status = st.empty()
        try:
            def _on_progress(fraction: float, msg: str) -> None:
                prog.progress(min(fraction, 1.0), text=msg)
                status.caption(msg)

            run_refresh(interval=interval, fast=fast_mode, on_progress=_on_progress,
                        market=market, db_path=cfg["db_path"])
            prog.progress(1.0, text="Done!")
            status.empty()
            _load_prices_cached.clear()
            _load_signals_cached.clear()
            st.success("Data refreshed — reload the Signals tab to see updated ranks.")
        except Exception as exc:
            prog.empty()
            st.error(f"Refresh failed: {exc}")

    # DB stats
    if cfg["db_path"].exists():
        prices, index = _load_prices_cached(market)
        if not prices.empty:
            st.markdown("---")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total price rows", f"{len(prices):,}")
            m2.metric("Symbols", f"{prices['symbol'].nunique():,}")
            m3.metric("Earliest date", str(prices["date"].min().date()))
            m4.metric("Latest date", str(prices["date"].max().date()))

            # Symbol price chart
            st.markdown("---")
            st.subheader("Price Chart")
            symbols_available = sorted(prices["symbol"].unique().tolist())
            default_sym = "RELIANCE.NS" if market == "india" else "AAPL"
            sel_sym = st.selectbox("Symbol", symbols_available,
                                   index=symbols_available.index(default_sym)
                                   if default_sym in symbols_available else 0)
            sym_df = prices[prices["symbol"] == sel_sym].sort_values("date")
            if not sym_df.empty:
                fig = px.line(sym_df, x="date", y="adj_close",
                              title=f"{sel_sym} — Adjusted Close",
                              labels={"adj_close": f"Price ({cfg['currency']})", "date": ""})
                fig.update_layout(height=350, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No database found. Click **Refresh Data** to download prices.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Signals
# ══════════════════════════════════════════════════════════════════════════════

with tab_signals:
    with st.expander("ℹ️ How to use this tab", expanded=False):
        st.markdown("""
**Signals tab** is the algo output — what the model thinks you should be long or short today.

**Reading the regime:**
The coloured badge shows the current market regime detected from Nifty 50 volatility + trend.
The regime determines which signals get more weight:
- 🔵 `LOW_VOL_DOWN_TREND` / 🔴 `HIGH_VOL_DOWN_TREND` → Mean-reversion heavy (stocks that fell hard tend to bounce)
- 🟢 `LOW_VOL_UP_TREND` / 🟠 `HIGH_VOL_UP_TREND` → Momentum heavy (recent winners keep winning)

**Reading the scores (0 → 1):**
Each stock gets a percentile score across the universe. Score = 1.0 means it ranked #1 across all three signals.
- **≥ 0.90** → strong long candidate
- **≤ 0.10** → strong short candidate
- Scores near 0.5 → no edge, ignore

**Practical workflow:**
1. Check the regime — if `SKIP` is shown, the model has low confidence and you should stay flat.
2. Scan the top 5–10 longs and shorts. Cross-check with news/fundamentals before acting.
3. Use the **Playground tab** to simulate a position before committing to a paper trade.
4. The **Per-signal breakdown** expander shows which of the 3 signals drove each stock's rank.
        """)

    if not cfg["db_path"].exists():
        st.warning("Run data refresh first.")
    else:
        if st.button("🔁 Recompute Signals"):
            _load_signals_cached.clear()

        with st.spinner("Loading signals..."):
            result = _load_signals_cached(market)

        if len(result) == 5:
            signals, close, liq, regime_df, latest = result
        else:
            signals, close, liq, regime_df, latest = {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None

        if not signals or latest is None:
            st.warning("Not enough data. Run data_refresh.py first.")
        else:
            strategy_key = st.session_state.get("strategy", DEFAULT_STRATEGY)
            regime, weights = _get_regime_and_weights(regime_df, latest, market=market, strategy_key=strategy_key)

            # Header row
            hcol1, hcol2 = st.columns([2, 3])
            with hcol1:
                st.markdown("**Current Regime**")
                st.markdown(_regime_badge(regime), unsafe_allow_html=True)
                st.caption(f"As of {latest.date()}")
                strat_info = STRATEGIES.get(strategy_key, STRATEGIES[DEFAULT_STRATEGY])
                st.markdown(
                    f"**Strategy:** {strat_info['name']} "
                    f"<span style='background:{strat_info['color']};color:#fff;"
                    f"border-radius:4px;padding:1px 6px;font-size:0.75em'>"
                    f"{strat_info['tag']}</span>",
                    unsafe_allow_html=True,
                )
                gated = SKIP_REGIMES and regime in SKIP_REGIMES
                if gated:
                    st.error("⚠️ This regime is in the skip list — strategy would be FLAT")

            with hcol2:
                st.markdown("**Signal Weights**")
                wdf = pd.DataFrame({
                    "Signal": list(weights.keys()),
                    "Weight": [f"{v:.1%}" for v in weights.values()],
                    "Bar": list(weights.values()),
                })
                fig_w = px.bar(wdf, x="Signal", y="Bar", text="Weight",
                               color="Signal", height=180)
                fig_w.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0),
                                    yaxis_title="", xaxis_title="")
                fig_w.update_traces(textposition="outside")
                st.plotly_chart(fig_w, use_container_width=True)

            st.markdown("---")

            # Regime history chart
            with st.expander("Regime history (last 12 months)"):
                recent_regime = regime_df.dropna(subset=["regime"]).tail(252)
                if not recent_regime.empty:
                    regime_colors_list = [REGIME_COLORS.get(r, "#95a5a6")
                                          for r in recent_regime["regime"]]
                    fig_r = go.Figure(go.Scatter(
                        x=recent_regime.index, y=[1] * len(recent_regime),
                        mode="markers",
                        marker=dict(color=regime_colors_list, size=8, symbol="square"),
                        text=recent_regime["regime"],
                        hoverinfo="text+x",
                    ))
                    fig_r.update_layout(height=100, showlegend=False,
                                        yaxis=dict(visible=False),
                                        margin=dict(l=0, r=0, t=10, b=0))
                    st.plotly_chart(fig_r, use_container_width=True)

            # Ranked positions
            top_n = st.slider("Positions per side", 5, 50, 20)
            eligible = P.per_rebalance_universe(close, liq, latest)
            if len(eligible) < 10:
                eligible = close.loc[latest].dropna().index.tolist()

            ranked = _blend_signals(signals, weights, latest, eligible)
            sector_map = get_sector_map(market=market)

            top_cut = 1.0 - 1.0 / 10
            bot_cut = 1.0 / 10
            longs_s = ranked[ranked >= top_cut].sort_values(ascending=False).head(top_n)
            shorts_s = ranked[ranked <= bot_cut].sort_values(ascending=True).head(top_n)

            lcol, rcol = st.columns(2)

            with lcol:
                st.markdown("### 🟢 Longs")
                ldf = pd.DataFrame({
                    "Symbol": longs_s.index,
                    "Score": longs_s.values.round(4),
                    "Sector": [sector_map.get(s, "—") for s in longs_s.index],
                })
                st.dataframe(ldf, use_container_width=True, hide_index=True,
                             column_config={"Score": st.column_config.ProgressColumn(
                                 min_value=0.8, max_value=1.0, format="%.4f")})

            with rcol:
                st.markdown("### 🔴 Shorts")
                sdf = pd.DataFrame({
                    "Symbol": shorts_s.index,
                    "Score": shorts_s.values.round(4),
                    "Sector": [sector_map.get(s, "—") for s in shorts_s.index],
                })
                st.dataframe(sdf, use_container_width=True, hide_index=True,
                             column_config={"Score": st.column_config.ProgressColumn(
                                 min_value=0.0, max_value=0.2, format="%.4f")})

            # Per-signal breakdown
            with st.expander("Per-signal scores at latest date"):
                rows = []
                for name, sig_df in signals.items():
                    if latest in sig_df.index:
                        vals = sig_df.loc[latest, eligible].dropna()
                        rows.append({"Signal": name, "n": len(vals),
                                     "Mean": round(vals.mean(), 4),
                                     "Std": round(vals.std(), 4),
                                     "Weight": f"{weights.get(name, 0):.1%}"})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Trades
# ══════════════════════════════════════════════════════════════════════════════

with tab_trades:
    with st.expander("ℹ️ How to use this tab", expanded=False):
        st.markdown("""
**Trades tab** is your paper trading journal. No broker connection needed — you record trades manually after executing them yourself on Zerodha.

**Entering a trade:**
1. Pick a symbol from the dropdown (275 NSE stocks) or choose "Type custom" for anything else.
2. Set **Direction**: Long = you bought it expecting it to rise. Short = you sold/shorted expecting it to fall.
3. Enter the **actual price you paid** on Zerodha (not the signal price).
4. **Quantity** = number of shares.
5. Click **Enter Trade**. The trade is saved locally to `output/paper_trades.csv`.

**Open positions panel:**
- Live price is fetched from yfinance every time the page loads.
- **Unrealised P&L** = (live price − entry price) × qty (for longs), reversed for shorts.

**Closing a trade:**
1. After you sell/cover on Zerodha, come back here.
2. In the **Close a position** section, pick the symbol and enter your actual exit price.
3. P&L is calculated and recorded permanently.

**Tips:**
- Use **Notes** to record why you took the trade (e.g. "pg#2 score=0.984 regime=LOW_VOL_DOWN")
- Trades promoted from the Playground tab auto-fill the notes with the signal metadata.
        """)

    trades_df = _load_trades()
    open_df = trades_df[trades_df["status"] == "open"] if not trades_df.empty else pd.DataFrame()

    # ── Enter trade ──────────────────────────────────────────────────────────
    with st.expander("➕ Enter new position", expanded=open_df.empty):
        universe_syms = sorted(get_universe(market=market))
        CUSTOM_OPT = "✏️  Type custom symbol below..."
        sym_options = universe_syms + [CUSTOM_OPT]

        with st.form("enter_trade"):
            c1, c2, c3, c4 = st.columns(4)
            sym_sel = c1.selectbox("Symbol (universe)", sym_options,
                                   help="Start typing to filter. Choose last option to enter any ticker.")
            sym_custom = c1.text_input("Custom symbol", placeholder="e.g. NIFTY50.NS",
                                       help="Used only when 'Type custom' is selected above.")
            direction = c2.selectbox("Direction", ["long", "short"])
            qty = c3.number_input("Quantity", min_value=1, value=100, step=1)
            price = c4.number_input(f"Entry price ({cfg['currency']})", min_value=0.01, value=100.0, step=0.05)
            notes = st.text_input("Notes (optional)")
            submitted = st.form_submit_button("Enter Trade", type="primary")

            if submitted:
                sym = (sym_custom.strip().upper()
                       if sym_sel == CUSTOM_OPT
                       else sym_sel)
                if not sym:
                    st.error("Symbol is required — pick from list or enter a custom symbol.")
                else:
                    # Validate ticker has price data
                    live = _live_price(sym)
                    if live is None and sym not in universe_syms:
                        st.warning(
                            f"⚠️ Could not fetch a live price for **{sym}**. "
                            "Double-check the ticker (NSE symbols end in `.NS`). "
                            "Trade logged anyway — P&L will show '—' until data is available."
                        )
                    trades_df = _load_trades()
                    new_row = {
                        "id": str(_next_id(trades_df)),
                        "symbol": sym, "direction": direction,
                        "qty": str(qty), "entry_price": str(price),
                        "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "exit_price": "", "exit_date": "", "pnl": "",
                        "pnl_pct": "", "status": "open", "notes": notes,
                    }
                    trades_df = pd.concat(
                        [trades_df, pd.DataFrame([new_row])], ignore_index=True
                    )
                    _save_trades(trades_df)
                    price_str = f"{cfg['currency']}{live:.2f} live" if live else f"{cfg['currency']}{price:.2f} manual"
                    st.success(f"Entered {direction.upper()} {qty}× {sym} @ {price_str}")
                    st.rerun()

    # ── Open positions ────────────────────────────────────────────────────────
    st.subheader("Open Positions")
    trades_df = _load_trades()
    open_df = trades_df[trades_df["status"] == "open"].copy() if not trades_df.empty else pd.DataFrame()

    if open_df.empty:
        st.info("No open positions.")
    else:
        rows = []
        total_unreal = 0.0
        for _, t in open_df.iterrows():
            live = _live_price(t["symbol"])
            entry = float(t["entry_price"])
            qty_v = int(t["qty"])
            if live:
                pnl = (live - entry) * qty_v if t["direction"] == "long" else (entry - live) * qty_v
                pnl_pct = (live / entry - 1) * (1 if t["direction"] == "long" else -1) * 100
                total_unreal += pnl
            else:
                pnl = pnl_pct = None
            rows.append({
                "ID": t["id"], "Symbol": t["symbol"], "Dir": t["direction"],
                "Qty": qty_v, f"Entry {cfg['currency']}": entry,
                f"Live {cfg['currency']}": round(live, 2) if live else "—",
                f"P&L {cfg['currency']}": round(pnl, 0) if pnl is not None else "—",
                "P&L %": round(pnl_pct, 2) if pnl_pct is not None else "—",
                "Since": t["entry_date"][:10],
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.metric("Unrealised P&L", f"{cfg['currency']}{total_unreal:+,.0f}")

        # ── Close position ────────────────────────────────────────────────────
        with st.expander("✅ Close a position"):
            with st.form("close_trade"):
                open_syms = open_df["symbol"].tolist()
                close_sym = st.selectbox("Symbol to close", open_syms)
                exit_price = st.number_input(f"Exit price ({cfg['currency']})", min_value=0.01, value=100.0, step=0.05)
                close_notes = st.text_input("Notes (optional)")
                close_sub = st.form_submit_button("Close Position", type="primary")

                if close_sub:
                    trades_df = _load_trades()
                    mask = (trades_df["symbol"] == close_sym) & (trades_df["status"] == "open")
                    idx = trades_df[mask].index
                    if len(idx) == 0:
                        st.error("Position not found")
                    else:
                        i = idx[-1]
                        entry_p = float(trades_df.at[i, "entry_price"])
                        qty_v = int(trades_df.at[i, "qty"])
                        dirn = trades_df.at[i, "direction"]
                        pnl = (exit_price - entry_p) * qty_v if dirn == "long" else (entry_p - exit_price) * qty_v
                        pnl_pct = (exit_price / entry_p - 1) * (1 if dirn == "long" else -1) * 100
                        trades_df.at[i, "exit_price"] = str(exit_price)
                        trades_df.at[i, "exit_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                        trades_df.at[i, "pnl"] = str(round(pnl, 2))
                        trades_df.at[i, "pnl_pct"] = str(round(pnl_pct, 2))
                        trades_df.at[i, "status"] = "closed"
                        if close_notes:
                            trades_df.at[i, "notes"] = close_notes
                        _save_trades(trades_df)
                        emoji = "✓" if pnl >= 0 else "✗"
                        st.success(f"{emoji} Closed {dirn.upper()} {qty_v}× {close_sym} — P&L {cfg['currency']}{pnl:+,.0f} ({pnl_pct:+.2f}%)")
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Performance
# ══════════════════════════════════════════════════════════════════════════════

with tab_perf:
    with st.expander("ℹ️ How to use this tab", expanded=False):
        st.markdown("""
**Performance tab** tracks your closed paper trades over time. Only trades you have entered AND closed appear here.

| Metric | What it means |
|---|---|
| **Total P&L** | Sum of all realised profits and losses in ₹ |
| **Win rate** | % of trades that closed in profit |
| **Avg win / Avg loss** | Average profit on winners vs average loss on losers |
| **R:R implied** | Avg win ÷ Avg loss — target > 1.5x |

**Equity curve** — cumulative P&L over time. A rising line means the strategy is working in practice.

**Goal of paper trading:** Run at least 6 months (≈ 6 monthly rebalances) before committing real capital.
Watch for: consistent win rate ≥ 50%, R:R > 1.5x, no single trade losing more than 10% of notional.
        """)

    trades_df = _load_trades()
    closed_df = trades_df[trades_df["status"] == "closed"].copy() if not trades_df.empty else pd.DataFrame()

    if closed_df.empty:
        st.info("No closed trades yet. Enter and close some paper trades to see performance.")
    else:
        closed_df["pnl"] = pd.to_numeric(closed_df["pnl"], errors="coerce").fillna(0)
        closed_df["pnl_pct"] = pd.to_numeric(closed_df["pnl_pct"], errors="coerce").fillna(0)
        closed_df["exit_date"] = pd.to_datetime(closed_df["exit_date"], errors="coerce")
        closed_df = closed_df.sort_values("exit_date")

        total_pnl = closed_df["pnl"].sum()
        winners = (closed_df["pnl"] > 0).sum()
        win_rate = winners / len(closed_df)
        avg_win = closed_df[closed_df["pnl"] > 0]["pnl"].mean() if winners > 0 else 0
        avg_loss = closed_df[closed_df["pnl"] < 0]["pnl"].mean() if (closed_df["pnl"] < 0).any() else 0

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total P&L", f"{cfg['currency']}{total_pnl:+,.0f}")
        m2.metric("Trades", len(closed_df))
        m3.metric("Win rate", f"{win_rate:.1%}")
        m4.metric("Avg win", f"{cfg['currency']}{avg_win:+,.0f}")
        m5.metric("Avg loss", f"{cfg['currency']}{avg_loss:+,.0f}")

        # Equity curve
        closed_df["cumulative_pnl"] = closed_df["pnl"].cumsum()
        fig_eq = px.area(
            closed_df, x="exit_date", y="cumulative_pnl",
            title=f"Cumulative P&L ({cfg['currency']})",
            labels={"cumulative_pnl": f"Cumulative P&L ({cfg['currency']})", "exit_date": ""},
            color_discrete_sequence=["#2ecc71"] if total_pnl >= 0 else ["#e74c3c"],
        )
        fig_eq.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_eq, use_container_width=True)

        # Per-trade bar chart
        colors = ["#2ecc71" if p >= 0 else "#e74c3c" for p in closed_df["pnl"]]
        fig_bar = go.Figure(go.Bar(
            x=closed_df["symbol"] + " (" + closed_df["direction"] + ")",
            y=closed_df["pnl"],
            marker_color=colors,
            text=[f"{cfg['currency']}{p:+,.0f}" for p in closed_df["pnl"]],
            textposition="outside",
        ))
        fig_bar.update_layout(title="P&L per trade", height=300,
                              margin=dict(l=0, r=0, t=40, b=0),
                              xaxis_tickangle=-30)
        st.plotly_chart(fig_bar, use_container_width=True)

        # Trade history table
        st.subheader("Trade History")
        display_cols = ["symbol", "direction", "qty", "entry_price",
                        "exit_price", "pnl", "pnl_pct", "exit_date", "notes"]
        st.dataframe(
            closed_df[display_cols].rename(columns={
                "symbol": "Symbol", "direction": "Dir", "qty": "Qty",
                "entry_price": f"Entry {cfg['currency']}", "exit_price": f"Exit {cfg['currency']}",
                "pnl": f"P&L {cfg['currency']}", "pnl_pct": "P&L %",
                "exit_date": "Date", "notes": "Notes",
            }),
            use_container_width=True, hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — Playground
# ══════════════════════════════════════════════════════════════════════════════

# Historical IC estimates per regime (from training + held-out)
_REGIME_IC: dict[str, float] = {
    "LOW_VOL_UP_TREND":    0.055,
    "HIGH_VOL_UP_TREND":   0.009,
    "HIGH_VOL_DOWN_TREND": 0.051,
    "LOW_VOL_DOWN_TREND":  0.035,
    "UNKNOWN":             0.025,
}

with tab_pg:
    st.subheader("Signal Playground")
    with st.expander("ℹ️ How to use this tab", expanded=False):
        st.markdown("""
**Playground tab** lets you simulate trades before committing to the real paper trade journal.
It seeds scenarios directly from the algo's current signal rankings.

**Step-by-step:**
1. Choose **3 or 6 scenarios** and click **Generate Playground**.
   - Top half = long candidates (highest composite scores)
   - Bottom half = short candidates (lowest composite scores)
2. Each card shows:
   - **Signal breakdown table** — how each of the 3 signals scored this stock and how much it contributed.
     A stock ranked 95th percentile by mean-reversion gets `Rank % = 95%`. Multiply by weight to get contribution.
   - **IC-implied target** — based on historical Information Coefficient for the current regime.
     IC = 0.055 in LOW_VOL_UP_TREND means the model's picks historically moved ~5% in the right direction over 20 days.
   - **Stop price** — default 3% against you. Adjust to your risk tolerance.
3. Edit **Entry, Target, Stop, Qty, Hold days** — the **At target** and **At stop** P&L update instantly.
4. Check **R:R** (reward-to-risk). Aim for ≥ 2x before promoting.
5. Click **→ Promote to Paper Trade** on the best scenario. It moves to the Trades tab with signal metadata in Notes.

**Scenarios are session-only** — they reset on page refresh. Use the Trades tab for real tracking.
        """)


    pg_n = st.selectbox("Scenarios to generate", [3, 6], index=1, key="pg_n_select")
    if st.button("🎲 Generate Playground", type="primary"):
        result = _load_signals_cached(market)
        if len(result) == 5:
            signals_pg, close_pg, liq_pg, regime_df_pg, latest_pg = result
        else:
            signals_pg, close_pg, liq_pg, latest_pg = result[0], result[1], result[2], result[3]
            regime_df_pg = pd.DataFrame()

        regime_pg, weights_pg = _get_regime_and_weights(regime_df_pg, latest_pg, market=market,
                                                         strategy_key=st.session_state.get("strategy", DEFAULT_STRATEGY))
        eligible_pg = P.per_rebalance_universe(close_pg, liq_pg, latest_pg)
        if len(eligible_pg) < 10:
            eligible_pg = close_pg.loc[latest_pg].dropna().index.tolist()

        ranked_pg = _blend_signals(signals_pg, weights_pg, latest_pg, eligible_pg)
        top_cut = 1.0 - 1.0 / 10
        bot_cut = 1.0 / 10
        longs_pg = ranked_pg[ranked_pg >= top_cut].sort_values(ascending=False)
        shorts_pg = ranked_pg[ranked_pg <= bot_cut].sort_values(ascending=True)

        n_each = pg_n // 2
        picks = (
            [(s, "long", sc) for s, sc in longs_pg.head(n_each).items()] +
            [(s, "short", sc) for s, sc in shorts_pg.head(n_each).items()]
        )

        ic_est = _REGIME_IC.get(regime_pg, 0.025)
        sector_map_pg = get_sector_map(market=market)
        scenarios: list[dict] = []

        for sym, direction, composite_score in picks:
            live = _live_price(sym)
            entry = (live if live
                     else float(close_pg.loc[latest_pg, sym]) if sym in close_pg.columns
                     else 100.0)

            # Per-signal breakdown: rank each signal independently within eligible
            breakdown: dict[str, dict] = {}
            for sig_name, sig_df in signals_pg.items():
                if latest_pg in sig_df.index and sym in sig_df.columns:
                    raw_val = float(sig_df.loc[latest_pg, sym])
                    vals = sig_df.loc[latest_pg, eligible_pg].dropna()
                    pct_rank = float((vals < raw_val).sum() / len(vals)) if len(vals) > 0 else 0.5
                else:
                    pct_rank = 0.5
                w = weights_pg.get(sig_name, 0.0)
                breakdown[sig_name] = {"rank": pct_rank, "weight": w,
                                       "contribution": round(pct_rank * w, 4)}

            # IC-implied target: top-decile stock in current IC regime
            target_pct = ic_est * composite_score * 2.0 * 100
            target_pct = round(min(max(target_pct, 1.5), 15.0), 1)

            sign = 1 if direction == "long" else -1
            target = round(entry * (1 + sign * target_pct / 100), 2)
            stop   = round(entry * (1 - sign * 0.03), 2)          # default 3% stop

            scenarios.append({
                "sym": sym,
                "sector": sector_map_pg.get(sym, "—"),
                "direction": direction,
                "composite_score": composite_score,
                "breakdown": breakdown,
                "entry_price": entry,
                "target_price": target,
                "stop_price": stop,
                "qty": 100,
                "hold_days": 20,
                "regime": regime_pg,
                "ic_est": ic_est,
                "target_pct": target_pct,
            })

        st.session_state["pg_scenarios"] = scenarios
        st.session_state["pg_regime"] = regime_pg
        st.rerun()

    # ── Render cards ────────────────────────────────────────────────────────
    if not st.session_state.get("pg_scenarios"):
        st.info("Click **Generate Playground** above to seed scenarios from current signals.")
    else:
        scenarios = st.session_state["pg_scenarios"]
        regime_pg = st.session_state.get("pg_regime", "UNKNOWN")

        st.markdown(
            f"Seeded from regime: {_regime_badge(regime_pg)} "
            f"&nbsp;|&nbsp; IC estimate: **{_REGIME_IC.get(regime_pg, 0.025):.3f}**",
            unsafe_allow_html=True,
        )
        st.markdown("")

        comparison_rows: list[dict] = []

        for row_start in range(0, len(scenarios), 3):
            cols = st.columns(3)
            for col_offset in range(3):
                sc_idx = row_start + col_offset
                if sc_idx >= len(scenarios):
                    break
                pg = scenarios[sc_idx]
                with cols[col_offset]:
                    dir_emoji = "🟢" if pg["direction"] == "long" else "🔴"
                    st.markdown(
                        f"**{dir_emoji} Scenario #{sc_idx + 1}**<br>"
                        f"<span style='font-size:1.1em;font-weight:700'>{pg['sym']}</span>"
                        f"&nbsp;<span style='color:grey;font-size:0.85em'>{pg['sector']}</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(
                        f"Composite score: **{pg['composite_score']:.4f}** | "
                        f"{pg['direction'].upper()} | "
                        f"IC-implied target: +{pg['target_pct']:.1f}%"
                    )

                    # Signal breakdown mini-table
                    bd_rows = [
                        {
                            "Signal": name.replace("_", " "),
                            "Rank %": f"{bd['rank']:.0%}",
                            "Weight": f"{bd['weight']:.0%}",
                            "Contribution": f"{bd['contribution']:.3f}",
                        }
                        for name, bd in pg["breakdown"].items()
                    ]
                    st.dataframe(pd.DataFrame(bd_rows), use_container_width=True,
                                 hide_index=True, height=135)

                    # Editable params
                    entry  = st.number_input(f"Entry {cfg['currency']}",  value=float(pg["entry_price"]),
                                             step=1.0, format="%.2f", key=f"pg_{sc_idx}_entry")
                    target = st.number_input(f"Target {cfg['currency']}", value=float(pg["target_price"]),
                                             step=1.0, format="%.2f", key=f"pg_{sc_idx}_target")
                    stop   = st.number_input(f"Stop {cfg['currency']}",   value=float(pg["stop_price"]),
                                             step=1.0, format="%.2f", key=f"pg_{sc_idx}_stop")
                    qty    = st.number_input("Qty",       value=int(pg["qty"]),
                                             min_value=1, step=10, key=f"pg_{sc_idx}_qty")
                    hold   = st.number_input("Hold days", value=int(pg["hold_days"]),
                                             min_value=1, max_value=365, step=5,
                                             key=f"pg_{sc_idx}_hold")

                    # Live P&L
                    sign = 1 if pg["direction"] == "long" else -1
                    pnl_tgt  = (target - entry) * sign * qty
                    pnl_stop = (stop   - entry) * sign * qty
                    ret_tgt  = (target / entry - 1) * sign * 100 if entry else 0
                    ret_stop = (stop   / entry - 1) * sign * 100 if entry else 0
                    rr = abs(pnl_tgt / pnl_stop) if pnl_stop != 0 else 0.0

                    mc1, mc2 = st.columns(2)
                    mc1.metric("↑ At target",  f"{cfg['currency']}{pnl_tgt:+,.0f}",  f"{ret_tgt:+.1f}%")
                    mc2.metric("↓ At stop",    f"{cfg['currency']}{pnl_stop:+,.0f}", f"{ret_stop:+.1f}%")
                    st.caption(
                        f"R:R = **{rr:.1f}x** &nbsp;|&nbsp; "
                        f"Notional {cfg['currency']}{entry * qty:,.0f} &nbsp;|&nbsp; "
                        f"Hold {hold}d",
                        unsafe_allow_html=True,
                    )

                    if st.button("→ Promote to Paper Trade", key=f"pg_{sc_idx}_promote"):
                        trades_df = _load_trades()
                        new_row = {
                            "id": str(_next_id(trades_df)),
                            "symbol": pg["sym"], "direction": pg["direction"],
                            "qty": str(qty), "entry_price": str(entry),
                            "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "exit_price": "", "exit_date": "", "pnl": "", "pnl_pct": "",
                            "status": "open",
                            "notes": (f"playground #{sc_idx+1} | score={pg['composite_score']:.4f} "
                                      f"| strategy={st.session_state.get('strategy', DEFAULT_STRATEGY)} "
                                      f"| target={target} | stop={stop}"),
                        }
                        trades_df = pd.concat([trades_df, pd.DataFrame([new_row])], ignore_index=True)
                        _save_trades(trades_df)
                        st.success(f"✓ {pg['sym']} promoted — check the Trades tab.")

                    comparison_rows.append({
                        "#": sc_idx + 1,
                        "Symbol": pg["sym"],
                        "Dir": pg["direction"].upper(),
                        "Score": f"{pg['composite_score']:.4f}",
                        f"Entry {cfg['currency']}": f"{entry:,.2f}",
                        f"Target {cfg['currency']}": f"{target:,.2f}",
                        f"Stop {cfg['currency']}": f"{stop:,.2f}",
                        "Qty": qty,
                        "P&L @ tgt": f"{cfg['currency']}{pnl_tgt:+,.0f}",
                        "Return": f"{ret_tgt:+.1f}%",
                        "R:R": f"{rr:.1f}x",
                    })

            st.markdown("---")

        # ── Comparison table ────────────────────────────────────────────────
        st.subheader("Side-by-side comparison")
        if comparison_rows:
            st.dataframe(pd.DataFrame(comparison_rows), use_container_width=True, hide_index=True)

        if st.button("🗑️ Clear Playground"):
            for _k in [k for k in st.session_state if k.startswith("pg_")]:
                del st.session_state[_k]
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 7 — Coach
# ══════════════════════════════════════════════════════════════════════════════

with tab_coach:
    try:
        import coach as _coach
        _coach_available = True
    except ImportError:
        _coach_available = False

    if not _coach_available:
        st.error("coach.py not found in the same directory as app.py.")
        st.stop()

    # ── Check API key ─────────────────────────────────────────────────────────
    import os as _os
    if not _os.environ.get("ANTHROPIC_API_KEY"):
        st.warning(
            "**ANTHROPIC_API_KEY not set.**  \n"
            "Run the app with the key exported, e.g.:  \n"
            "`ANTHROPIC_API_KEY=sk-ant-... streamlit run app.py`  \n"
            "Or add it to a `.env` file in this folder."
        )
        st.stop()

    # ── Build live context for the coach ─────────────────────────────────────
    _ck_market  = st.session_state.get("market", "india")
    _ck_cfg     = MARKET_CFG[_ck_market]
    _ck_sk      = st.session_state.get("strategy", DEFAULT_STRATEGY)
    _ck_strat   = STRATEGIES.get(_ck_sk, STRATEGIES[DEFAULT_STRATEGY])

    _ck_longs, _ck_shorts, _ck_regime = [], [], "UNKNOWN"
    try:
        _ck_result = _load_signals_cached(_ck_market)
        if len(_ck_result) == 5 and _ck_result[0]:
            _ck_sigs, _ck_close, _ck_liq, _ck_rdf, _ck_latest = _ck_result
            _ck_regime, _ck_w = _get_regime_and_weights(_ck_rdf, _ck_latest,
                                                         market=_ck_market, strategy_key=_ck_sk)
            _ck_elig = P.per_rebalance_universe(_ck_close, _ck_liq, _ck_latest)
            if len(_ck_elig) < 10:
                _ck_elig = _ck_close.loc[_ck_latest].dropna().index.tolist()
            _ck_ranked = _blend_signals(_ck_sigs, _ck_w, _ck_latest, _ck_elig)
            _ck_longs  = list(_ck_ranked[_ck_ranked >= 0.88]
                              .sort_values(ascending=False).head(5).items())
            _ck_shorts = list(_ck_ranked[_ck_ranked <= 0.12]
                              .sort_values(ascending=True).head(5).items())
    except Exception:
        pass

    # Paper trade summary for context
    _ck_tdf = _load_trades()
    if _ck_tdf.empty:
        _ck_trade_summary = "No paper trades logged yet."
    else:
        _open   = _ck_tdf[_ck_tdf["status"] == "open"]
        _closed = _ck_tdf[_ck_tdf["status"] == "closed"]
        _wins   = sum(1 for _, r in _closed.iterrows() if r["pnl"] and float(r["pnl"]) > 0)
        _total  = len(_closed)
        _win_rate = f"{_wins}/{_total}" if _total else "0/0"
        _recent = _closed.tail(3)[["symbol", "direction", "pnl", "pnl_pct"]].to_string(index=False) if not _closed.empty else "none"
        _ck_trade_summary = (
            f"Open positions: {len(_open)}\n"
            f"Closed trades: {_total}  Win rate: {_win_rate}\n"
            f"Last 3 closed trades:\n{_recent}"
        )

    _ck_context = _coach.build_context(
        regime=_ck_regime,
        strategy_name=_ck_strat["name"],
        longs=_ck_longs,
        shorts=_ck_shorts,
        trade_summary=_ck_trade_summary,
        currency=_ck_cfg["currency"],
        date=str(pd.Timestamp.today().date()),
        market=_ck_market,
    )

    # ── Session state init ────────────────────────────────────────────────────
    if "coach_messages" not in st.session_state:
        st.session_state["coach_messages"] = []
    if "coach_mode" not in st.session_state:
        st.session_state["coach_mode"] = None

    # ── Mode selector ─────────────────────────────────────────────────────────
    st.markdown("### 🎓 Trading Coach")
    st.caption("Pick a mode to start. The coach knows your live signals, regime, and paper trade history.")

    _m1, _m2, _m3, _m_reset = st.columns([2, 2, 2, 1])

    def _set_coach_mode(mode: str, kick_off: str) -> None:
        st.session_state["coach_messages"] = []
        st.session_state["coach_mode"] = mode
        # Send the kick-off as the first assistant message
        with st.spinner("Coach is thinking…"):
            try:
                reply = _coach.chat(
                    [{"role": "user", "content": kick_off}],
                    _ck_context,
                )
                st.session_state["coach_messages"] = [
                    {"role": "user",      "content": kick_off},
                    {"role": "assistant", "content": reply},
                ]
            except Exception as e:
                st.session_state["coach_messages"] = [
                    {"role": "assistant", "content": f"Error reaching coach: {e}"},
                ]

    with _m1:
        if st.button("📚 Teach me", use_container_width=True,
                     help="Coach walks you through the curriculum step by step"):
            _set_coach_mode(
                "learn",
                "I want to learn. Start from wherever makes sense given what you know about me — "
                "but don't assume I know finance. Ask me one question first to figure out what I already understand.",
            )
            st.rerun()

    with _m2:
        if st.button("🧪 Quiz me", use_container_width=True,
                     help="Coach picks a topic and tests your knowledge"):
            _set_coach_mode(
                "quiz",
                "Quiz me. Pick a concept from the curriculum that you think I should know by now, "
                "and fire a question at me. One question, no hints.",
            )
            st.rerun()

    with _m3:
        if st.button("📋 Review my trades", use_container_width=True,
                     help="Coach analyses your paper trade history and grills you on decisions"):
            _set_coach_mode(
                "review",
                "Review my paper trades. Be honest — if a decision was bad, tell me. "
                "Start by summarising what you see in my trade history, then pick the most "
                "interesting trade and ask me why I made that decision.",
            )
            st.rerun()

    with _m_reset:
        if st.button("🔄 Reset", use_container_width=True, help="Clear chat history"):
            st.session_state["coach_messages"] = []
            st.session_state["coach_mode"] = None
            st.rerun()

    st.markdown("---")

    # ── Render chat history ───────────────────────────────────────────────────
    _msgs = st.session_state.get("coach_messages", [])

    if not _msgs:
        st.info("Choose a mode above to start a coaching session.")
    else:
        for _msg in _msgs:
            with st.chat_message(_msg["role"]):
                st.markdown(_msg["content"])

    # ── Chat input ────────────────────────────────────────────────────────────
    if _msgs:
        _user_input = st.chat_input("Your answer…")
        if _user_input:
            _msgs.append({"role": "user", "content": _user_input})
            st.session_state["coach_messages"] = _msgs
            with st.chat_message("user"):
                st.markdown(_user_input)
            with st.chat_message("assistant"):
                with st.spinner(""):
                    try:
                        _reply = _coach.chat(_msgs, _ck_context)
                    except Exception as e:
                        _reply = f"Error: {e}"
                    st.markdown(_reply)
            _msgs.append({"role": "assistant", "content": _reply})
            st.session_state["coach_messages"] = _msgs
