"""Incremental data refresh — appends new price bars to DuckDB.

Run as often as you like. Only fetches bars newer than what's already
in the database, so it's fast and idempotent.

Usage:
    python data_refresh.py                  # daily bars (default)
    python data_refresh.py --interval 1h    # hourly (last ~2 years available)
    python data_refresh.py --interval 5m    # 5-minute (last 60 days only)
    python data_refresh.py --interval 1m    # 1-minute (last 7 days only)
    python data_refresh.py --fast           # 50-ticker subset (quick test)

Intervals and yfinance history limits:
    1d  → full history back to ~2010        recommended for signal computation
    1h  → ~730 days                         useful for daily signal refresh
    5m  → ~60 days                          intraday monitoring only
    1m  → ~7 days                           intraday monitoring only

Note: signals in this prototype were trained on 1d bars. Running signal_report.py
on shorter intervals is "untrained territory" — use for monitoring, not trading.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import yfinance as yf

import pipeline as P
from pipeline import INDEX_TICKER, get_universe

DB_PATH = Path(__file__).parent / "data" / "prices.duckdb"

INTERVAL_MAX_DAYS = {
    "1d":  None,   # no limit — go back to DATA_START
    "1h":  729,
    "30m": 59,
    "15m": 59,
    "5m":  59,
    "1m":  6,
}


def _get_latest_date(con: duckdb.DuckDBPyConnection, symbol: str, interval: str) -> pd.Timestamp | None:
    """Return the most recent date/datetime stored for this symbol+interval."""
    table = "prices" if interval == "1d" else f"prices_{interval.replace('m', 'min').replace('h', 'hour')}"
    try:
        row = con.execute(
            f"SELECT MAX(date) FROM {table} WHERE symbol = ?", [symbol]
        ).fetchone()
        if row and row[0] is not None:
            return pd.Timestamp(row[0])
    except Exception:
        pass
    return None


def _ensure_intraday_table(con: duckdb.DuckDBPyConnection, interval: str) -> str:
    """Create intraday table if it doesn't exist. Returns table name."""
    suffix = interval.replace("m", "min").replace("h", "hour")
    table = f"prices_{suffix}"
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            symbol VARCHAR,
            date TIMESTAMP,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            adj_close DOUBLE,
            PRIMARY KEY (symbol, date)
        )
    """)
    return table


def refresh_index(con: duckdb.DuckDBPyConnection, interval: str) -> None:
    """Append new index bars since last stored date."""
    latest = None
    try:
        row = con.execute(
            "SELECT MAX(date) FROM index_prices WHERE symbol = ?", [INDEX_TICKER]
        ).fetchone()
        if row and row[0]:
            latest = pd.Timestamp(row[0])
    except Exception:
        pass

    if interval != "1d":
        # For intraday we don't update the daily index table — regime needs daily bars
        return

    max_days = INTERVAL_MAX_DAYS[interval]
    if latest is None:
        start = P.DATA_START
    else:
        start = latest + pd.Timedelta(days=1)

    today = pd.Timestamp.today().normalize()
    if start > today:
        print(f"[index] {INDEX_TICKER} up to date ({latest.date() if latest else 'none'})")
        return

    if max_days:
        start = max(start, today - pd.Timedelta(days=max_days))

    print(f"[index] fetching {INDEX_TICKER} {start.date()} → {today.date()}")
    df = yf.download(INDEX_TICKER, start=start.date(), end=(today + pd.Timedelta(days=1)).date(),
                     interval=interval, auto_adjust=False, progress=False)
    if df.empty:
        print(f"[index] no new data")
        return

    rows = []
    for dt, r in df.iterrows():
        close = r.get("Close")
        if isinstance(close, pd.Series):
            close = close.iloc[0]
        if pd.isna(close):
            continue
        rows.append((INDEX_TICKER, dt.date(), float(close)))
    if rows:
        con.executemany("INSERT OR IGNORE INTO index_prices VALUES (?, ?, ?)", rows)
        print(f"[index] {len(rows)} rows inserted")


def refresh_symbols(
    con: duckdb.DuckDBPyConnection,
    symbols: list[str],
    interval: str,
    batch_size: int = 20,
) -> None:
    """Append new bars for each symbol since its last stored date."""
    today = pd.Timestamp.today().normalize()
    max_days = INTERVAL_MAX_DAYS[interval]

    if interval == "1d":
        table = "prices"
    else:
        table = _ensure_intraday_table(con, interval)

    # Build per-symbol start dates based on what's already stored
    symbol_starts: dict[str, pd.Timestamp] = {}
    for sym in symbols:
        latest = _get_latest_date(con, sym, interval) if interval != "1d" else None

        if interval == "1d":
            # For daily, check the prices table
            try:
                row = con.execute(
                    "SELECT MAX(date) FROM prices WHERE symbol = ?", [sym]
                ).fetchone()
                if row and row[0]:
                    latest = pd.Timestamp(row[0])
            except Exception:
                pass

        if latest is None:
            start = P.DATA_START if interval == "1d" else today - pd.Timedelta(days=max_days or 365)
        else:
            start = latest + pd.Timedelta(days=1 if interval == "1d" else 0, minutes=1 if "m" in interval else 0, hours=1 if interval == "1h" else 0)

        if max_days:
            earliest_allowed = today - pd.Timedelta(days=max_days)
            start = max(start, earliest_allowed)

        if start <= today:
            symbol_starts[sym] = start

    if not symbol_starts:
        print(f"[prices] all {len(symbols)} symbols up to date")
        return

    # Group symbols that share the same start date into batches
    to_fetch = list(symbol_starts.keys())
    print(f"[prices] refreshing {len(to_fetch)} symbols (interval={interval})")

    total_inserted = 0
    for i in range(0, len(to_fetch), batch_size):
        batch = [s for s in to_fetch[i: i + batch_size]]
        # Use the earliest start in the batch
        batch_start = min(symbol_starts[s] for s in batch)
        end = today + pd.Timedelta(days=1)

        yahoo_tickers = [P.to_yahoo(s) for s in batch]
        try:
            df = yf.download(
                yahoo_tickers,
                start=batch_start.date(),
                end=end.date(),
                interval=interval,
                auto_adjust=False,
                progress=False,
                group_by="ticker",
            )
        except Exception as e:
            print(f"  [warn] batch {i // batch_size + 1} failed: {e}")
            continue

        if df.empty:
            continue

        rows = []
        if len(batch) == 1:
            sym = batch[0]
            for dt, r in df.iterrows():
                o = r.get("Open"); h = r.get("High"); lo = r.get("Low")
                c = r.get("Close"); v = r.get("Volume"); ac = r.get("Adj Close")
                for val in [o, h, lo, c, v, ac]:
                    if isinstance(val, pd.Series):
                        val = val.iloc[0]
                if any(pd.isna(x) for x in [c, ac]):
                    continue
                dt_val = dt.date() if interval == "1d" else dt
                rows.append((sym, dt_val, float(o or 0), float(h or 0), float(lo or 0),
                             float(c), int(v or 0), float(ac)))
        else:
            for sym in batch:
                yahoo = P.to_yahoo(sym)
                if yahoo not in df.columns.get_level_values(0):
                    continue
                sym_df = df[yahoo]
                for dt, r in sym_df.iterrows():
                    c = r.get("Close"); ac = r.get("Adj Close")
                    if isinstance(c, pd.Series): c = c.iloc[0]
                    if isinstance(ac, pd.Series): ac = ac.iloc[0]
                    if pd.isna(c) or pd.isna(ac):
                        continue
                    o = float(r.get("Open") or 0); h = float(r.get("High") or 0)
                    lo = float(r.get("Low") or 0); v = int(r.get("Volume") or 0)
                    dt_val = dt.date() if interval == "1d" else dt
                    rows.append((sym, dt_val, o, h, lo, float(c), v, float(ac)))

        if rows:
            if interval == "1d":
                con.executemany(
                    "INSERT OR IGNORE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            else:
                con.executemany(
                    f"INSERT OR IGNORE INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            total_inserted += len(rows)

    print(f"[prices] {total_inserted} rows inserted")


def run_refresh(interval: str = "1d", fast: bool = False, db_path: Path = DB_PATH) -> None:
    """Run refresh in-process (no subprocess). Used by app.py to avoid DuckDB lock conflicts."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    symbols = get_universe(fast=fast)
    print(f"[refresh] {len(symbols)} symbols  interval={interval}  {datetime.now():%Y-%m-%d %H:%M:%S}")
    con = P._init_db(db_path)
    try:
        refresh_index(con, interval)
        refresh_symbols(con, symbols, interval)
    finally:
        con.close()
    print("[refresh] done")


def main() -> None:
    parser = argparse.ArgumentParser(description="Incremental price refresh")
    parser.add_argument("--interval", default="1d",
                        choices=["1d", "1h", "30m", "15m", "5m", "1m"],
                        help="Bar interval (default: 1d)")
    parser.add_argument("--fast", action="store_true",
                        help="Use 50-ticker fallback instead of full universe")
    args = parser.parse_args()

    if args.interval != "1d":
        print(f"[warn] interval={args.interval}: signals were trained on 1d bars.")
        print(f"       Intraday data is stored but signal_report.py will flag this.")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    symbols = get_universe(fast=args.fast)
    print(f"[refresh] {len(symbols)} symbols  interval={args.interval}  {datetime.now():%Y-%m-%d %H:%M:%S}")

    con = P._init_db(DB_PATH)
    refresh_index(con, args.interval)
    refresh_symbols(con, symbols, args.interval)
    con.close()

    print(f"[refresh] done")


if __name__ == "__main__":
    main()
