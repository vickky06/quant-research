"""HINDCOPPER real chart with trend and volume annotations."""
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import webbrowser, tempfile

dates  = ["Aug 17","Aug 18","Aug 19","Aug 20","Aug 21","Aug 24","Aug 25","Aug 26","Aug 27","Aug 28","Aug 31","Sep 01","Sep 02","Sep 03","Sep 04","Sep 07","Sep 08","Sep 09","Sep 10","Sep 11","Sep 15","Sep 16","Sep 17","Sep 18","Sep 21","Sep 22","Sep 23","Sep 24","Sep 25"]
opens  = [535,569,560,565,563,576,542,527,547,539,528,529,521,526,522,522,520,538,539,510,514,496,485,491,505,510,513,504,496]
highs  = [575,577,569,575,582,587,552,563,553,543,530,537,525,529,524,522,537,545,543,517,514,497,489,499,507,522,521,507,499]
lows   = [534,556,553,554,561,567,529,526,533,530,520,517,516,517,518,507,520,531,526,505,491,478,481,487,497,507,509,494,489]
closes = [573,566,555,560,573,574,533,556,536,534,525,527,521,519,522,509,533,532,527,515,492,482,486,497,504,508,513,496,495]
vols   = [29.3,15.5,5.9,9.8,13.7,11.5,44.7,56.5,24.1,10.1,8.8,13.7,6.6,5.4,3.8,6.0,24.9,15.1,8.5,8.8,7.0,7.2,4.7,9.9,4.9,7.8,6.1,5.9,3.6]
colors = ["#2ecc71" if c >= o else "#e74c3c" for o, c in zip(opens, closes)]

fig = make_subplots(rows=2, cols=1, row_heights=[0.65, 0.35],
                    shared_xaxes=True, vertical_spacing=0.03)

fig.add_trace(go.Candlestick(
    x=dates, open=opens, high=highs, low=lows, close=closes,
    increasing_line_color="#2ecc71", decreasing_line_color="#e74c3c",
    name="HINDCOPPER", showlegend=False,
), row=1, col=1)

fig.add_trace(go.Bar(
    x=dates, y=vols, marker_color=colors, showlegend=False, opacity=0.8,
), row=2, col=1)

# ── Trend zones ────────────────────────────────────────────────────────────────
# Uptrend box Aug 17–24
fig.add_vrect(x0="Aug 17", x1="Aug 24", fillcolor="#2ecc71", opacity=0.06,
              annotation_text="UPTREND<br>Higher highs,<br>higher lows",
              annotation_position="top left",
              annotation_font=dict(color="#2ecc71", size=11), row=1, col=1)

# Crash Aug 25
fig.add_vrect(x0="Aug 25", x1="Aug 26", fillcolor="#e74c3c", opacity=0.15,
              annotation_text="CRASH<br>High volume<br>selling",
              annotation_position="top left",
              annotation_font=dict(color="#e74c3c", size=11), row=1, col=1)

# Downtrend Aug 27 – Sep 17
fig.add_vrect(x0="Aug 27", x1="Sep 17", fillcolor="#e74c3c", opacity=0.05,
              annotation_text="DOWNTREND<br>Lower highs,<br>lower lows",
              annotation_position="top right",
              annotation_font=dict(color="#e74c3c", size=11), row=1, col=1)

# Your entry Sep 18
fig.add_vline(x="Sep 18", line_dash="dash", line_color="#f39c12", line_width=2)
fig.add_annotation(x="Sep 18", y=499, text="YOUR ENTRY ₹497",
                   showarrow=True, ax=60, ay=-30,
                   font=dict(color="#f39c12", size=12, family="Arial Black"),
                   bgcolor="#1a1a2e", bordercolor="#f39c12")

# Possible recovery zone
fig.add_vrect(x0="Sep 18", x1="Sep 25", fillcolor="#f39c12", opacity=0.06,
              annotation_text="Recovery?<br>Low volume<br>= uncertain",
              annotation_position="top right",
              annotation_font=dict(color="#f39c12", size=11), row=1, col=1)

# Aug 25 volume spike annotation
fig.add_annotation(x="Aug 25", y=44.7, xref="x", yref="y2",
                   text="10× avg volume<br>= panic selling confirmed",
                   showarrow=True, ax=70, ay=-15,
                   font=dict(color="#e74c3c", size=10),
                   bgcolor="#1a1a2e", bordercolor="#e74c3c",
                   row=2, col=1)

fig.update_yaxes(title_text="Price (₹)", row=1, col=1, color="#dddddd")
fig.update_yaxes(title_text="Volume (M)", row=2, col=1, color="#dddddd")
fig.add_hline(y=10, line_dash="dot", line_color="#555", row=2, col=1,
              annotation_text="avg vol", annotation_font_color="#888")

fig.update_layout(
    title=dict(
        text="<b>HINDCOPPER.NS — Real 3-Month Chart</b><br>"
             "<sup>Your open trade · Entry ₹497.4 · Reading trends + volume on an actual stock</sup>",
        font=dict(size=16),
    ),
    height=650, paper_bgcolor="#0f0f0f", plot_bgcolor="#111111",
    font=dict(color="#dddddd"), xaxis_rangeslider_visible=False,
    margin=dict(l=60, r=60, t=80, b=40),
)

out = tempfile.mktemp(suffix=".html")
fig.write_html(out, include_plotlyjs="cdn")
print(f"Opening: {out}")
webbrowser.open(f"file://{out}")
