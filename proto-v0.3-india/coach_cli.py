#!/usr/bin/env python3
"""
Standalone Trading Coach — interactive terminal session.

Usage:
    python coach_cli.py              # prompts you to pick a mode
    python coach_cli.py --mode learn
    python coach_cli.py --mode quiz
    python coach_cli.py --mode review

Type 'exit', 'quit', or press Ctrl+C to end the session.
Type 'context' to re-print the live market context.
Type 'mode' to switch to a different coaching mode.
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# ── Resolve paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Terminal colours ──────────────────────────────────────────────────────────
BOLD    = "\033[1m"
DIM     = "\033[2m"
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
RESET   = "\033[0m"
CLEAR   = "\033[H\033[J"


def _fmt(text: str, width: int = 90) -> str:
    """Wrap and indent coach responses."""
    lines = []
    for para in text.split("\n"):
        if para.strip() == "":
            lines.append("")
        else:
            lines.extend(textwrap.wrap(para, width=width, subsequent_indent="  "))
    return "\n".join(lines)


def _header():
    print(f"\n{BOLD}{CYAN}{'━' * 70}{RESET}")
    print(f"{BOLD}{CYAN}  🎓  Trading Coach  ·  India Signal Algo  ·  v0.3{RESET}")
    print(f"{BOLD}{CYAN}{'━' * 70}{RESET}\n")


def _pick_mode() -> tuple[str, str]:
    """Prompt user to pick a coaching mode. Returns (mode_key, kick_off)."""
    modes = {
        "1": ("learn",  "I want to learn. Start from wherever makes sense given what you know about me — but don't assume I know finance. Ask me one question first to figure out what I already understand."),
        "2": ("quiz",   "Quiz me. Pick a concept from the curriculum that you think I should know by now and fire a question at me. One question, no hints."),
        "3": ("review", "Review my paper trades. Be honest — if a decision was bad, tell me. Start by summarising what you see in my trade history, then pick the most interesting trade and ask me why I made that decision."),
    }
    print(f"{BOLD}Choose a mode:{RESET}")
    print(f"  {GREEN}1{RESET}  📚 Teach me       — curriculum walk-through")
    print(f"  {GREEN}2{RESET}  🧪 Quiz me        — Socratic testing")
    print(f"  {GREEN}3{RESET}  📋 Review trades  — grill on my paper trade decisions")
    print()
    while True:
        choice = input(f"{DIM}Enter 1, 2, or 3: {RESET}").strip()
        if choice in modes:
            return modes[choice]
        print(f"{RED}  Invalid choice. Enter 1, 2, or 3.{RESET}")


def _load_context() -> str:
    """Pull live context from DuckDB + paper trades CSV."""
    import coach as C

    regime        = "UNKNOWN"
    strategy_name = "Regime-Conditional Ensemble"
    longs: list[tuple[str, float]]  = []
    shorts: list[tuple[str, float]] = []
    currency      = "₹"
    market        = "india"

    try:
        import pandas as pd
        import pipeline as P

        db_path = ROOT / "data" / "prices.duckdb"
        if db_path.exists():
            con = P._init_db(db_path)
            prices = P.load_prices(con, db_path)
            index  = P.load_index(con, db_path)
            con.close()

            if not prices.empty and not index.empty:
                close  = prices.pivot(index="date", columns="symbol", values="adj_close")
                volume = prices.pivot(index="date", columns="symbol", values="volume")
                liq    = (close * volume).rolling(60, min_periods=20).mean()
                sector_map = P.get_sector_map(market=market)
                signals = {
                    name: fn(close, index_close=index, sector_map=sector_map, volume=volume)
                    for name, fn in P.AGENTS.items()
                }
                regime_df = P.compute_regime(index)
                latest    = close.index.max()
                regime    = regime_df.iloc[-1]["regime"] if not regime_df.empty else "UNKNOWN"

                # Default weights
                from pipeline import REGIME_SIGNAL_WEIGHTS
                raw = dict(REGIME_SIGNAL_WEIGHTS.get(regime, {k: 1/3 for k in P.AGENTS}))
                raw = {k: v for k, v in raw.items() if v > 0}
                total = sum(raw.values())
                weights = {k: v / total for k, v in raw.items()} if total else raw

                eligible = P.per_rebalance_universe(close, liq, latest)
                if len(eligible) < 10:
                    eligible = close.loc[latest].dropna().index.tolist()

                weighted = pd.Series(0.0, index=eligible)
                mass     = pd.Series(0.0, index=eligible)
                for name, sig_df in signals.items():
                    w = weights.get(name, 0.0)
                    if w == 0 or latest not in sig_df.index:
                        continue
                    s = sig_df.loc[latest, eligible].dropna()
                    weighted.loc[s.index] += s * w
                    mass.loc[s.index] += w
                import numpy as np
                score = (weighted / mass).replace([np.inf, -np.inf], float("nan")).dropna()
                ranked = score.rank(pct=True)
                longs  = list(ranked[ranked >= 0.88].sort_values(ascending=False).head(5).items())
                shorts = list(ranked[ranked <= 0.12].sort_values(ascending=True).head(5).items())
    except Exception as e:
        print(f"{DIM}  [context] signals unavailable: {e}{RESET}")

    # Paper trades
    trades_file = ROOT / "output" / "paper_trades.csv"
    trade_summary = "No paper trades logged yet."
    try:
        import pandas as pd
        if trades_file.exists():
            tdf    = pd.read_csv(trades_file, dtype=str).fillna("")
            open_  = tdf[tdf["status"] == "open"]
            closed = tdf[tdf["status"] == "closed"]
            wins   = sum(1 for _, r in closed.iterrows() if r["pnl"] and float(r["pnl"]) > 0)
            total  = len(closed)
            recent = (closed.tail(3)[["symbol", "direction", "pnl", "pnl_pct"]]
                      .to_string(index=False) if not closed.empty else "none")
            trade_summary = (
                f"Open positions: {len(open_)}\n"
                f"Closed trades: {total}  Win rate: {wins}/{total}\n"
                f"Last 3 closed:\n{recent}"
            )
    except Exception:
        pass

    from datetime import date
    return C.build_context(
        regime=regime, strategy_name=strategy_name,
        longs=longs, shorts=shorts,
        trade_summary=trade_summary,
        currency=currency, date=str(date.today()), market=market,
    )


def _run_session(mode_key: str, kick_off: str, context: str) -> None:
    import coach as C

    messages: list[dict] = []

    print(f"\n{DIM}Connecting to coach…{RESET}")
    try:
        reply = C.chat([{"role": "user", "content": kick_off}], context)
    except RuntimeError as e:
        print(f"\n{RED}{e}{RESET}")
        print(f"{DIM}Set ANTHROPIC_API_KEY in your environment and retry.{RESET}\n")
        return

    messages = [
        {"role": "user",      "content": kick_off},
        {"role": "assistant", "content": reply},
    ]

    mode_labels = {"learn": "📚 Teach me", "quiz": "🧪 Quiz me", "review": "📋 Review trades"}
    print(f"\n{BOLD}Mode: {mode_labels.get(mode_key, mode_key)}{RESET}")
    print(f"{DIM}Type 'exit' to quit · 'context' to see live data · 'mode' to switch{RESET}\n")
    print(f"{CYAN}{BOLD}Coach:{RESET}")
    print(f"  {_fmt(reply)}\n")

    while True:
        try:
            user_input = input(f"{GREEN}{BOLD}You:{RESET}  ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n\n{DIM}Session ended. Good luck with the trades.{RESET}\n")
            break

        if not user_input:
            continue

        low = user_input.lower()

        if low in ("exit", "quit", "bye"):
            print(f"\n{DIM}Session ended. Good luck with the trades.{RESET}\n")
            break

        if low == "context":
            print(f"\n{DIM}{'─' * 60}\nLive context:\n{context}\n{'─' * 60}{RESET}\n")
            continue

        if low == "mode":
            mode_key, kick_off = _pick_mode()
            context = _load_context()
            _run_session(mode_key, kick_off, context)
            return

        messages.append({"role": "user", "content": user_input})
        print(f"\n{DIM}…{RESET}", end="\r")

        try:
            reply = C.chat(messages, context)
        except Exception as e:
            print(f"{RED}Error: {e}{RESET}\n")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})
        print(f"{CYAN}{BOLD}Coach:{RESET}")
        print(f"  {_fmt(reply)}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone trading coach (terminal)")
    parser.add_argument(
        "--mode", choices=["learn", "quiz", "review"], default=None,
        help="Coaching mode (default: prompted)"
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"\n{RED}ANTHROPIC_API_KEY not set.{RESET}")
        print("Export it before running:")
        print("  export ANTHROPIC_API_KEY=sk-ant-...\n")
        sys.exit(1)

    _header()

    print(f"{DIM}Loading live market context…{RESET}")
    context = _load_context()
    print(f"{GREEN}✓ Context loaded{RESET}\n")

    kick_offs = {
        "learn":  "I want to learn. Start from wherever makes sense given what you know about me — but don't assume I know finance. Ask me one question first to figure out what I already understand.",
        "quiz":   "Quiz me. Pick a concept from the curriculum that you think I should know by now and fire a question at me. One question, no hints.",
        "review": "Review my paper trades. Be honest — if a decision was bad, tell me. Start by summarising what you see in my trade history, then pick the most interesting trade and ask me why I made that decision.",
    }

    if args.mode:
        mode_key = args.mode
        kick_off = kick_offs[mode_key]
    else:
        mode_key, kick_off = _pick_mode()

    _run_session(mode_key, kick_off, context)


if __name__ == "__main__":
    main()
