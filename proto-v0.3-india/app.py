"""India v0.3 Signal Dashboard — Streamlit app.

Run with:
    streamlit run app.py

Tabs:
    Data      — DB status, incremental refresh, price chart
    Signals   — Current regime, ranked longs/shorts, per-signal breakdown
    Trades    — Log paper trades, open positions with live P&L
    Performance — Equity curve, win rate, trade history
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
DB_PATH = ROOT / "data" / "prices.duckdb"
TRADES_FILE = ROOT / "output" / "paper_trades.csv"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="India v0.3 — Signal Dashboard",
    page_icon="📊",
    layout="wide",
)

# ── lazy imports (only after path setup) ─────────────────────────────────────
import pipeline as P
from pipeline import (
    AGENTS, ROUNDTRIP_COST_BPS, compute_regime,
    get_sector_map, get_universe, load_index, load_prices,
)
from run import REGIME_SIGNAL_WEIGHTS, SKIP_REGIMES
from data_refresh import run_refresh


# ══════════════════════════════════════════════════════════════════════════════
# Cached data loaders
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _load_prices_cached() -> tuple[pd.DataFrame, pd.Series]:
    if not DB_PATH.exists():
        return pd.DataFrame(), pd.Series(dtype=float)
    prices = load_prices(DB_PATH)
    index = load_index(DB_PATH)
    return prices, index


@st.cache_data(ttl=300, show_spinner=False)
def _load_signals_cached() -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.Timestamp | None]:
    prices, index = _load_prices_cached()
    if prices.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), None

    cutoff = prices["date"].max() - pd.Timedelta(days=400)
    prices = prices[prices["date"] >= cutoff]
    index = index[index.index >= cutoff]

    close = prices.pivot(index="date", columns="symbol", values="adj_close")
    volume = prices.pivot(index="date", columns="symbol", values="volume")
    liq = (close * volume).rolling(60, min_periods=20).mean()

    sector_map = get_sector_map()
    signals = {
        name: fn(close, index_close=index, sector_map=sector_map)
        for name, fn in AGENTS.items()
    }
    regime_df = compute_regime(index)
    latest = close.index.max()
    return signals, close, liq, regime_df, latest


def _get_regime_and_weights(regime_df: pd.DataFrame, latest: pd.Timestamp):
    regime = "UNKNOWN"
    if latest in regime_df.index:
        regime = regime_df.loc[latest, "regime"]
    else:
        valid = regime_df.dropna(subset=["regime"])
        if not valid.empty:
            regime = valid.iloc[-1]["regime"]

    raw = REGIME_SIGNAL_WEIGHTS.get(regime, {})
    if not raw:
        raw = {n: 1 / len(AGENTS) for n in AGENTS}
    total = sum(raw.values())
    weights = {k: v / total for k, v in raw.items()}
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

st.title("📊 India v0.3 — Signal Dashboard")
tab_data, tab_signals, tab_trades, tab_perf = st.tabs(
    ["📁 Data", "📈 Signals", "📝 Trades", "💰 Performance"]
)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Data
# ══════════════════════════════════════════════════════════════════════════════

with tab_data:
    st.subheader("Price Database")

    col1, col2, col3 = st.columns([1, 1, 2])

    interval = col1.selectbox("Interval", ["1d", "1h", "5m", "1m"], index=0)
    fast_mode = col2.checkbox("Fast mode (50 tickers)", value=False)

    if st.button("🔄 Refresh Data", type="primary"):
        # Clear cache first so no open DB connections linger before refresh
        _load_prices_cached.clear()
        _load_signals_cached.clear()
        with st.spinner("Downloading new bars… (progress in terminal)"):
            try:
                run_refresh(interval=interval, fast=fast_mode)
                _load_prices_cached.clear()
                _load_signals_cached.clear()
                st.success("Data refreshed — reload the Signals tab to see updated ranks.")
            except Exception as exc:
                st.error(f"Refresh failed: {exc}")

    # DB stats
    if DB_PATH.exists():
        prices, index = _load_prices_cached()
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
            sel_sym = st.selectbox("Symbol", symbols_available,
                                   index=symbols_available.index("RELIANCE.NS")
                                   if "RELIANCE.NS" in symbols_available else 0)
            sym_df = prices[prices["symbol"] == sel_sym].sort_values("date")
            if not sym_df.empty:
                fig = px.line(sym_df, x="date", y="adj_close",
                              title=f"{sel_sym} — Adjusted Close",
                              labels={"adj_close": "Price (₹)", "date": ""})
                fig.update_layout(height=350, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No database found. Click **Refresh Data** to download prices.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Signals
# ══════════════════════════════════════════════════════════════════════════════

with tab_signals:
    if not DB_PATH.exists():
        st.warning("Run data refresh first.")
    else:
        if st.button("🔁 Recompute Signals"):
            _load_signals_cached.clear()

        with st.spinner("Loading signals..."):
            result = _load_signals_cached()

        if len(result) == 5:
            signals, close, liq, regime_df, latest = result
        else:
            signals, close, liq, regime_df, latest = {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None

        if not signals or latest is None:
            st.warning("Not enough data. Run data_refresh.py first.")
        else:
            regime, weights = _get_regime_and_weights(regime_df, latest)

            # Header row
            hcol1, hcol2 = st.columns([2, 3])
            with hcol1:
                st.markdown("**Current Regime**")
                st.markdown(_regime_badge(regime), unsafe_allow_html=True)
                st.caption(f"As of {latest.date()}")
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
            sector_map = get_sector_map()

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
    trades_df = _load_trades()
    open_df = trades_df[trades_df["status"] == "open"] if not trades_df.empty else pd.DataFrame()

    # ── Enter trade ──────────────────────────────────────────────────────────
    with st.expander("➕ Enter new position", expanded=open_df.empty):
        universe_syms = sorted(get_universe())
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
            price = c4.number_input("Entry price (₹)", min_value=0.01, value=100.0, step=0.05)
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
                    price_str = f"₹{live:.2f} live" if live else f"₹{price:.2f} manual"
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
                "Qty": qty_v, "Entry ₹": entry,
                "Live ₹": round(live, 2) if live else "—",
                "P&L ₹": round(pnl, 0) if pnl is not None else "—",
                "P&L %": round(pnl_pct, 2) if pnl_pct is not None else "—",
                "Since": t["entry_date"][:10],
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.metric("Unrealised P&L", f"₹{total_unreal:+,.0f}")

        # ── Close position ────────────────────────────────────────────────────
        with st.expander("✅ Close a position"):
            with st.form("close_trade"):
                open_syms = open_df["symbol"].tolist()
                close_sym = st.selectbox("Symbol to close", open_syms)
                exit_price = st.number_input("Exit price (₹)", min_value=0.01, value=100.0, step=0.05)
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
                        st.success(f"{emoji} Closed {dirn.upper()} {qty_v}× {close_sym} — P&L ₹{pnl:+,.0f} ({pnl_pct:+.2f}%)")
                        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Performance
# ══════════════════════════════════════════════════════════════════════════════

with tab_perf:
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
        m1.metric("Total P&L", f"₹{total_pnl:+,.0f}")
        m2.metric("Trades", len(closed_df))
        m3.metric("Win rate", f"{win_rate:.1%}")
        m4.metric("Avg win", f"₹{avg_win:+,.0f}")
        m5.metric("Avg loss", f"₹{avg_loss:+,.0f}")

        # Equity curve
        closed_df["cumulative_pnl"] = closed_df["pnl"].cumsum()
        fig_eq = px.area(
            closed_df, x="exit_date", y="cumulative_pnl",
            title="Cumulative P&L (₹)",
            labels={"cumulative_pnl": "Cumulative P&L (₹)", "exit_date": ""},
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
            text=[f"₹{p:+,.0f}" for p in closed_df["pnl"]],
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
                "entry_price": "Entry ₹", "exit_price": "Exit ₹",
                "pnl": "P&L ₹", "pnl_pct": "P&L %",
                "exit_date": "Date", "notes": "Notes",
            }),
            use_container_width=True, hide_index=True,
        )
