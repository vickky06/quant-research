# Trading Basics — Reference Guide

Personal reference from coaching sessions. Covers every concept discussed, in order learned.

---

## 1. How Markets Work

### What is a stock?
A company sells small pieces of ownership to raise money. Each piece = a **share**. When you buy a share of Reliance, you own a tiny fraction of Reliance Industries.

### What moves the price?
Buyers and sellers constantly disagree on what a stock is worth.
- Someone thinks it will earn more → they buy → price goes up
- Someone thinks it won't → they sell → price goes down

### The Order Book
At any moment on NSE, there are two sides:

| Buyers (Bids) | Price | Sellers (Asks) |
|---|---|---|
| 500 shares | ₹1,800 | — |
| 300 shares | ₹1,795 | — |
| — | ₹1,820 | 200 shares |

The gap between ₹1,800 and ₹1,820 = **bid-ask spread**. No trade happens until someone crosses it.

If sellers urgently need out → they drop their ask to ₹1,800 → trade executes.

### Key Terms

**Ticker** — Short code for a stock. `RELIANCE.NS` = Reliance on NSE. `.NS` = NSE suffix. In the US: `AAPL` = Apple.

**Market Order** — Buy/sell now at whatever price. Executes instantly, you pay the ask.

**Limit Order** — Buy only at ₹X or lower. You wait, but control your price. Most traders use this.

**Bid-Ask Spread** — Gap between highest buyer price and lowest seller price. Small on liquid stocks (₹1–2), large on illiquid ones (₹20–50).

**Liquidity** — How easy it is to buy/sell without moving the price.
- High liquidity (Reliance, TCS): thousands of trades per second, tiny spread
- Low liquidity (small caps): few trades, wide spread — entering costs you before you even start

> Why liquidity matters: a ₹50 spread means you're already down ₹50 per share the moment you enter. The algo filters for liquid stocks first.

---

## 2. Candlestick Charts

Each candle = one trading day. Shows 4 numbers: **Open, High, Low, Close**.

```
High  ₹118  ← buyers pushed here but couldn't hold it all
      │  (upper wick)
Open  ₹100  ┐
            │  GREEN body = Close > Open = buyers won
Close ₹115  ┘
      │  (lower wick)
Low   ₹95   ← sellers pushed here but got bought back
```

**Green candle** = Close above Open = buyers won the day
**Red candle** = Close below Open = sellers won the day

### Wicks
The wick shows where price went during the day but **couldn't stay**.

- **Long upper wick** — buyers pushed price high, sellers came in hard and rejected it. Sellers won at the top.
- **Long lower wick** — sellers pushed price low, buyers flooded in and rejected it. Buyers won at the bottom.
- **Long lower wick = Hammer candle** — sellers gave everything, failed, buyers now in control. Often signals a bounce.

> Key insight: the longer the wick, the stronger the rejection at that level.

### The 3 tools together

| Tool | Question it answers |
|---|---|
| Candle colour | Who won today — buyers or sellers? |
| Wick length | Where are the hidden walls buyers/sellers defend? |
| Volume | Was the move real conviction or just noise? |

---

## 3. Volume

Volume = total shares traded that day = **how many people showed up to the tug of war**.

| Situation | What it means |
|---|---|
| Price up + HIGH volume | Real buying, lots of conviction |
| Price up + LOW volume | Might be noise — don't trust it |
| Price down + HIGH volume | Real panic selling, confirmed move |
| Price down + LOW volume | Just a quiet drift, not conviction |

> **Rule: Volume is the lie detector for price moves. Price tells you what happened. Volume tells you whether to believe it.**

Low volume green candle = noise. Could reverse tomorrow.
High volume red candle = real selling. Respect it.

**Volume spike on a crash** = institutional selling. That single-day level often becomes resistance on the way back up.

---

## 4. Trends

One candle does not make a trend. A trend is the pattern across many candles.

