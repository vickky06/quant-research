"""Candlestick + Volume chart explainer — shows how both panels work together."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import webbrowser, tempfile

fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.65, 0.35],
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("", ""),
)

days   = ["W1 Mon", "W1 Tue", "W1 Wed", "W1 Thu", "W1 Fri", "W2 Mon", "W2 Tue", "W2 Wed", "W2 Thu", "W2 Fri"]
opens  = [100,   108,   104,   85,    88,    92,    96,    100,   106,   104 ]
highs  = [112,   115,   112,   95,    94,    99,    104,   110,   115,   114 ]
lows   = [97,    100,   80,    78,    82,    88,    92,    97,    103,   100 ]
closes = [108,   104,   84,    90,    92,    97,    102,   107,   104,   112 ]
vols   = [1.2,   0.9,   4.8,   3.9,   1.1,   0.8,   1.0,   1.4,   0.9,   2.1 ]

colors = ["#2ecc71" if c >= o else "#e74c3c" for o, c in zip(opens, closes)]

# ── Candlestick ───────────────────────────────────────────────────────────────
fig.add_trace(go.Candlestick(
    x=days,
    open=opens, high=highs, low=lows, close=closes,
    increasing_line_color="#2ecc71",
    decreasing_line_color="#e74c3c",
    name="Price",
    showlegend=False,
), row=1, col=1)

# ── Volume bars ───────────────────────────────────────────────────────────────
fig.add_trace(go.Bar(
    x=days, y=vols,
    marker_color=colors,
    name="Volume",
    showlegend=False,
    opacity=0.8,
), row=2, col=1)

# ── Annotations on price chart ────────────────────────────────────────────────
fig.add_annotation(
    x="W1 Wed", y=112, xref="x", yref="y",
    text="⬅ Wed: huge red candle<br>sellers dumped hard",
    showarrow=True, ax=80, ay=-20,
    font=dict(size=11, color="#e74c3c"),
    bgcolor="#1a1a2e", bordercolor="#e74c3c",
    row=1, col=1,
)
fig.add_annotation(
    x="W1 Thu", y=78, xref="x", yref="y",
    text="⬅ Thu: long lower wick<br>sellers tried ₹78,<br>buyers pushed back to ₹90",
    showarrow=True, ax=90, ay=20,
    font=dict(size=11, color="#f39c12"),
    bgcolor="#1a1a2e", bordercolor="#f39c12",
    row=1, col=1,
)
fig.add_annotation(
    x="W1 Fri", y=94, xref="x", yref="y",
    text="Fri–Mon: quiet recovery<br>low volume = no panic",
    showarrow=True, ax=-90, ay=-30,
    font=dict(size=11, color="#2ecc71"),
    bgcolor="#1a1a2e", bordercolor="#2ecc71",
    row=1, col=1,
)
fig.add_annotation(
    x="W2 Fri", y=114, xref="x", yref="y",
    text="⬅ Last Fri: strong green<br>high volume = real buying,<br>trend resuming",
    showarrow=True, ax=90, ay=-20,
    font=dict(size=11, color="#2ecc71"),
    bgcolor="#1a1a2e", bordercolor="#2ecc71",
    row=1, col=1,
)

# ── Annotations on volume chart ───────────────────────────────────────────────
fig.add_annotation(
    x="W1 Wed", y=4.8, xref="x", yref="y2",
    text="Highest volume of the period<br>= confirms the big red candle<br>was REAL selling, not noise",
    showarrow=True, ax=100, ay=-10,
    font=dict(size=11, color="#e74c3c"),
    bgcolor="#1a1a2e", bordercolor="#e74c3c",
    row=2, col=1,
)
fig.add_annotation(
    x="W1 Thu", y=3.9, xref="x", yref="y2",
    text="Still high volume<br>= sellers still active<br>but price bounced → buyers entering",
    showarrow=True, ax=100, ay=10,
    font=dict(size=11, color="#f39c12"),
    bgcolor="#1a1a2e", bordercolor="#f39c12",
    row=2, col=1,
)
fig.add_annotation(
    x="W1 Fri", y=1.1, xref="x", yref="y2",
    text="Volume drops = panic over",
    showarrow=True, ax=-90, ay=-30,
    font=dict(size=10, color="#aaaaaa"),
    bgcolor="#1a1a2e",
    row=2, col=1,
)

# ── Y-axis labels ─────────────────────────────────────────────────────────────
fig.update_yaxes(title_text="Price (₹)", row=1, col=1, color="#dddddd")
fig.update_yaxes(title_text="Volume (M shares)", row=2, col=1, color="#dddddd")

# ── Horizontal divider line at volume = 2 (average) ──────────────────────────
fig.add_hline(y=1.5, line_dash="dot", line_color="#555555",
              annotation_text="avg volume", annotation_font_color="#888888",
              row=2, col=1)

# ── Layout ────────────────────────────────────────────────────────────────────
fig.update_layout(
    title=dict(
        text="<b>How to read Price + Volume together</b><br>"
             "<sup>Top panel = price (candlesticks) · Bottom panel = volume (bars) · Same dates on x-axis</sup>",
        font=dict(size=17),
    ),
    height=680,
    paper_bgcolor="#0f0f0f",
    plot_bgcolor="#111111",
    font=dict(color="#dddddd"),
    xaxis_rangeslider_visible=False,
    xaxis2_rangeslider_visible=False,
    margin=dict(l=60, r=60, t=80, b=40),
)

out = tempfile.mktemp(suffix=".html")
fig.write_html(out, include_plotlyjs="cdn")
print(f"Opening: {out}")
webbrowser.open(f"file://{out}")
