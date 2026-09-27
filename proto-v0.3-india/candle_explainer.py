"""Generate a visual candlestick explainer and open it in the browser."""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import webbrowser, tempfile, os

fig = make_subplots(
    rows=2, cols=3,
    subplot_titles=(
        "🟢 Green Candle — Buyers won",
        "🔴 Red Candle — Sellers won",
        "📌 Anatomy of a Candle",
        "Example: 5-day chart",
        "Long wick = rejected move",
        "Volume confirms the story",
    ),
    vertical_spacing=0.18,
    horizontal_spacing=0.1,
)

# ── Chart 1: Green candle ─────────────────────────────────────────────────────
fig.add_trace(go.Candlestick(
    x=["Day"],
    open=[100], high=[118], low=[95], close=[115],
    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
    showlegend=False,
), row=1, col=1)
fig.add_annotation(x="Day", y=118, text="High ₹118", showarrow=True, ay=-30,
                   font=dict(size=11), row=1, col=1)
fig.add_annotation(x="Day", y=115, text="Close ₹115 ←", showarrow=False,
                   xanchor="left", font=dict(size=11, color="#2ecc71"), row=1, col=1)
fig.add_annotation(x="Day", y=100, text="Open ₹100 ←", showarrow=False,
                   xanchor="left", font=dict(size=11), row=1, col=1)
fig.add_annotation(x="Day", y=95, text="Low ₹95", showarrow=True, ay=30,
                   font=dict(size=11), row=1, col=1)

# ── Chart 2: Red candle ──────────────────────────────────────────────────────
fig.add_trace(go.Candlestick(
    x=["Day"],
    open=[115], high=[120], low=[92], close=[95],
    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
    showlegend=False,
), row=1, col=2)
fig.add_annotation(x="Day", y=120, text="High ₹120", showarrow=True, ay=-30,
                   font=dict(size=11), row=1, col=2)
fig.add_annotation(x="Day", y=115, text="Open ₹115 ←", showarrow=False,
                   xanchor="left", font=dict(size=11), row=1, col=2)
fig.add_annotation(x="Day", y=95,  text="Close ₹95 ←", showarrow=False,
                   xanchor="left", font=dict(size=11, color="#e74c3c"), row=1, col=2)
fig.add_annotation(x="Day", y=92,  text="Low ₹92", showarrow=True, ay=30,
                   font=dict(size=11), row=1, col=2)

# ── Chart 3: Anatomy labels ───────────────────────────────────────────────────
fig.add_trace(go.Candlestick(
    x=["Candle"],
    open=[105], high=[125], low=[90], close=[118],
    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
    showlegend=False,
), row=1, col=3)
for y, label in [(125,"Upper wick\n(buyers pushed up\nbut couldn't hold all)"),
                 (118,"Body top = Close\n(green) or Open (red)"),
                 (105,"Body bottom = Open\n(green) or Close (red)"),
                 (90, "Lower wick\n(sellers pushed down\nbut got bought back)")]:
    fig.add_annotation(x="Candle", y=y, text=label, showarrow=True,
                       ax=60, font=dict(size=10), row=1, col=3)

# ── Chart 4: 5-day story ──────────────────────────────────────────────────────
days  = ["Mon","Tue","Wed","Thu","Fri"]
opens  = [100, 108, 104, 112, 108]
highs  = [110, 115, 112, 120, 116]
lows   = [97,  105, 98,  109, 102]
closes = [108, 104, 112, 108, 115]
fig.add_trace(go.Candlestick(
    x=days, open=opens, high=highs, low=lows, close=closes,
    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
    showlegend=False,
), row=2, col=1)
fig.add_annotation(x="Fri", y=115,
                   text="Friday: strong green\nbig volume → likely\ncontinuation",
                   showarrow=True, ax=-60, font=dict(size=10), row=2, col=1)

# ── Chart 5: Long wick rejection ─────────────────────────────────────────────
fig.add_trace(go.Candlestick(
    x=["Hammer"],
    open=[100], high=[103], low=[75], close=[101],
    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
    showlegend=False,
), row=2, col=2)
fig.add_annotation(x="Hammer", y=75,
                   text="Sellers pushed to ₹75\nbut buyers flooded in\n→ 'Hammer' candle\n→ bounce signal",
                   showarrow=True, ay=60, font=dict(size=10), row=2, col=2)
fig.add_annotation(x="Hammer", y=101,
                   text="Closed near open\n= sellers rejected",
                   showarrow=True, ay=-40, font=dict(size=10), row=2, col=2)

# ── Chart 6: Volume bars ──────────────────────────────────────────────────────
vdays = ["Mon","Tue","Wed","Thu","Fri"]
vols  = [1.2,  0.8,  3.5,  0.9,  1.1]
vcols = ["#2ecc71","#e74c3c","#e74c3c","#2ecc71","#2ecc71"]
fig.add_trace(go.Bar(
    x=vdays, y=vols, marker_color=vcols, showlegend=False,
    text=["low","low","HIGH!","low","low"],
    textposition="outside",
), row=2, col=3)
fig.add_annotation(x="Wed", y=3.5,
                   text="Big red candle\n+ high volume\n= real selling,\nnot noise",
                   showarrow=True, ay=50, font=dict(size=10, color="#e74c3c"),
                   row=2, col=3)

# ── Layout ────────────────────────────────────────────────────────────────────
fig.update_layout(
    title=dict(
        text="<b>Candlestick Charts — Visual Guide</b><br>"
             "<sup>Each candle = one trading day. Green = buyers won. Red = sellers won.</sup>",
        font=dict(size=18),
    ),
    height=820,
    paper_bgcolor="#0f0f0f",
    plot_bgcolor="#0f0f0f",
    font=dict(color="#dddddd"),
    xaxis_rangeslider_visible=False,
    xaxis2_rangeslider_visible=False,
    xaxis3_rangeslider_visible=False,
    xaxis4_rangeslider_visible=False,
    xaxis5_rangeslider_visible=False,
)
for i in range(1, 7):
    fig.update_layout(**{f"xaxis{i if i>1 else ''}_rangeslider_visible": False})

out = tempfile.mktemp(suffix=".html")
fig.write_html(out, include_plotlyjs="cdn")
print(f"Opening: {out}")
webbrowser.open(f"file://{out}")