**Uptrend** — each high is higher than the last, each low is higher than the last
```
Day 1: ₹100 → Day 4: ₹106 → Day 7: ₹112
Each pullback stops higher than the last one
```

**Downtrend** — each high is lower than the last, each low is lower than the last

**Sideways** — bouncing between two levels, no clear direction

### Two types of traders

**Momentum Trader** — believes winners keep winning. Buys stocks already going up, rides the trend. Works in bull markets. Risk: sharp reversals hurt badly.

**Mean Reversion Trader** — believes what goes down too far must come back up. Buys beaten-down stocks expecting a bounce. Works in choppy/volatile markets. Risk: sometimes stocks fall for a real reason and never bounce.

> Both work — just in different market conditions. This is why the algo switches signal weights based on the regime.

---

## 5. Support & Resistance

**Support** — a price floor where buyers repeatedly show up and push price back up. Revealed by multiple lower wicks bouncing off the same level.

**Resistance** — a price ceiling where sellers repeatedly show up and push price back down. Revealed by multiple upper wicks getting rejected at the same level.

### How to find them
- Look back **3× your intended hold period** (holding 7–15 days → look back 3 months)
- Look for levels tested **at least 2–3 times** — more tests = stronger level
- **High volume crash days** create strong levels even from a single day — traders remember them

### How to use them

```
Resistance ₹570  ← target (sellers will fight back here)
           ...
Entry      ₹497  ← your buy
           ...
Support    ₹477  ← stop loss (if this breaks, exit)
```

- Potential gain: ₹570 − ₹497 = ₹73
- Maximum loss: ₹497 − ₹477 = ₹20
- **Risk-Reward: 3.6x** — for every ₹1 risked, expected ₹3.6 gain

> Aim for R:R ≥ 2x. Anything below that and the math doesn't work long term.

---

## 6. Moving Averages (MA)

A moving average tracks where price has been **living** recently — its home base.

**20-day MA** — average closing price over last 20 days. Short-term home base. Wiggles closely with price.

**200-day MA** — average closing price over last 200 days (≈1 year). Long-term home base. Slow and smooth.

### How to use them

| Observation | What it means |
|---|---|
| Price above 20-day MA | Running hot, momentum building |
| Price below 20-day MA | Stretched down, mean reversion candidate |
| 20-day above 200-day | Short-term trend stronger than long-term → bullish |
| 20-day crosses below 200-day | **Death Cross** — bearish signal |
| 20-day crosses above 200-day | **Golden Cross** — bullish signal |

> For mean reversion trades: the 20-day MA is your **first target**, not the resistance ceiling. Price gravitates back to the mean before attempting anything higher.

---

## 7. RSI — Relative Strength Index

A number from **0 to 100** that answers: *"has this stock been going up or down too aggressively for too long?"*

| RSI | Meaning | Action |
|---|---|---|
| Above 70 | **Overbought** — risen too fast, too far | Expect pullback. Don't buy. |
| 50–70 | Bullish momentum | Momentum buy still valid |
| 40–60 | Neutral | No strong signal |
| 30–50 | Bearish momentum | Potential mean reversion setup forming |
| Below 30 | **Oversold** — fallen too fast, too far | Expect bounce. Mean reversion entry. |

### How it's calculated (plain English)
Look at last 14 days. Average all the green-day gains. Average all the red-day losses. RSI = how much bigger the gains are vs losses, scaled to 0–100.

### RSI journey of a mean reversion trade
```
Oversold (RSI < 30)  →  Entry ₹497
       ↓
RSI climbs back to 50  →  Mean restored → EXIT (take profit)
       ↓
RSI approaches 70  →  Overbought → definitely exit if still holding
```

> For mean reversion: **exit at RSI 50**, not 70. The snap-back has happened. Holding past 50 is greed.

---

## 8. Complete Decision Framework

### The 6 steps to analyse any stock

