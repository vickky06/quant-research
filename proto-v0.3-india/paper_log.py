"""Paper trading log — record manual trades and track P&L vs signal.

Commands:
    python paper_log.py enter RELIANCE.NS long  100 2520.50   # enter position
    python paper_log.py enter TCS.NS      short  50 3800.00   # enter short
    python paper_log.py exit  RELIANCE.NS        2601.00       # close position
    python paper_log.py status                                  # open positions + P&L
    python paper_log.py history                                 # all closed trades
    python paper_log.py snapshot                                # mark-to-market open positions

All trades are stored in output/paper_trades.csv. No broker connection needed.

P&L is in ₹. For shorts: profit when price falls.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

TRADES_FILE = Path(__file__).parent / "output" / "paper_trades.csv"
FIELDNAMES = [
    "id", "symbol", "direction", "qty", "entry_price", "entry_date",
    "exit_price", "exit_date", "pnl", "pnl_pct", "status", "notes",
]


def _load_trades() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    with open(TRADES_FILE) as f:
        return list(csv.DictReader(f))


def _save_trades(trades: list[dict]) -> None:
    TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADES_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(trades)


def _next_id(trades: list[dict]) -> int:
    if not trades:
        return 1
    return max(int(t["id"]) for t in trades) + 1


def _get_live_price(symbol: str) -> float | None:
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def cmd_enter(symbol: str, direction: str, qty: int, price: float, notes: str = "") -> None:
    if direction not in ("long", "short"):
        print(f"[error] direction must be 'long' or 'short', got '{direction}'")
        sys.exit(1)
    trades = _load_trades()
    # Check for existing open position in same symbol+direction
    open_same = [t for t in trades if t["symbol"] == symbol
                 and t["direction"] == direction and t["status"] == "open"]
    if open_same:
        print(f"[warn] already have an open {direction} in {symbol} (id={open_same[0]['id']})")
        print(f"       Close it first or use a different direction.")

    trade = {
        "id": _next_id(trades),
        "symbol": symbol,
        "direction": direction,
        "qty": qty,
        "entry_price": price,
        "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "exit_price": "",
        "exit_date": "",
        "pnl": "",
        "pnl_pct": "",
        "status": "open",
        "notes": notes,
    }
    trades.append(trade)
    _save_trades(trades)
    notional = qty * price
    print(f"✓ Entered {direction.upper()} {qty}x {symbol} @ ₹{price:.2f}  (notional ₹{notional:,.0f})")
    print(f"  Trade id={trade['id']}")


def cmd_exit(symbol: str, exit_price: float, notes: str = "") -> None:
    trades = _load_trades()
    open_trades = [t for t in trades if t["symbol"] == symbol and t["status"] == "open"]
    if not open_trades:
        print(f"[error] no open position found for {symbol}")
        sys.exit(1)
    if len(open_trades) > 1:
        print(f"[warn] multiple open positions for {symbol} — closing most recent")

    t = open_trades[-1]
    entry = float(t["entry_price"])
    qty = int(t["qty"])
    direction = t["direction"]

    if direction == "long":
        pnl = (exit_price - entry) * qty
    else:
        pnl = (entry - exit_price) * qty
    pnl_pct = (exit_price / entry - 1) * (1 if direction == "long" else -1) * 100

    t["exit_price"] = exit_price
    t["exit_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    t["pnl"] = round(pnl, 2)
    t["pnl_pct"] = round(pnl_pct, 2)
    t["status"] = "closed"
    if notes:
        t["notes"] = (t.get("notes", "") + " | " + notes).strip(" | ")

    _save_trades(trades)
    emoji = "✓" if pnl >= 0 else "✗"
    print(f"{emoji} Closed {direction.upper()} {qty}x {symbol} @ ₹{exit_price:.2f}")
    print(f"  Entry ₹{entry:.2f} → Exit ₹{exit_price:.2f}  |  P&L ₹{pnl:+,.0f} ({pnl_pct:+.2f}%)")


def cmd_status() -> None:
    trades = _load_trades()
    open_trades = [t for t in trades if t["status"] == "open"]
    closed_trades = [t for t in trades if t["status"] == "closed"]

    print()
    print("=" * 62)
    print("  PAPER TRADING STATUS")
    print("=" * 62)

    if not open_trades:
        print("  No open positions.")
    else:
        print(f"  Open positions ({len(open_trades)}):")
        print(f"  {'#':>3}  {'Symbol':<20}  {'Dir':<6}  {'Qty':>5}  {'Entry':>8}  {'Live':>8}  {'P&L':>10}")
        print("  " + "-" * 60)
        total_unrealised = 0.0
        for t in open_trades:
            live = _get_live_price(t["symbol"])
            entry = float(t["entry_price"])
            qty = int(t["qty"])
            if live:
                if t["direction"] == "long":
                    pnl = (live - entry) * qty
                else:
                    pnl = (entry - live) * qty
                total_unrealised += pnl
                pnl_str = f"₹{pnl:+,.0f}"
                live_str = f"₹{live:.2f}"
            else:
                pnl_str = "—"
                live_str = "—"
            print(f"  {t['id']:>3}  {t['symbol']:<20}  {t['direction']:<6}  {qty:>5}  "
                  f"₹{entry:>7.2f}  {live_str:>8}  {pnl_str:>10}")
        print("  " + "-" * 60)
        print(f"  Unrealised P&L (mark-to-market): ₹{total_unrealised:+,.0f}")

    print()
    if closed_trades:
        total_pnl = sum(float(t["pnl"]) for t in closed_trades if t["pnl"])
        winners = sum(1 for t in closed_trades if float(t.get("pnl", 0)) > 0)
        print(f"  Closed trades: {len(closed_trades)}  |  Win rate: {winners}/{len(closed_trades)}")
        print(f"  Realised P&L:  ₹{total_pnl:+,.0f}")
    print("=" * 62)
    print()


def cmd_history() -> None:
    trades = _load_trades()
    closed = [t for t in trades if t["status"] == "closed"]
    if not closed:
        print("No closed trades yet.")
        return

    print()
    print(f"  {'#':>3}  {'Symbol':<20}  {'Dir':<6}  {'Qty':>5}  "
          f"{'Entry':>8}  {'Exit':>8}  {'P&L':>10}  {'%':>7}  {'Date'}")
    print("  " + "-" * 80)
    for t in closed:
        pnl = float(t["pnl"]) if t["pnl"] else 0
        pct = float(t["pnl_pct"]) if t["pnl_pct"] else 0
        print(f"  {t['id']:>3}  {t['symbol']:<20}  {t['direction']:<6}  {t['qty']:>5}  "
              f"₹{float(t['entry_price']):>7.2f}  ₹{float(t['exit_price']):>7.2f}  "
              f"₹{pnl:>+9,.0f}  {pct:>+6.2f}%  {t['exit_date'][:10]}")
    total = sum(float(t["pnl"]) for t in closed if t["pnl"])
    print("  " + "-" * 80)
    print(f"  Total realised P&L: ₹{total:+,.0f}")
    print()


def cmd_snapshot() -> None:
    """Print current signal report alongside open positions for comparison."""
    import subprocess, sys
    trades = _load_trades()
    open_trades = [t for t in trades if t["status"] == "open"]
    if not open_trades:
        print("No open positions to compare.")
    else:
        open_syms = {t["symbol"]: t["direction"] for t in open_trades}
        print(f"Your open positions: {open_syms}")
        print()
    # Run signal report inline
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "signal_report.py")],
        capture_output=False
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading log")
    sub = parser.add_subparsers(dest="cmd")

    p_enter = sub.add_parser("enter", help="Enter a new position")
    p_enter.add_argument("symbol")
    p_enter.add_argument("direction", choices=["long", "short"])
    p_enter.add_argument("qty", type=int)
    p_enter.add_argument("price", type=float)
    p_enter.add_argument("--notes", default="")

    p_exit = sub.add_parser("exit", help="Close an open position")
    p_exit.add_argument("symbol")
    p_exit.add_argument("price", type=float)
    p_exit.add_argument("--notes", default="")

    sub.add_parser("status", help="Show open positions + unrealised P&L")
    sub.add_parser("history", help="Show all closed trades")
    sub.add_parser("snapshot", help="Compare open positions vs current signal")

    args = parser.parse_args()

    if args.cmd == "enter":
        cmd_enter(args.symbol, args.direction, args.qty, args.price, args.notes)
    elif args.cmd == "exit":
        cmd_exit(args.symbol, args.price, args.notes)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "history":
        cmd_history()
    elif args.cmd == "snapshot":
        cmd_snapshot()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
