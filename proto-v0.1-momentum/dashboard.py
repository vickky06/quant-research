"""Local Streamlit dashboard for the v0.1 momentum prototype.

Run with: streamlit run dashboard.py
Opens at http://localhost:8501

Read PROTOTYPE_NOTICE.md first. This is a throwaway visualization layer
over pipeline.py — everything reactive here uses cached data from DuckDB
or JSON outputs. No re-downloading.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import pipeline as P
import run_log

PROTO_ROOT = Path(__file__).parent
DB_PATH = PROTO_ROOT / "data" / "prices.duckdb"
OUT_DIR = PROTO_ROOT / "output"
CONTEXT_PATH = PROTO_ROOT.parent / "CONTEXT.md"
CONTRACT_PATH = PROTO_ROOT.parent / "strategy-design-contract.md"


# =============================================================================
# Cached data loaders
# =============================================================================


@st.cache_data(show_spinner="Loading prices from DuckDB…")
def load_prices_cached() -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame()
    return P.load_prices(DB_PATH)


@st.cache_data(show_spinner="Loading index prices…")
def load_index_cached() -> pd.Series:
    if not DB_PATH.exists():
        return pd.Series(dtype=float)
    return P.load_index(DB_PATH)


@st.cache_data
def load_regime_cached(_index: pd.Series) -> pd.DataFrame:
    if _index.empty:
        return pd.DataFrame()
    return P.compute_regime(_index)


@st.cache_data
def load_wide_close(_prices: pd.DataFrame) -> pd.DataFrame:
    if _prices.empty:
        return pd.DataFrame()
    return _prices.pivot(index="date", columns="symbol", values="adj_close")


@st.cache_data
def load_momentum(_close_wide: pd.DataFrame) -> pd.DataFrame:
    if _close_wide.empty:
        return pd.DataFrame()
    return P.compute_momentum(_close_wide)


def read_json_safe(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# =============================================================================
# Glossary parser (CONTEXT.md → dict[section, list[(term, body)]])
# =============================================================================


@st.cache_data
def parse_context_glossary(text: str) -> dict[str, list[tuple[str, str]]]:
    lines = text.splitlines()
    sections: dict[str, list[tuple[str, str]]] = {}
    current_section = "General"
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Section header (### Foo)
        if line.startswith("### "):
            current_section = line[4:].strip()
            sections.setdefault(current_section, [])
        # Term (**Foo**:)
        m = re.match(r"^\*\*(.+?)\*\*:\s*$", line)
        if m:
            term = m.group(1).strip()
            body_lines = []
            j = i + 1
            while j < len(lines) and not re.match(r"^\*\*.+?\*\*:\s*$", lines[j].strip()):
                if lines[j].startswith("### ") or lines[j].startswith("## "):
                    break
                body_lines.append(lines[j])
                j += 1
            body = "\n".join(body_lines).strip()
            sections.setdefault(current_section, []).append((term, body))
            i = j
            continue
        i += 1
    return sections


# =============================================================================
# Page setup
# =============================================================================

st.set_page_config(
    page_title="v0.1 Momentum Prototype",
    page_icon="📊",
    layout="wide",
)

st.title("v0.1 Momentum Prototype — Dashboard")
st.caption(
    "Local visualization over the throwaway prototype. Read `PROTOTYPE_NOTICE.md` first."
)

# Data availability check
prices = load_prices_cached()
index_close = load_index_cached()

if prices.empty or index_close.empty:
    st.warning(
        "No cached data yet. Run `python run.py --fast` (or `python run.py` for full Nifty 500) first."
    )
    st.stop()

close_wide = load_wide_close(prices)
regime_df = load_regime_cached(index_close)
momentum = load_momentum(close_wide)

with st.sidebar:
    st.subheader("Data snapshot")
    st.metric("Symbols", close_wide.shape[1])
    st.metric("Trading days", close_wide.shape[0])
    st.metric("Date range", f"{close_wide.index.min().date()} → {close_wide.index.max().date()}")

    st.divider()
    st.subheader("Held-out lock")
    st.markdown(
        f"Held-out set starts **{P.HELD_OUT_START.date()}** — dashboard clamps date "
        f"pickers to Training window only."
    )

    st.divider()
    st.caption("Contract source of truth: `strategy-design-contract.md`")
    st.caption("Vocabulary source: `CONTEXT.md`")


tab_glossary, tab_regime, tab_signal, tab_backtest, tab_gate, tab_history = st.tabs([
    "📖 Glossary",
    "🌡️ Regime Explorer",
    "🔍 Signal Explorer",
    "🎛️ Backtest Playground",
    "🚦 Gate Status",
    "📚 Run History",
])


# =============================================================================
# Tab 1 — Glossary
# =============================================================================

with tab_glossary:
    st.header("Glossary — the vocabulary of this system")
    st.caption(
        "Parsed from CONTEXT.md. Terms in **bold** are what the code uses; "
        "terms after _Avoid_ are what to *not* say."
    )

    if not CONTEXT_PATH.exists():
        st.error(f"CONTEXT.md not found at {CONTEXT_PATH}")
    else:
        text = CONTEXT_PATH.read_text()
        sections = parse_context_glossary(text)

        search = st.text_input("Search terms", "").strip().lower()

        for section_name, terms in sections.items():
            filtered = [
                (t, b) for t, b in terms
                if not search or search in t.lower() or search in b.lower()
            ]
            if not filtered:
                continue
            st.subheader(section_name)
            cols = st.columns(2)
            for idx, (term, body) in enumerate(filtered):
                with cols[idx % 2]:
                    with st.expander(f"**{term}**", expanded=bool(search)):
                        st.markdown(body)


# =============================================================================
# Tab 2 — Regime Explorer
# =============================================================================

REGIME_COLORS = {
    "LOW_VOL_UP_TREND": "rgba(46, 204, 113, 0.18)",    # calm bull — green
    "HIGH_VOL_UP_TREND": "rgba(241, 196, 15, 0.18)",   # choppy bull — yellow
    "LOW_VOL_DOWN_TREND": "rgba(230, 126, 34, 0.18)",  # grinding bear — orange
    "HIGH_VOL_DOWN_TREND": "rgba(231, 76, 60, 0.22)",  # crisis — red
    "UNKNOWN": "rgba(128, 128, 128, 0.10)",
}

REGIME_LABELS = {
    "LOW_VOL_UP_TREND": "Calm Bull",
    "HIGH_VOL_UP_TREND": "Choppy Bull",
    "LOW_VOL_DOWN_TREND": "Grinding Bear",
    "HIGH_VOL_DOWN_TREND": "Crisis",
    "UNKNOWN": "Unknown (warmup)",
}


with tab_regime:
    st.header("Regime Explorer")
    st.caption("Nifty 50 index with 2×2 Vol×Trend regime overlay.")

    reg_start, reg_end = st.select_slider(
        "Date range",
        options=list(regime_df.index),
        value=(
            max(regime_df.index.min(), P.TRAINING_START),
            min(regime_df.index.max(), P.TRAINING_END),
        ),
        format_func=lambda d: d.strftime("%Y-%m"),
    )

    reg_sel = regime_df.loc[reg_start:reg_end].copy()
    idx_sel = index_close.loc[reg_start:reg_end]

    # Current-state metric
    latest = reg_sel.iloc[-1]
    cA, cB, cC, cD = st.columns(4)
    cA.metric("Latest Regime", REGIME_LABELS.get(latest["regime"], "?"))
    cB.metric("Vol percentile", f"{latest['vol_percentile']:.2f}" if pd.notna(latest["vol_percentile"]) else "—")
    cC.metric("Trend slope", f"{latest['trend_slope']:+.4f}" if pd.notna(latest["trend_slope"]) else "—")
    cD.metric("As of", latest.name.strftime("%Y-%m-%d"))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=idx_sel.index, y=idx_sel.values, mode="lines",
        line=dict(color="#2c3e50", width=1.4),
        name="Nifty 50",
    ))
    # Regime bands
    reg_sel["regime_next"] = reg_sel["regime"].shift(-1)
    boundaries = reg_sel[reg_sel["regime"] != reg_sel["regime_next"]].index.tolist()
    prev = reg_sel.index[0]
    for b in boundaries:
        reg_here = reg_sel.loc[prev, "regime"]
        color = REGIME_COLORS.get(reg_here, REGIME_COLORS["UNKNOWN"])
        fig.add_vrect(
            x0=prev, x1=b, fillcolor=color, opacity=1.0, line_width=0, layer="below",
        )
        prev = b
    fig.update_layout(
        height=500,
        xaxis_title="Date",
        yaxis_title="Nifty 50 close",
        margin=dict(l=20, r=20, t=20, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Regime frequency histogram
    st.subheader("Regime frequency in window")
    freq = reg_sel["regime"].value_counts(normalize=True).sort_index()
    st.dataframe(
        pd.DataFrame({
            "Regime": [REGIME_LABELS.get(r, r) for r in freq.index],
            "Frequency": [f"{v:.1%}" for v in freq.values],
            "Days": reg_sel["regime"].value_counts().reindex(freq.index).values,
        }).set_index("Regime"),
        use_container_width=True,
    )


# =============================================================================
# Tab 3 — Signal Explorer
# =============================================================================

with tab_signal:
    st.header("Signal Explorer")
    st.caption(
        "Pick an Instrument. See its 12-1 momentum rank over time, and its "
        "realized forward 1-month return."
    )

    symbols = sorted(close_wide.columns.tolist())
    if not symbols:
        st.warning("No symbols available.")
    else:
        symbol = st.selectbox("Instrument", symbols, index=0)

        # 12-1 momentum for this symbol
        s_mom = momentum[symbol].dropna()
        s_price = close_wide[symbol].dropna()
        s_ret_fwd = s_price.pct_change(periods=21).shift(-21).dropna()

        # Clamp to training window
        s_mom = s_mom.loc[P.TRAINING_START:P.TRAINING_END]
        s_price = s_price.loc[P.TRAINING_START:P.TRAINING_END]
        s_ret_fwd = s_ret_fwd.loc[P.TRAINING_START:P.TRAINING_END]

        c1, c2, c3 = st.columns(3)
        c1.metric("Latest momentum rank", f"{s_mom.iloc[-1]:.2%}" if not s_mom.empty else "—")
        c2.metric("Latest price (₹)", f"{s_price.iloc[-1]:.2f}" if not s_price.empty else "—")
        c3.metric("Data points", len(s_mom))

        fig_signal = go.Figure()
        fig_signal.add_trace(go.Scatter(
            x=s_mom.index, y=s_mom.values, mode="lines", name="12-1 momentum rank",
            line=dict(color="#3498db", width=1.4),
        ))
        fig_signal.add_hline(y=0.9, line_dash="dot", line_color="#27ae60",
                             annotation_text="Long threshold (top decile)",
                             annotation_position="top left")
        fig_signal.add_hline(y=0.1, line_dash="dot", line_color="#c0392b",
                             annotation_text="Short threshold (bottom decile)",
                             annotation_position="bottom left")
        fig_signal.update_layout(
            height=380, yaxis_title="Cross-sectional rank [0,1]",
            xaxis_title="Date",
            margin=dict(l=20, r=20, t=30, b=20),
            title=f"{symbol} — 12-1 momentum rank vs universe",
        )
        st.plotly_chart(fig_signal, use_container_width=True)

        fig_price = go.Figure()
        fig_price.add_trace(go.Scatter(
            x=s_price.index, y=s_price.values, mode="lines", name="Price (adj close)",
            line=dict(color="#2c3e50", width=1.2),
        ))
        fig_price.update_layout(
            height=300, yaxis_title="₹",
            margin=dict(l=20, r=20, t=30, b=20),
            title=f"{symbol} — price",
        )
        st.plotly_chart(fig_price, use_container_width=True)


# =============================================================================
# Tab 4 — Backtest Playground
# =============================================================================

with tab_backtest:
    st.header("Backtest Playground")
    st.caption(
        "Tweak parameters and rerun the backtest on cached data. The last-run "
        "result on disk is the honest one — this tab is for building intuition."
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        lookback = st.slider("Momentum lookback (months)", 3, 24, 12)
    with c2:
        skip = st.slider("Skip months", 0, 3, 1)
    with c3:
        deciles = st.slider("Deciles (top/bottom N)", 5, 20, 10)
    with c4:
        cost_bps = st.slider("Cost bps (roundtrip)", 0, 100, 20)

    if st.button("Run backtest with these params", type="primary"):
        with st.spinner("Running backtest…"):
            # Recompute momentum with tweaked params
            lookback_days = lookback * 21
            skip_days = skip * 21
            past = close_wide.shift(skip_days)
            older = close_wide.shift(lookback_days)
            raw = past / older - 1.0
            momo = raw.rank(axis=1, pct=True)

            # Temp override of decile constant
            orig_deciles = P.DECILES
            P.DECILES = deciles
            try:
                turnover_wide = close_wide * prices.pivot(
                    index="date", columns="symbol", values="volume"
                )
                liq60 = turnover_wide.rolling(60, min_periods=30).mean()

                result = P.run_backtest(
                    close_wide=close_wide,
                    momentum=momo,
                    liquidity_60d=liq60,
                    regime_df=regime_df,
                    training_start=P.TRAINING_START,
                    training_end=P.TRAINING_END,
                    cost_bps=cost_bps,
                )
            finally:
                P.DECILES = orig_deciles

            ic_series = P.compute_ic_per_rebalance(
                result.signal_at_rebalance, result.forward_returns
            )
            scorecard = P.compute_regime_scorecard(ic_series, result.regime_at_rebalance)
            dsr = P.compute_dsr(result.monthly_returns)
            gate = P.evaluate_gate_g1(dsr, scorecard, threshold_dsr=0.5)

        c1, c2, c3 = st.columns(3)
        c1.metric("Sharpe (net, ann.)", f"{dsr['sharpe_annualized']:+.3f}")
        c2.metric("DSR (PSR)", f"{dsr['psr']:.3f}", delta=f"threshold 0.5")
        c3.metric(
            "Gate G1",
            gate["verdict"],
            delta="pass" if gate["verdict"] == "PASS" else "fail",
            delta_color="normal" if gate["verdict"] == "PASS" else "inverse",
        )

        # Equity curve
        equity = (1 + result.monthly_returns).cumprod()
        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(
            x=equity.index, y=equity.values, mode="lines",
            line=dict(color="#3498db", width=2),
            name="Cumulative L/S (net)",
        ))
        fig_eq.add_hline(y=1.0, line_dash="dot", line_color="#95a5a6")
        fig_eq.update_layout(
            height=400, yaxis_title="Cumulative return (1 = start)",
            title="Long-short equity curve, net of costs",
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_eq, use_container_width=True)

        # Regime scorecard
        st.subheader("Regime Scorecard")
        st.dataframe(
            scorecard.rename_axis("Regime").reset_index().set_index("Regime"),
            use_container_width=True,
        )

        st.info(
            "Reminder: this is on cached data and the momentum params are tweaked. "
            "The Contract's Gate G1 evidence is what's on disk in "
            "`output/gate_g1_result.json`, not what you saw here."
        )


# =============================================================================
# Tab 5 — Gate Status
# =============================================================================

with tab_gate:
    st.header("Gate Status")
    st.caption("Read from `output/gate_g1_result.json` and `regime_scorecard.json`.")

    gate = read_json_safe(OUT_DIR / "gate_g1_result.json")
    scorecard = read_json_safe(OUT_DIR / "regime_scorecard.json")

    if not gate:
        st.warning("No `gate_g1_result.json` yet — run `python run.py` first.")
    else:
        verdict = gate["verdict"]
        color = "🟢" if verdict == "PASS" else "🔴"
        st.markdown(f"### {color} Gate G1: **{verdict}**")

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "DSR (PSR)",
            f"{gate['observed_dsr_psr']:.3f}",
            delta=f"threshold {gate['threshold_dsr']}",
            delta_color="normal" if gate["dsr_pass"] else "inverse",
        )
        c2.metric(
            "Positive-IC Regimes",
            f"{gate['regime_positive_count']} / {gate['regime_total_evaluated']}",
            delta="≥ 3 required",
            delta_color="normal" if gate["regime_pass"] else "inverse",
        )
        c3.metric(
            "Sharpe (net, ann.)",
            f"{gate['sharpe_annualized']:+.3f}",
        )

        st.divider()
        st.subheader("Regime Scorecard heatmap")
        if scorecard:
            rows = []
            for reg, vals in scorecard.items():
                rows.append({
                    "Regime": REGIME_LABELS.get(reg, reg),
                    "IC (mean)": vals["ic_mean"],
                    "Rebalances": vals["n_rebalances"],
                })
            df = pd.DataFrame(rows).set_index("Regime")
            fig_hm = px.bar(
                df.reset_index(),
                x="Regime", y="IC (mean)",
                color="IC (mean)",
                color_continuous_scale="RdBu",
                color_continuous_midpoint=0.0,
                text=df["IC (mean)"].apply(lambda x: f"{x:+.4f}"),
            )
            fig_hm.update_traces(textposition="outside")
            fig_hm.update_layout(
                height=400,
                margin=dict(l=20, r=20, t=20, b=20),
                showlegend=False,
            )
            st.plotly_chart(fig_hm, use_container_width=True)

            st.dataframe(df, use_container_width=True)

        st.divider()
        st.subheader("Remaining gates (G2–G5)")
        remaining = pd.DataFrame([
            {"Gate": "G2 Ensemble", "Test": "DSR + max DD on training set", "Status": "not yet — need ensemble"},
            {"Gate": "G3 Held-out", "Test": "One-shot on 2024-2026-Q2", "Status": "locked — do not touch"},
            {"Gate": "G4 Paper", "Test": "3 months paper trading", "Status": "not started"},
            {"Gate": "G5 Live-Small", "Test": "12 months live money", "Status": "not started"},
        ])
        st.dataframe(remaining.set_index("Gate"), use_container_width=True)


# =============================================================================
# Tab 6 — Run History
# =============================================================================

with tab_history:
    st.header("Run History")
    st.caption(
        "Every `python run.py` execution is persisted to `data/run_log.sqlite`. "
        "This is your audit trail — what you tried, when, and what it produced."
    )

    runs = run_log.read_runs()

    if runs.empty:
        st.warning("No runs logged yet. Execute `python run.py` (or `--fast`) at least once.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total runs", len(runs))
        c2.metric("Pass count", int((runs["verdict"] == "PASS").sum()))
        c3.metric("Fail count", int((runs["verdict"] == "FAIL").sum()))
        c4.metric("Most recent", runs.iloc[0]["timestamp"])

        # Filters
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            mode_filter = st.multiselect(
                "Mode filter",
                options=sorted(runs["mode"].unique().tolist()),
                default=sorted(runs["mode"].unique().tolist()),
            )
        with col_f2:
            verdict_filter = st.multiselect(
                "Verdict filter",
                options=sorted(runs["verdict"].unique().tolist()),
                default=sorted(runs["verdict"].unique().tolist()),
            )

        filtered = runs[
            runs["mode"].isin(mode_filter) & runs["verdict"].isin(verdict_filter)
        ]

        display_cols = [
            "id", "timestamp", "mode", "universe_size", "verdict",
            "dsr", "sharpe_annualized", "cumulative_return", "ic_mean",
            "n_rebalances", "avg_turnover",
        ]
        display_cols = [c for c in display_cols if c in filtered.columns]
        st.dataframe(
            filtered[display_cols].style.format({
                "dsr": "{:.3f}",
                "sharpe_annualized": "{:+.3f}",
                "cumulative_return": "{:+.2%}",
                "ic_mean": "{:+.4f}",
                "avg_turnover": "{:.1%}",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.divider()
        st.subheader("Inspect single run")
        if not filtered.empty:
            run_choices = filtered.apply(
                lambda r: f"#{r['id']} — {r['timestamp']} — {r['mode']} — {r['verdict']}",
                axis=1,
            ).tolist()
            selected = st.selectbox("Pick a run", run_choices, index=0)
            run_id = int(selected.split("#")[1].split(" ")[0])

            run_row = runs[runs["id"] == run_id].iloc[0]
            regimes = run_log.read_run_regimes(run_id)

            c1, c2, c3 = st.columns(3)
            c1.metric("Verdict", run_row["verdict"])
            c2.metric("DSR", f"{run_row['dsr']:.3f}")
            c3.metric("Sharpe (ann.)", f"{run_row['sharpe_annualized']:+.3f}")

            with st.expander("Parameters"):
                st.json(json.loads(run_row["params_json"]))

            if not regimes.empty:
                st.markdown("**Regime Scorecard for this run**")
                display_regimes = regimes.copy()
                display_regimes["Regime"] = display_regimes["regime"].map(
                    REGIME_LABELS
                ).fillna(display_regimes["regime"])
                st.dataframe(
                    display_regimes[["Regime", "ic_mean", "n_rebalances"]].style.format({
                        "ic_mean": "{:+.4f}"
                    }),
                    use_container_width=True,
                    hide_index=True,
                )