| Step | Question | Tool |
|---|---|---|
| 1 | What's the trend? | Candles + higher highs/lows |
| 2 | Is the move real? | Volume |
| 3 | Where are the walls? | Support/Resistance from wicks |
| 4 | Is it stretched from mean? | Price vs 20-day MA |
| 5 | How oversold/overbought? | RSI |
| 6 | Entry, target, stop | All of the above combined |

### Entry types

**Momentum Buy**
- Condition: Uptrend + high volume + RSI 30–60
- Hold: 20–40 days
- Target: next resistance level
- Stop: below last higher low
- Exit when: RSI hits 70 or price breaks a higher low on high volume

**Mean Reversion Buy**
- Condition: Downtrend + RSI < 30 + support confirmed by wicks + volume drying up
- Hold: 5–15 days
- Target: 20-day MA (first), then resistance ceiling
- Stop: below support floor
- Exit when: RSI reaches 50

**Sideways Bounce Buy**
- Condition: Near support + RSI < 40
- Hold: 5–10 days
- Target: resistance ceiling
- Stop: below support floor
- Exit when: RSI reaches 55

**Never trade:**
- Low volume moves (noise)
- RSI neutral + price in middle of range (no edge)
- Downtrend with RSI still above 30 (still falling)

---

## 9. Case Study — HINDCOPPER.NS (Live Trade)

**Entry:** ₹497.4 on Sep 18, 2026
**Algo score:** 1.0 (best mean reversion signal in Nifty 500)

**What the chart showed:**
- Uptrend Aug 17–24 (₹574 peak)
- Crash Aug 25–26: 44M volume (4× average) — real panic selling confirmed
- Downtrend Aug 27 – Sep 17: lower highs, lower lows, steady bleed to ₹481
- Support floor: ₹477–480 (multiple lower wicks bouncing here 3+ times)
- Resistance ceiling: ₹570–574 (multiple upper wicks rejected here)
- RSI at entry: below 30 (oversold)
- Price at entry: below 20-day MA (stretched down)
- Volume: drying up after crash (sellers exhausted)

**Trade thesis:**
> HINDCOPPER sold down hard since August. Below both MAs. RSI oversold. Support at ₹477 confirmed by 3 wicks. Volume dried up. Expecting bounce to 20-day MA ~₹520–530. Longer target ₹570 resistance.

**Trade parameters:**
- Entry: ₹497
- Target: ₹520–530 (20-day MA) or ₹570 (resistance)
- Stop: ₹477 (below support floor)
- R:R: 3.6x
- Hold: 5–15 days (mean reversion window)
- Exit signal: RSI reaches 50

---

## 10. Generated Visuals

All generated during the coaching session — run from `proto-v0.3-india/`:

| File | What it shows |
|---|---|
| `python candle_explainer.py` | 6-panel candlestick anatomy (green/red/wicks explained) |
| `python candle_explainer2.py` | Price + volume panels together, 10-day story |
| `python candle_hindcopper.py` | Real HINDCOPPER 3-month chart with trend zones annotated |
| `open trading_decision_tree.html` | Full buy/sell/hold decision flowchart |

---

## 11. Key Rules to Memorise

1. **Price tells you what happened. Volume tells you whether to believe it.**
2. **A wick shows you where the invisible wall is** — where buyers or sellers defend a level.
3. **Trend is defined by multiple candles**, not one. Higher highs + higher lows = uptrend.
4. **Support and resistance** — look back 3× your hold period, need 2–3 tests to confirm.
5. **20-day MA is the mean** — price below it = stretched = mean reversion candidate.
6. **RSI < 30 = oversold** (bounce likely). **RSI > 70 = overbought** (pullback likely).
7. **For MR trades: exit at RSI 50**, not 70. The snap-back is done.
8. **R:R must be ≥ 2x** — if your target isn't at least 2× your stop distance, the trade isn't worth taking.
9. **Patience is a position** — no edge = don't trade. Wait for price to reach a wall.
10. **Volume spike on a crash** creates a strong resistance level on the way back up, even from one day.
