"""Pipeline for v0.3 India prototype (Nifty 500).

Adapted from v0.2-us prototype: same signal + Meta-Learner + regime
architecture, India equities, Nifty 500 universe, ^NSEI index proxy,
Zerodha cost model.

Key change vs v0.1: regime-conditional hard gating (ADR-0007). Mean
reversion has negative IC in LOW_VOL_UP_TREND even in training. The
backtest now skips those months and records 0 return — removing the
catastrophic anti-market trades documented in the US v0.2 post-mortem.

Pure-ish functions. No CLI, no orchestration — those live in run.py.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats


# =============================================================================
# Contract-bound constants
# =============================================================================

TRAINING_START = pd.Timestamp("2017-01-01")
TRAINING_END = pd.Timestamp("2023-12-31")
HELD_OUT_START = pd.Timestamp("2024-01-01")

# Data must extend earlier than TRAINING_START for lookback needs (12m momentum + 200d MA)
DATA_START = pd.Timestamp("2015-01-01")

# India-market thresholds
LIQUIDITY_THRESHOLD_INR = 5_000_000   # ₹50 lakh avg daily turnover floor
LISTING_YEARS = 3
PRICE_FLOOR_INR = 50.0                # skip very cheap stocks (penny/SME)

MOMENTUM_LOOKBACK_MONTHS = 12
MOMENTUM_SKIP_MONTHS = 1
DECILES = 10

# Regime detection
VOL_WINDOW_DAYS = 60
VOL_PERCENTILE_WINDOW_DAYS = 252 * 5  # 5-year rolling
MA_WINDOW = 200
TREND_LOOKBACK_DAYS = 20

# Cost model: Zerodha equity delivery ~20 bps roundtrip (brokerage + STT + exchange)
ROUNDTRIP_COST_BPS = 20

INDEX_TICKER = "^NSEI"  # Nifty 50 as regime proxy


# =============================================================================
# Universe
# =============================================================================

# Hardcoded fallback: ~270 liquid Nifty 500 stocks across sectors (NSE tickers).
# Covers Nifty 50, Nifty Next 50, Nifty Midcap 150, and Nifty Smallcap selections.
# Known-bad tickers removed: TATAMOTORS, LTIM, MCDOWELL-N, HBLPOWER, FINOLEX,
#   JSPL, BARBEQUE, VEDANT, NIPPONLIFE, LEMONTRE, ZOMATO, IPCA (yfinance issues).
NIFTY500_FALLBACK = [
    # Nifty 50 large-caps
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BAJFINANCE.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "HCLTECH.NS", "ASIANPAINT.NS", "AXISBANK.NS", "MARUTI.NS",
    "NESTLEIND.NS", "TITAN.NS", "WIPRO.NS", "ULTRACEMCO.NS", "SUNPHARMA.NS",
    "BAJAJFINSV.NS", "ONGC.NS", "TECHM.NS", "NTPC.NS", "POWERGRID.NS",
    "COALINDIA.NS", "DIVISLAB.NS", "DRREDDY.NS", "GRASIM.NS", "INDUSINDBK.NS",
    "JSWSTEEL.NS", "BRITANNIA.NS", "CIPLA.NS", "TATASTEEL.NS",
    "HINDALCO.NS", "BPCL.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "M&M.NS",
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "BAJAJ-AUTO.NS", "TATACONSUM.NS",
    "SBILIFE.NS", "HDFCLIFE.NS", "UPL.NS", "DABUR.NS", "PIDILITIND.NS",
    # Nifty Next 50
    "DMART.NS", "SIEMENS.NS", "HAVELLS.NS", "BERGEPAINT.NS", "MARICO.NS",
    "GODREJCP.NS", "MUTHOOTFIN.NS", "COLPAL.NS", "PGHH.NS", "BOSCHLTD.NS",
    "SOLARINDS.NS", "MOTHERSON.NS", "TORNTPHARM.NS", "LUPIN.NS", "AUROPHARMA.NS",
    "BIOCON.NS", "AMBUJACEM.NS", "ACC.NS", "SHREECEM.NS", "INDIGO.NS",
    "TATAPOWER.NS", "IOC.NS", "GAIL.NS", "PETRONET.NS",
    "HINDPETRO.NS", "SAIL.NS", "NMDC.NS", "RECLTD.NS", "PFC.NS",
    "IRCTC.NS", "HAL.NS", "BEL.NS", "BHEL.NS", "CONCOR.NS",
    "OFSS.NS", "MPHASIS.NS", "PERSISTENT.NS", "COFORGE.NS",
    # Nifty Midcap 150 selections (liquid mid-caps)
    "VOLTAS.NS", "CROMPTON.NS", "BLUESTARCO.NS", "WHIRLPOOL.NS", "SYMPHONY.NS",
    "POLYCAB.NS", "KEI.NS", "SCHNEIDER.NS",
    "IDFCFIRSTB.NS", "BANDHANBNK.NS", "FEDERALBNK.NS", "RBLBANK.NS", "KARURVYSYA.NS",
    "CHOLAFIN.NS", "MANAPPURAM.NS", "LICHSGFIN.NS", "SUNDARMFIN.NS", "M&MFIN.NS",
    "PIIND.NS", "RALLIS.NS", "COROMANDEL.NS", "GNFC.NS", "DEEPAKNTR.NS",
    "AARTIIND.NS", "NAVINFLUOR.NS", "SUDARSCHEM.NS", "VINATIORGA.NS", "FINEORG.NS",
    "CUMMINSIND.NS", "THERMAX.NS", "GRINDWELL.NS", "TIMKEN.NS", "SCHAEFFLER.NS",
    "ASTRAL.NS", "SUPREMEIND.NS", "ATUL.NS", "NOCIL.NS", "BALAMINES.NS",
    "JUBLFOOD.NS", "WESTLIFE.NS", "DEVYANI.NS", "SAPPHIRE.NS",
    "TRENT.NS", "VMART.NS", "PAGEIND.NS", "MANYAVAR.NS",
    "TORNTPOWER.NS", "CESC.NS", "RATNAMANI.NS", "WELCORP.NS",
    "RVNL.NS", "IRFC.NS", "NBCC.NS", "NCC.NS", "KEC.NS",
    "ASTERDM.NS", "MAXHEALTH.NS", "NH.NS", "METROPOLIS.NS", "THYROCARE.NS",
    "NYKAA.NS", "DELHIVERY.NS", "POLICYBZR.NS",
    "MFSL.NS", "ICICIGI.NS", "HDFCAMC.NS", "UTIAMC.NS",
    "KANSAINER.NS", "INDHOTEL.NS", "CHALET.NS", "EIHOTEL.NS",
    "CEATLTD.NS", "MRF.NS", "APOLLOTYRE.NS", "BALKRISIND.NS", "TVSSRICHAK.NS",
    "PFIZER.NS", "ABBOTINDIA.NS", "ALKEM.NS", "GLAND.NS",
    "ZYDUSLIFE.NS", "GLENMARK.NS", "NATCOPHARM.NS", "AJANTPHARM.NS", "LAURUSLABS.NS",
    # Additional mid/smallcap Nifty 500 stocks
    "BANKBARODA.NS", "PNB.NS", "CANBK.NS", "UNIONBANK.NS", "INDIANB.NS",
    "DCBBANK.NS", "UJJIVANSFB.NS", "EQUITASBNK.NS", "AUBANK.NS", "SURYAROSNI.NS",
    "EMAMILTD.NS", "VBL.NS", "RADICO.NS", "JYOTHYLAB.NS", "VARUNBEV.NS",
    "CYIENT.NS", "KPIT.NS", "TATAELXSI.NS", "ZENSARTECH.NS", "MASTEK.NS",
    "LTTS.NS", "BSOFT.NS", "HEXAWARE.NS", "NIITLTD.NS", "RATEGAIN.NS",
    "AMARAJABAT.NS", "ENDURANCE.NS", "SUPRAJIT.NS", "CRAFTSMAN.NS", "SUNDRMFAST.NS",
    "SRF.NS", "TATACHEM.NS", "GHCL.NS", "GALAXYSURF.NS", "JUBILANT.NS",
    "OBEROIRLTY.NS", "PRESTIGE.NS", "GODREJPROP.NS", "BRIGADE.NS", "SOBHA.NS",
    "SUNTVNETWORK.NS", "ZEETELE.NS", "PVRINOX.NS", "INOXWIND.NS",
    "HINDCOPPER.NS", "APLAPOLLO.NS", "SHYAMMETL.NS", "KALYANKJIL.NS",
    "APTUS.NS", "HOMEFIRST.NS", "AAVAS.NS", "CANFINHOME.NS", "REPCO.NS",
    "ALEMBICPHARM.NS", "JBCHEPHARM.NS", "IPCA.NS", "SANOFI.NS", "GLAXO.NS",
    "GMRINFRA.NS", "IRB.NS", "SADBHAV.NS", "PNCINFRA.NS", "HGINFRA.NS",
    "TTKPRESTIGE.NS", "HAWKINCOOK.NS", "VSTIND.NS", "GODFRYPHLP.NS",
    "IGL.NS", "MGL.NS", "GUJGASLTD.NS", "ATGL.NS",
    "APOLLOPIPE.NS", "JKCEMENT.NS", "RAMCOCEM.NS", "HEIDELBERG.NS",
    "CLEAN.NS", "INDIGOPNTS.NS", "AKZOINDIA.NS", "SHALPAINTS.NS",
    "TATACOMM.NS", "IDEA.NS", "RAILTEL.NS", "BSNL.NS",
    "TEJASNET.NS", "STLTECH.NS",
    "NAUKRI.NS", "JUSTDIAL.NS", "MAPDIGITAL.NS",
    "BAJAJHLDNG.NS", "MAHINDCIE.NS", "ESCORTS.NS", "VSTTILLERS.NS",
    "WELSPUNLIV.NS", "TRIDENT.NS", "VARDHMANTEXT.NS", "GRASIM.NS",
    "CREDITACC.NS", "SPANDANA.NS", "AROHAN.NS",
    "LAXMIMACH.NS", "TEXRAIL.NS", "MAHSEAMLES.NS", "PENIND.NS",
]


def get_universe(fast: bool = False) -> list[str]:
    """Return Nifty 500 tickers in Yahoo Finance format (symbol.NS)."""
    if fast:
        return NIFTY500_FALLBACK

    # Attempt to fetch a broader list from NSE/Wikipedia; fall back to hardcoded.
    try:
        import io
        import requests

        # Wikipedia does not have a clean Nifty 500 table; use a direct fetch
        # of the NSE-listed CSV if available, otherwise fall through to fallback.
        url = "https://en.wikipedia.org/wiki/NIFTY_500"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        # Look for a table with a "Symbol" column containing NSE tickers
        for df in tables:
            if "Symbol" in df.columns and len(df) >= 100:
                syms = df["Symbol"].astype(str).str.strip().tolist()
                # Add .NS suffix if not already present
                syms = [s if s.endswith(".NS") else s + ".NS" for s in syms]
                print(f"[universe] fetched {len(syms)} symbols from NIFTY 500 wiki")
                return syms
    except Exception as e:
        print(f"[universe] Nifty 500 fetch failed ({e!r}); using fallback list")

    return NIFTY500_FALLBACK


def to_yahoo(symbol: str) -> str:
    """India tickers already carry .NS suffix for Yahoo Finance."""
    return symbol


# =============================================================================
# Data ingestion (yfinance → DuckDB)
# =============================================================================


def _init_db(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open DuckDB. Writer creates tables; reader opens read_only for concurrency."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        return duckdb.connect(str(db_path), read_only=True)
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol VARCHAR,
            date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            adj_close DOUBLE,
            PRIMARY KEY (symbol, date)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS index_prices (
            symbol VARCHAR,
            date DATE,
            close DOUBLE,
            PRIMARY KEY (symbol, date)
        )
    """)
    return con


def _cached_symbols(
    con: duckdb.DuckDBPyConnection,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> set[str]:
    """Return symbols that have at least one row within [start, end] (if given)."""
    if start is not None and end is not None:
        rows = con.execute(
            "SELECT DISTINCT symbol FROM prices WHERE date >= ? AND date <= ?",
            [start.date(), end.date()],
        ).fetchall()
    else:
        rows = con.execute("SELECT DISTINCT symbol FROM prices").fetchall()
    return {r[0] for r in rows}


def download_prices(
    symbols: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_path: Path,
    batch_size: int = 20,
) -> None:
    """Idempotent yfinance → DuckDB. Skips symbols that already have data in [start, end]."""
    import yfinance as yf

    con = _init_db(db_path)
    cached = _cached_symbols(con, start=start, end=end)
    to_fetch = [s for s in symbols if s not in cached]

    if not to_fetch:
        print(f"[data] all {len(symbols)} symbols cached; skipping download")
        con.close()
        return

    print(f"[data] downloading {len(to_fetch)} symbols in batches of {batch_size}")

    for i in range(0, len(to_fetch), batch_size):
        batch = to_fetch[i : i + batch_size]
        yahoo_tickers = [to_yahoo(s) for s in batch]
        try:
            df = yf.download(
                yahoo_tickers,
                start=start.date(),
                end=end.date(),
                auto_adjust=False,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as e:
            print(f"[data] batch failed ({e!r}); skipping")
            time.sleep(2)
            continue

        rows: list[tuple] = []
        for sym, yahoo in zip(batch, yahoo_tickers):
            if yahoo not in df.columns.get_level_values(0):
                continue
            sub = df[yahoo].dropna(how="all")
            for dt, r in sub.iterrows():
                if pd.isna(r.get("Close")):
                    continue
                rows.append((
                    sym,
                    dt.date(),
                    float(r.get("Open", np.nan) or 0),
                    float(r.get("High", np.nan) or 0),
                    float(r.get("Low", np.nan) or 0),
                    float(r["Close"]),
                    int(r.get("Volume", 0) or 0),
                    float(r.get("Adj Close", r["Close"])),
                ))
        if rows:
            con.executemany(
                "INSERT OR IGNORE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
        print(f"[data]   batch {i // batch_size + 1}: {len(rows)} rows inserted")
        time.sleep(0.5)

    con.close()


def download_index(db_path: Path, start: pd.Timestamp, end: pd.Timestamp) -> None:
    """Fetch Nifty 50 index for regime detection. Date-range aware cache check."""
    import yfinance as yf

    con = _init_db(db_path)
    cached_in_range = con.execute(
        "SELECT COUNT(*) FROM index_prices WHERE symbol = ? AND date >= ? AND date <= ?",
        [INDEX_TICKER, start.date(), end.date()],
    ).fetchone()[0]
    if cached_in_range > 100:
        print(f"[data] index {INDEX_TICKER} cached ({cached_in_range} rows in range); skipping")
        con.close()
        return

    df = yf.download(INDEX_TICKER, start=start.date(), end=end.date(), progress=False)
    rows = []
    for dt, r in df.iterrows():
        close = r.get("Close")
        if isinstance(close, pd.Series):
            close = close.iloc[0]
        if pd.isna(close):
            continue
        rows.append((INDEX_TICKER, dt.date(), float(close)))
    con.executemany("INSERT OR IGNORE INTO index_prices VALUES (?, ?, ?)", rows)
    print(f"[data] index {INDEX_TICKER}: {len(rows)} rows")
    con.close()


def load_prices(db_path: Path, read_only: bool = True) -> pd.DataFrame:
    """Return long-form: [date, symbol, close, volume, adj_close]."""
    con = _init_db(db_path, read_only=read_only)
    df = con.execute(
        "SELECT symbol, date, close, volume, adj_close FROM prices ORDER BY symbol, date"
    ).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def load_index(db_path: Path, read_only: bool = True) -> pd.Series:
    con = _init_db(db_path, read_only=read_only)
    df = con.execute(
        "SELECT date, close FROM index_prices WHERE symbol = ? ORDER BY date",
        [INDEX_TICKER],
    ).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["close"]


# =============================================================================
# Universe filters
# =============================================================================


def apply_universe_filters(prices_long: pd.DataFrame) -> pd.DataFrame:
    """Filter to symbols meeting listing, liquidity, and price rules."""
    close = prices_long.pivot(index="date", columns="symbol", values="adj_close")

    required_history_start = TRAINING_START - pd.DateOffset(months=13)
    first_seen = close.apply(lambda s: s.first_valid_index())
    listing_ok = first_seen.apply(
        lambda fv: pd.notna(fv) and (fv <= required_history_start)
    )

    eligible_symbols = listing_ok[listing_ok].index.tolist()
    print(
        f"[filter] listing filter (>= 13m history at training start): "
        f"{len(eligible_symbols)} of {len(close.columns)}"
    )

    return prices_long[prices_long["symbol"].isin(eligible_symbols)].copy()


def per_rebalance_universe(
    close: pd.DataFrame,
    liquidity_60d: pd.DataFrame,
    rebalance_date: pd.Timestamp,
) -> list[str]:
    """Symbols eligible on this rebalance date."""
    if rebalance_date not in close.index:
        return []
    price_ok = close.loc[rebalance_date] > PRICE_FLOOR_INR
    if rebalance_date in liquidity_60d.index:
        liq_ok = liquidity_60d.loc[rebalance_date] > LIQUIDITY_THRESHOLD_INR
    else:
        liq_ok = pd.Series(False, index=price_ok.index)
    return price_ok[price_ok & liq_ok].index.tolist()


# =============================================================================
# Signals
# =============================================================================


def compute_momentum(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """12-1 momentum: return from t-13m to t-1m. Cross-sectionally rank-normalized."""
    lookback = MOMENTUM_LOOKBACK_MONTHS * 21
    skip = MOMENTUM_SKIP_MONTHS * 21
    past = close_wide.shift(skip)
    older = close_wide.shift(lookback)
    raw_momentum = past / older - 1.0
    return raw_momentum.rank(axis=1, pct=True)


MEAN_REVERSION_WINDOW_DAYS = 20


def compute_mean_reversion(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Short-term mean reversion — Jegadeesh (1990).

    Ranks by the inverse of the 20-day return: recent losers score high,
    recent winners score low. Cross-sectionally ranked per date.
    """
    past_return = close_wide.pct_change(MEAN_REVERSION_WINDOW_DAYS)
    inverted = -past_return
    return inverted.rank(axis=1, pct=True)


LOW_VOL_WINDOW_DAYS = 60


def compute_low_vol(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Long-low-vol / short-high-vol. Kept for reference; not in AGENTS."""
    log_returns = np.log(close_wide / close_wide.shift(1))
    realized_vol = log_returns.rolling(LOW_VOL_WINDOW_DAYS).std() * np.sqrt(252)
    return (-realized_vol).rank(axis=1, pct=True)


# GICS sector assignments for Nifty 500 fallback universe.
NIFTY500_SECTOR_MAP: dict[str, str] = {
    # Information Technology
    "TCS.NS": "Information Technology", "INFY.NS": "Information Technology",
    "WIPRO.NS": "Information Technology", "HCLTECH.NS": "Information Technology",
    "TECHM.NS": "Information Technology", "OFSS.NS": "Information Technology",
    "MPHASIS.NS": "Information Technology", "PERSISTENT.NS": "Information Technology",
    "COFORGE.NS": "Information Technology", "LTIM.NS": "Information Technology",
    # Financials
    "HDFCBANK.NS": "Financials", "ICICIBANK.NS": "Financials",
    "KOTAKBANK.NS": "Financials", "AXISBANK.NS": "Financials",
    "SBIN.NS": "Financials", "INDUSINDBK.NS": "Financials",
    "BANDHANBNK.NS": "Financials", "FEDERALBNK.NS": "Financials",
    "RBLBANK.NS": "Financials", "IDFCFIRSTB.NS": "Financials",
    "BAJFINANCE.NS": "Financials", "BAJAJFINSV.NS": "Financials",
    "SBILIFE.NS": "Financials", "HDFCLIFE.NS": "Financials",
    "MFSL.NS": "Financials", "ICICIGI.NS": "Financials",
    "HDFCAMC.NS": "Financials", "UTIAMC.NS": "Financials",
    "CHOLAFIN.NS": "Financials", "MANAPPURAM.NS": "Financials",
    "LICHSGFIN.NS": "Financials", "SUNDARMFIN.NS": "Financials",
    "M&MFIN.NS": "Financials", "MUTHOOTFIN.NS": "Financials",
    "KARURVYSYA.NS": "Financials",
    # Consumer Staples
    "HINDUNILVR.NS": "Consumer Staples", "NESTLEIND.NS": "Consumer Staples",
    "BRITANNIA.NS": "Consumer Staples", "DABUR.NS": "Consumer Staples",
    "MARICO.NS": "Consumer Staples", "GODREJCP.NS": "Consumer Staples",
    "COLPAL.NS": "Consumer Staples", "TATACONSUM.NS": "Consumer Staples",
    "PGHH.NS": "Consumer Staples",
    # Consumer Discretionary
    "MARUTI.NS": "Consumer Discretionary", "M&M.NS": "Consumer Discretionary",
    "BAJAJ-AUTO.NS": "Consumer Discretionary", "HEROMOTOCO.NS": "Consumer Discretionary",
    "EICHERMOT.NS": "Consumer Discretionary", "TITAN.NS": "Consumer Discretionary",
    "TRENT.NS": "Consumer Discretionary", "VMART.NS": "Consumer Discretionary",
    "PAGEIND.NS": "Consumer Discretionary", "JUBLFOOD.NS": "Consumer Discretionary",
    "WESTLIFE.NS": "Consumer Discretionary", "DEVYANI.NS": "Consumer Discretionary",
    "SAPPHIRE.NS": "Consumer Discretionary", "MANYAVAR.NS": "Consumer Discretionary",
    "INDHOTEL.NS": "Consumer Discretionary", "CHALET.NS": "Consumer Discretionary",
    "EIHOTEL.NS": "Consumer Discretionary", "MRF.NS": "Consumer Discretionary",
    "CEATLTD.NS": "Consumer Discretionary", "APOLLOTYRE.NS": "Consumer Discretionary",
    "BALKRISIND.NS": "Consumer Discretionary", "TVSSRICHAK.NS": "Consumer Discretionary",
    # Health Care
    "SUNPHARMA.NS": "Health Care", "DIVISLAB.NS": "Health Care",
    "DRREDDY.NS": "Health Care", "CIPLA.NS": "Health Care",
    "LUPIN.NS": "Health Care", "AUROPHARMA.NS": "Health Care",
    "BIOCON.NS": "Health Care", "TORNTPHARM.NS": "Health Care",
    "PFIZER.NS": "Health Care", "ABBOTINDIA.NS": "Health Care",
    "ALKEM.NS": "Health Care", "GLAND.NS": "Health Care",
    "ZYDUSLIFE.NS": "Health Care", "GLENMARK.NS": "Health Care",
    "NATCOPHARM.NS": "Health Care", "AJANTPHARM.NS": "Health Care",
    "LAURUSLABS.NS": "Health Care", "IPCA.NS": "Health Care",
    "METROPOLIS.NS": "Health Care", "THYROCARE.NS": "Health Care",
    "ASTERDM.NS": "Health Care", "MAXHEALTH.NS": "Health Care",
    "NH.NS": "Health Care",
    # Energy
    "RELIANCE.NS": "Energy", "ONGC.NS": "Energy", "BPCL.NS": "Energy",
    "IOC.NS": "Energy", "GAIL.NS": "Energy", "PETRONET.NS": "Energy",
    "HINDPETRO.NS": "Energy", "TATAPOWER.NS": "Energy",
    "TORNTPOWER.NS": "Energy", "CESC.NS": "Energy",
    # Materials
    "TATASTEEL.NS": "Materials", "JSWSTEEL.NS": "Materials",
    "HINDALCO.NS": "Materials", "SAIL.NS": "Materials",
    "NMDC.NS": "Materials", "AMBUJACEM.NS": "Materials",
    "ACC.NS": "Materials", "SHREECEM.NS": "Materials",
    "ULTRACEMCO.NS": "Materials", "JSPL.NS": "Materials",
    "RATNAMANI.NS": "Materials", "WELCORP.NS": "Materials",
    "PIDILITIND.NS": "Materials", "KANSAINER.NS": "Materials",
    "PIIND.NS": "Materials", "RALLIS.NS": "Materials",
    "COROMANDEL.NS": "Materials", "GNFC.NS": "Materials",
    "DEEPAKNTR.NS": "Materials", "AARTIIND.NS": "Materials",
    "NAVINFLUOR.NS": "Materials", "SUDARSCHEM.NS": "Materials",
    "VINATIORGA.NS": "Materials", "FINEORG.NS": "Materials",
    "ATUL.NS": "Materials", "NOCIL.NS": "Materials",
    "BALAMINES.NS": "Materials",
    # Industrials
    "LT.NS": "Industrials", "SIEMENS.NS": "Industrials",
    "BHEL.NS": "Industrials", "HAL.NS": "Industrials",
    "BEL.NS": "Industrials", "CONCOR.NS": "Industrials",
    "IRCTC.NS": "Industrials", "RVNL.NS": "Industrials",
    "IRFC.NS": "Industrials", "NBCC.NS": "Industrials",
    "NCC.NS": "Industrials", "KEC.NS": "Industrials",
    "BOSCHLTD.NS": "Industrials", "CUMMINSIND.NS": "Industrials",
    "THERMAX.NS": "Industrials", "GRINDWELL.NS": "Industrials",
    "TIMKEN.NS": "Industrials", "SCHAEFFLER.NS": "Industrials",
    "MOTHERSON.NS": "Industrials", "POLYCAB.NS": "Industrials",
    "KEI.NS": "Industrials", "SCHNEIDER.NS": "Industrials",
    "CROMPTON.NS": "Industrials", "VOLTAS.NS": "Industrials",
    "BLUESTARCO.NS": "Industrials", "WHIRLPOOL.NS": "Industrials",
    "SYMPHONY.NS": "Industrials", "HAVELLS.NS": "Industrials",
    "ASIANPAINT.NS": "Industrials", "BERGEPAINT.NS": "Industrials",
    # Communication Services
    "BHARTIARTL.NS": "Communication Services",
    "ZOMATO.NS": "Communication Services", "NYKAA.NS": "Communication Services",
    "DELHIVERY.NS": "Communication Services", "POLICYBZR.NS": "Communication Services",
    "PAYTM.NS": "Communication Services",
    # Utilities
    "NTPC.NS": "Utilities", "POWERGRID.NS": "Utilities",
    "COALINDIA.NS": "Utilities",
    # Real Estate / Conglomerates
    "ADANIENT.NS": "Industrials", "ADANIPORTS.NS": "Industrials",
    "GRASIM.NS": "Materials",
    # Consumer Discretionary (continued)
    "UPL.NS": "Materials",
}


def get_sector_map(fast: bool = False) -> dict[str, str]:
    """Return GICS sector assignments for universe tickers."""
    return NIFTY500_SECTOR_MAP.copy()


def compute_sector_neutral_mean_reversion(
    close_wide: pd.DataFrame,
    sector_map: dict[str, str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Sector-neutralized 20-day mean reversion.

    Subtracts the GICS sector median 20-day return before ranking so the
    signal captures only idiosyncratic reversion, not sector-level drift.
    Degrades to raw mean_reversion if sector_map is None or empty.
    """
    past_return = close_wide.pct_change(MEAN_REVERSION_WINDOW_DAYS)

    if not sector_map:
        return (-past_return).rank(axis=1, pct=True)

    symbols = close_wide.columns.tolist()
    sym_to_sector = pd.Series(
        {s: sector_map.get(s, "Unknown") for s in symbols}, name="sector"
    )

    idio_return = past_return.copy()
    for sector, group_syms in sym_to_sector.groupby(sym_to_sector).groups.items():
        group_syms = [s for s in group_syms if s in past_return.columns]
        if len(group_syms) < 2:
            continue
        sector_median = past_return[group_syms].median(axis=1)
        idio_return[group_syms] = past_return[group_syms].sub(sector_median, axis=0)

    return (-idio_return).rank(axis=1, pct=True)


# Agent registry — India v0.3: mean_reversion + sector_neutral_mr + momentum.
AGENTS: dict[str, callable] = {
    "mean_reversion": compute_mean_reversion,
    "sector_neutral_mr": compute_sector_neutral_mean_reversion,
    "momentum": compute_momentum,
}


def compute_ensemble(signals_by_agent: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Equal-weight ensemble of per-Agent rank signals."""
    if not signals_by_agent:
        raise ValueError("no signals provided")
    frames = list(signals_by_agent.values())
    total = frames[0].copy()
    for f in frames[1:]:
        total = total.add(f, fill_value=np.nan)
    avg = total / len(frames)
    return avg.rank(axis=1, pct=True)


# =============================================================================
# Regime — 2×2 Vol × Trend
# =============================================================================


def compute_regime(index_close: pd.Series) -> pd.DataFrame:
    """Return DataFrame with columns [vol_regime, trend_regime, regime]."""
    returns = index_close.pct_change()
    vol_60d = returns.rolling(VOL_WINDOW_DAYS).std() * np.sqrt(252)

    vol_percentile = pd.Series(index=vol_60d.index, dtype=float)
    for i, dt in enumerate(vol_60d.index):
        if i < VOL_WINDOW_DAYS:
            continue
        window = vol_60d.iloc[max(0, i - VOL_PERCENTILE_WINDOW_DAYS + 1) : i + 1]
        current = vol_60d.iloc[i]
        if pd.isna(current) or window.dropna().empty:
            continue
        vol_percentile.iloc[i] = (window <= current).mean()

    vol_regime = np.where(vol_percentile < 0.5, "LOW_VOL", "HIGH_VOL")

    ma_200 = index_close.rolling(MA_WINDOW).mean()
    trend_slope = (ma_200 - ma_200.shift(TREND_LOOKBACK_DAYS)) / ma_200.shift(
        TREND_LOOKBACK_DAYS
    )
    trend_regime = np.where(trend_slope > 0, "UP_TREND", "DOWN_TREND")

    out = pd.DataFrame(
        {
            "vol_percentile": vol_percentile,
            "vol_regime": vol_regime,
            "trend_slope": trend_slope,
            "trend_regime": trend_regime,
        },
        index=index_close.index,
    )
    out["regime"] = out["vol_regime"] + "_" + out["trend_regime"]
    unknown_mask = out["vol_percentile"].isna() | pd.isna(trend_slope)
    out.loc[unknown_mask, "regime"] = "UNKNOWN"
    return out


# =============================================================================
# Backtest — decile long-short, monthly rebalance
# =============================================================================


def month_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Last trading day of each calendar month in the (trading-day) index."""
    if len(index) == 0:
        return []
    df = pd.DataFrame({"date": pd.DatetimeIndex(index)})
    df["period"] = df["date"].dt.to_period("M")
    return df.groupby("period")["date"].max().tolist()


@dataclass
class BacktestResult:
    monthly_returns: pd.Series
    signal_at_rebalance: dict
    forward_returns: dict
    regime_at_rebalance: pd.Series
    turnover: pd.Series


def run_backtest(
    close_wide: pd.DataFrame,
    momentum: pd.DataFrame,
    liquidity_60d: pd.DataFrame,
    regime_df: pd.DataFrame,
    training_start: pd.Timestamp,
    training_end: pd.Timestamp,
    cost_bps: int,
) -> BacktestResult:
    """Monthly rebalance decile long-short. Enforces training bounds."""
    assert training_end < HELD_OUT_START, "training bounds violate held-out lock"

    dates = close_wide.index
    rebalance_dates = [
        d for d in month_end_dates(dates) if training_start <= d <= training_end
    ]

    monthly_returns = []
    signals_snapshot: dict = {}
    fwd_snapshot: dict = {}
    regime_snapshot = {}
    turnovers = []

    prev_long: set[str] = set()
    prev_short: set[str] = set()

    min_eligible = min(20, max(10, close_wide.shape[1] // 2))

    for i, rb in enumerate(rebalance_dates[:-1]):
        next_rb = rebalance_dates[i + 1]
        elig = per_rebalance_universe(close_wide, liquidity_60d, rb)
        if len(elig) < min_eligible:
            continue

        momo_today = momentum.loc[rb, elig].dropna()
        if len(momo_today) < min_eligible:
            continue

        momo_ranked = momo_today.rank(pct=True)
        n = len(momo_ranked)
        top_cut = 1.0 - 1.0 / DECILES
        bot_cut = 1.0 / DECILES
        long_names = momo_ranked[momo_ranked >= top_cut].index.tolist()
        short_names = momo_ranked[momo_ranked <= bot_cut].index.tolist()

        fwd = (close_wide.loc[next_rb, elig] / close_wide.loc[rb, elig] - 1.0).dropna()

        long_ret = fwd.reindex(long_names).mean()
        short_ret = fwd.reindex(short_names).mean()
        gross_ls = long_ret - short_ret

        new_long = len(set(long_names) - prev_long) / max(len(long_names), 1)
        new_short = len(set(short_names) - prev_short) / max(len(short_names), 1)
        turnover_fraction = 0.5 * (new_long + new_short)
        cost = turnover_fraction * (cost_bps / 10_000.0)
        net_ls = gross_ls - cost

        monthly_returns.append((rb, net_ls))
        signals_snapshot[rb.strftime("%Y-%m-%d")] = momo_ranked.to_dict()
        fwd_snapshot[rb.strftime("%Y-%m-%d")] = fwd.to_dict()
        regime_snapshot[rb] = (
            regime_df.loc[rb, "regime"] if rb in regime_df.index else "UNKNOWN"
        )
        turnovers.append((rb, turnover_fraction))

        prev_long = set(long_names)
        prev_short = set(short_names)

    if not monthly_returns:
        raise RuntimeError("no rebalances produced returns — check data / filters")

    idx, vals = zip(*monthly_returns)
    mr = pd.Series(vals, index=pd.DatetimeIndex(idx), name="ls_return")
    reg_ser = pd.Series(regime_snapshot, name="regime")
    tv_idx, tv_vals = zip(*turnovers)
    tv = pd.Series(tv_vals, index=pd.DatetimeIndex(tv_idx), name="turnover")

    return BacktestResult(
        monthly_returns=mr,
        signal_at_rebalance=signals_snapshot,
        forward_returns=fwd_snapshot,
        regime_at_rebalance=reg_ser,
        turnover=tv,
    )


# =============================================================================
# Metrics — IC, DSR (PSR), Regime Scorecard
# =============================================================================


def compute_ic_per_rebalance(signals: dict, forwards: dict) -> pd.Series:
    """Spearman rank IC per rebalance."""
    out = {}
    for d, sig in signals.items():
        fwd = forwards.get(d, {})
        common = sig.keys() & fwd.keys()
        if len(common) < 20:
            continue
        s = np.array([sig[c] for c in common])
        f = np.array([fwd[c] for c in common])
        if np.std(s) == 0 or np.std(f) == 0:
            continue
        rho, _ = stats.spearmanr(s, f)
        out[pd.Timestamp(d)] = float(rho)
    return pd.Series(out, name="ic").sort_index()


def compute_regime_scorecard(
    ic_series: pd.Series, regime_at_rebalance: pd.Series
) -> pd.DataFrame:
    df = pd.DataFrame({"ic": ic_series, "regime": regime_at_rebalance}).dropna()
    grouped = df.groupby("regime")["ic"].agg(["mean", "count"])
    return grouped


def compute_dsr(returns: pd.Series, benchmark_sr: float = 0.0) -> dict:
    """Probabilistic Sharpe Ratio (Bailey-López de Prado 2012/2014).

    Monthly returns → Sharpe annualized by sqrt(12).
    """
    r = returns.dropna()
    T = len(r)
    if T < 12:
        return {"sharpe_annualized": float("nan"), "psr": float("nan"), "T": T}

    mean_r = r.mean()
    std_r = r.std(ddof=1)
    if std_r == 0:
        return {"sharpe_annualized": 0.0, "psr": 0.0, "T": T}
    sr_monthly = mean_r / std_r
    sr_ann = sr_monthly * np.sqrt(12)

    skew = float(stats.skew(r, bias=False))
    excess_kurt = float(stats.kurtosis(r, fisher=True, bias=False))

    denom = np.sqrt(1 - skew * sr_monthly + ((excess_kurt + 2) / 4.0) * sr_monthly**2)
    if denom <= 0 or np.isnan(denom):
        return {"sharpe_annualized": float(sr_ann), "psr": float("nan"), "T": T}
    z = (sr_monthly - benchmark_sr) * np.sqrt(T - 1) / denom
    psr = float(stats.norm.cdf(z))

    return {
        "sharpe_monthly": float(sr_monthly),
        "sharpe_annualized": float(sr_ann),
        "psr": psr,
        "T": T,
        "skew": skew,
        "excess_kurtosis": excess_kurt,
    }


# =============================================================================
# Max Drawdown
# =============================================================================


def compute_max_drawdown(monthly_returns: pd.Series) -> dict:
    """Max drawdown of the equity curve implied by monthly_returns."""
    r = monthly_returns.dropna()
    if len(r) == 0:
        return {"max_drawdown": 0.0, "peak_date": None, "trough_date": None,
                "recovery_date": None, "duration_months": None, "recovery_months": None}
    equity = (1 + r).cumprod()
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    trough_date = dd.idxmin()
    max_dd = float(dd.loc[trough_date])
    peak_slice = equity.loc[:trough_date]
    peak_date = peak_slice[peak_slice == running_max.loc[trough_date]].index[0]
    post = equity.loc[trough_date:]
    recovery_mask = post >= running_max.loc[trough_date]
    recovery_date = post[recovery_mask].index[0] if recovery_mask.any() else None
    duration_months = int(
        (trough_date.year - peak_date.year) * 12 + (trough_date.month - peak_date.month)
    )
    recovery_months = None
    if recovery_date is not None:
        recovery_months = int(
            (recovery_date.year - trough_date.year) * 12
            + (recovery_date.month - trough_date.month)
        )
    return {
        "max_drawdown": max_dd,
        "peak_date": peak_date,
        "trough_date": trough_date,
        "recovery_date": recovery_date,
        "duration_months": duration_months,
        "recovery_months": recovery_months,
    }


# =============================================================================
# Meta-Learner (v0.3) — IC-weighted signal combining
# =============================================================================

META_IC_WINDOW_MONTHS = 24
META_MIN_WEIGHT = 0.05
META_MAX_WEIGHT_FLOOR = 0.30
META_SHRINKAGE = 0.5
META_RESET_EVERY_MONTHS = 12


def dynamic_max_weight(n_agents: int) -> float:
    """Contract v1.2: cap = max(0.30, 1.2 / n_agents). See ADR-0005."""
    if n_agents <= 0:
        return META_MAX_WEIGHT_FLOOR
    return max(META_MAX_WEIGHT_FLOOR, 1.2 / n_agents)


def _compute_meta_weights_for_step(
    agent_names: list[str],
    ic_history_by_agent: dict[str, list[float]],
    step_index: int,
    window: int,
    min_w: float,
    max_w: float,
    shrinkage: float,
    reset_every: int,
) -> dict[str, float]:
    """Return weights for the next rebalance given per-Agent IC history so far."""
    n = len(agent_names)
    equal = 1.0 / n
    equal_weights = {a: equal for a in agent_names}

    if step_index < window or (reset_every > 0 and step_index % reset_every == 0):
        return equal_weights

    mean_ic = {}
    for a in agent_names:
        recent = ic_history_by_agent.get(a, [])[-window:]
        if not recent:
            return equal_weights
        mean_ic[a] = float(np.mean(recent))

    pos = {a: max(0.0, ic) for a, ic in mean_ic.items()}
    total_pos = sum(pos.values())
    if total_pos <= 0:
        raw = equal_weights.copy()
    else:
        raw = {a: pos[a] / total_pos for a in agent_names}

    shrunk = {a: shrinkage * equal + (1 - shrinkage) * raw[a] for a in agent_names}
    clipped = {a: min(max_w, max(min_w, shrunk[a])) for a in agent_names}
    s = sum(clipped.values())
    return {a: clipped[a] / s for a in agent_names}


@dataclass
class MetaEnsembleResult:
    monthly_returns: pd.Series
    signal_at_rebalance: dict
    forward_returns: dict
    regime_at_rebalance: pd.Series
    turnover: pd.Series
    weights_at_rebalance: pd.DataFrame
    per_agent_ic_at_rebalance: pd.DataFrame
    skipped_months: int   # count of LOW_VOL_UP_TREND-gated months


def run_meta_ensemble_backtest(
    signals_by_agent: dict[str, pd.DataFrame],
    close_wide: pd.DataFrame,
    liquidity_60d: pd.DataFrame,
    regime_df: pd.DataFrame,
    training_start: pd.Timestamp,
    training_end: pd.Timestamp,
    cost_bps: int,
    ic_window_months: int = META_IC_WINDOW_MONTHS,
    min_weight: float = META_MIN_WEIGHT,
    max_weight: float | None = None,
    shrinkage: float = META_SHRINKAGE,
    reset_every_months: int = META_RESET_EVERY_MONTHS,
    heldout_mode: bool = False,
    skip_regimes: frozenset[str] | None = None,
    regime_signal_weights: dict[str, dict[str, float]] | None = None,
) -> MetaEnsembleResult:
    """Backtest the ensemble with a dynamic IC-weighted Meta-Learner.

    skip_regimes: hard gate — skip months in these regimes, record 0.0 return.
    regime_signal_weights: override IC-learned weights for specific regimes.
        Format: {regime_label: {agent_name: weight, ...}}
        Weights are normalised to sum to 1. Agents not listed get weight 0.
    """
    if not heldout_mode:
        assert training_end < HELD_OUT_START, "training/held-out overlap"

    agent_names = list(signals_by_agent.keys())
    ic_history: dict[str, list[float]] = {a: [] for a in agent_names}

    if max_weight is None:
        max_weight = dynamic_max_weight(len(agent_names))

    rebalance_dates = [
        d for d in month_end_dates(close_wide.index) if training_start <= d <= training_end
    ]
    min_eligible = min(20, max(10, close_wide.shape[1] // 2))

    monthly_returns = []
    signals_snapshot: dict = {}
    fwd_snapshot: dict = {}
    regime_snapshot = {}
    turnovers = []
    weights_records = []
    ic_records = []
    skipped_count = 0

    prev_long: set[str] = set()
    prev_short: set[str] = set()

    for i, rb in enumerate(rebalance_dates[:-1]):
        next_rb = rebalance_dates[i + 1]

        # Determine regime at this rebalance date
        regime_label = (
            regime_df.loc[rb, "regime"] if rb in regime_df.index else "UNKNOWN"
        )
        regime_snapshot[rb] = regime_label

        # Hard gate: skip if regime is hostile
        if skip_regimes and regime_label in skip_regimes:
            monthly_returns.append((rb, 0.0))
            turnovers.append((rb, 0.0))
            skipped_count += 1
            # prev_long/prev_short unchanged — no portfolio change
            continue

        elig = per_rebalance_universe(close_wide, liquidity_60d, rb)
        if len(elig) < min_eligible:
            continue

        weights = _compute_meta_weights_for_step(
            agent_names, ic_history, i, ic_window_months,
            min_weight, max_weight, shrinkage, reset_every_months,
        )

        # Regime-conditional weight override: replace IC-learned weights with
        # regime-specific assignments (e.g. momentum in UP_TREND, MR in DOWN).
        if regime_signal_weights and regime_label in regime_signal_weights:
            override = regime_signal_weights[regime_label]
            total = sum(override.get(a, 0.0) for a in agent_names)
            if total > 0:
                weights = {a: override.get(a, 0.0) / total for a in agent_names}

        weights_records.append({"date": rb, **weights})

        weighted_score = pd.Series(0.0, index=elig, dtype=float)
        weight_mass = pd.Series(0.0, index=elig, dtype=float)
        for a, sig_df in signals_by_agent.items():
            agent_sig = sig_df.loc[rb, elig].dropna() if rb in sig_df.index else pd.Series(dtype=float)
            if agent_sig.empty:
                continue
            weighted_score.loc[agent_sig.index] += agent_sig * weights[a]
            weight_mass.loc[agent_sig.index] += weights[a]
        with np.errstate(divide="ignore", invalid="ignore"):
            score = (weighted_score / weight_mass).replace([np.inf, -np.inf], np.nan).dropna()
        if len(score) < min_eligible:
            continue
        ensemble_rank = score.rank(pct=True)

        top_cut = 1.0 - 1.0 / DECILES
        bot_cut = 1.0 / DECILES
        long_names = ensemble_rank[ensemble_rank >= top_cut].index.tolist()
        short_names = ensemble_rank[ensemble_rank <= bot_cut].index.tolist()

        fwd = (close_wide.loc[next_rb, elig] / close_wide.loc[rb, elig] - 1.0).dropna()

        long_ret = fwd.reindex(long_names).mean()
        short_ret = fwd.reindex(short_names).mean()
        gross_ls = long_ret - short_ret

        new_long = len(set(long_names) - prev_long) / max(len(long_names), 1)
        new_short = len(set(short_names) - prev_short) / max(len(short_names), 1)
        turnover_fraction = 0.5 * (new_long + new_short)
        cost = turnover_fraction * (cost_bps / 10_000.0)
        net_ls = gross_ls - cost

        monthly_returns.append((rb, net_ls))
        signals_snapshot[rb.strftime("%Y-%m-%d")] = ensemble_rank.to_dict()
        fwd_snapshot[rb.strftime("%Y-%m-%d")] = fwd.to_dict()
        turnovers.append((rb, turnover_fraction))

        ic_row = {"date": rb}
        for a, sig_df in signals_by_agent.items():
            if rb not in sig_df.index:
                ic_row[a] = np.nan
                continue
            agent_sig = sig_df.loc[rb, elig].dropna()
            common = agent_sig.index.intersection(fwd.index)
            if len(common) < 20:
                ic_row[a] = np.nan
                continue
            rho, _ = stats.spearmanr(agent_sig.loc[common], fwd.loc[common])
            rho_f = float(rho)
            ic_row[a] = rho_f
            if not np.isnan(rho_f):
                ic_history[a].append(rho_f)
        ic_records.append(ic_row)

        prev_long = set(long_names)
        prev_short = set(short_names)

    if not monthly_returns:
        raise RuntimeError("no rebalances produced returns in meta-ensemble")

    idx, vals = zip(*monthly_returns)
    mr = pd.Series(vals, index=pd.DatetimeIndex(idx), name="ls_return")
    reg_ser = pd.Series(regime_snapshot, name="regime")
    tv_idx, tv_vals = zip(*turnovers)
    tv = pd.Series(tv_vals, index=pd.DatetimeIndex(tv_idx), name="turnover")

    weights_df = pd.DataFrame(weights_records).set_index("date") if weights_records else pd.DataFrame()
    ic_df = pd.DataFrame(ic_records).set_index("date") if ic_records else pd.DataFrame()

    return MetaEnsembleResult(
        monthly_returns=mr,
        signal_at_rebalance=signals_snapshot,
        forward_returns=fwd_snapshot,
        regime_at_rebalance=reg_ser,
        turnover=tv,
        weights_at_rebalance=weights_df,
        per_agent_ic_at_rebalance=ic_df,
        skipped_months=skipped_count,
    )


# =============================================================================
# Walk-forward validation
# =============================================================================


def compute_walkforward_folds(
    monthly_returns: pd.Series,
    fold_years: int = 1,
    min_months_per_fold: int = 6,
) -> pd.DataFrame:
    """Slice a full backtest into per-year folds for stability analysis."""
    if monthly_returns.empty:
        return pd.DataFrame()
    df = monthly_returns.to_frame("ret")
    df["fold"] = (df.index.year // fold_years) * fold_years

    records = []
    for fold, group in df.groupby("fold"):
        r = group["ret"]
        if len(r) < min_months_per_fold:
            continue
        dsr = compute_dsr(r)
        dd = compute_max_drawdown(r)
        records.append({
            "fold_start": int(fold),
            "n_months": int(len(r)),
            "cum_return": float((1 + r).prod() - 1),
            "sharpe_annualized": float(dsr["sharpe_annualized"]),
            "dsr_psr": float(dsr["psr"]),
            "max_drawdown": float(dd["max_drawdown"]),
        })
    return pd.DataFrame(records)


def compute_multi_trial_deflated_sharpe(
    fold_sharpes: pd.Series,
    T_per_fold: int,
    n_trials: int,
) -> dict:
    """Bailey-López de Prado deflated Sharpe corrected for N independent trials."""
    r = fold_sharpes.dropna()
    if len(r) < 2 or n_trials < 2:
        return {"dsr_multi_trial": float("nan"), "sr_expected_null": float("nan"),
                "mean_sr": float(r.mean()) if len(r) else float("nan"),
                "n_trials": n_trials, "n_folds": len(r)}

    gamma = 0.5772156649
    v_sr = float(r.var(ddof=1))
    if not np.isfinite(v_sr) or v_sr <= 0:
        return {"dsr_multi_trial": float("nan"), "sr_expected_null": 0.0,
                "mean_sr": float(r.mean()), "n_trials": n_trials, "n_folds": len(r)}

    sr_null = np.sqrt(v_sr) * (
        (1 - gamma) * stats.norm.ppf(1 - 1.0 / n_trials)
        + gamma * stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
    )
    mean_sr = float(r.mean())
    skew = float(stats.skew(r, bias=False))
    excess_kurt = float(stats.kurtosis(r, fisher=True, bias=False))
    T = T_per_fold
    denom = np.sqrt(1 - skew * mean_sr + ((excess_kurt + 2) / 4.0) * mean_sr**2)
    if denom <= 0 or not np.isfinite(denom):
        z = (mean_sr - sr_null) * np.sqrt(max(T - 1, 1))
    else:
        z = (mean_sr - sr_null) * np.sqrt(max(T - 1, 1)) / denom
    dsr = float(stats.norm.cdf(z))
    return {
        "dsr_multi_trial": dsr,
        "sr_expected_null": float(sr_null),
        "mean_sr": mean_sr,
        "n_trials": n_trials,
        "n_folds": len(r),
    }


def summarize_walkforward(folds: pd.DataFrame) -> dict:
    if folds.empty:
        return {}
    s = folds["sharpe_annualized"]
    return {
        "n_folds": int(len(folds)),
        "mean_sharpe": float(s.mean()),
        "median_sharpe": float(s.median()),
        "min_sharpe": float(s.min()),
        "max_sharpe": float(s.max()),
        "std_sharpe": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        "positive_folds": int((s > 0).sum()),
        "positive_fold_rate": float((s > 0).mean()),
        "mean_max_dd": float(folds["max_drawdown"].mean()),
        "worst_max_dd": float(folds["max_drawdown"].min()),
    }


# =============================================================================
# Gate evaluators
# =============================================================================

MIN_REGIME_REBALANCES = 10


def evaluate_gate_g1(
    dsr_result: dict, scorecard: pd.DataFrame, threshold_dsr: float = 0.5,
    min_regime_n: int = MIN_REGIME_REBALANCES,
) -> dict:
    """Gate G1 per contract v1.1."""
    dsr = dsr_result.get("psr", 0.0)
    dsr_pass = dsr >= threshold_dsr

    real = scorecard.drop(index="UNKNOWN", errors="ignore")
    eligible = real[real["count"] >= min_regime_n]
    insufficient = real[real["count"] < min_regime_n]

    positive = int((eligible["mean"] > 0).sum())
    eligible_total = int(len(eligible))
    required_positive = eligible_total - 1
    regime_pass = eligible_total >= 3 and positive >= required_positive

    verdict = "PASS" if (dsr_pass and regime_pass) else "FAIL"

    return {
        "verdict": verdict,
        "threshold_dsr": threshold_dsr,
        "observed_dsr_psr": dsr,
        "dsr_pass": bool(dsr_pass),
        "regime_pass": bool(regime_pass),
        "regime_positive_count": positive,
        "regime_total_evaluated": eligible_total,
        "regime_min_n": min_regime_n,
        "regime_required_positive": required_positive,
        "regimes_insufficient_sample": insufficient.index.tolist(),
        "sharpe_annualized": dsr_result.get("sharpe_annualized"),
        "num_monthly_observations": dsr_result.get("T"),
    }


def evaluate_gate_g2(
    dsr_result: dict, dd_result: dict,
    threshold_sharpe: float = 1.0,
    threshold_psr: float = 0.90,
    threshold_max_dd: float = 0.25,
) -> dict:
    """Gate G2: ensemble validation on training set.

    Contract §5 (v1.3): Sharpe ≥ 1.0, PSR ≥ 0.90, MaxDD ≤ 25%.
    """
    sharpe = float(dsr_result.get("sharpe_annualized", 0.0))
    psr = float(dsr_result.get("psr", 0.0))
    sharpe_pass = sharpe >= threshold_sharpe
    psr_pass = psr >= threshold_psr
    max_dd = abs(float(dd_result.get("max_drawdown", 0.0)))
    dd_pass = max_dd <= threshold_max_dd
    verdict = "PASS" if (sharpe_pass and psr_pass and dd_pass) else "FAIL"
    return {
        "verdict": verdict,
        "threshold_sharpe": threshold_sharpe,
        "threshold_psr": threshold_psr,
        "threshold_max_dd": threshold_max_dd,
        "observed_sharpe": sharpe,
        "observed_psr": psr,
        "observed_dsr": psr,
        "observed_max_dd": max_dd,
        "sharpe_pass": bool(sharpe_pass),
        "psr_pass": bool(psr_pass),
        "dsr_pass": bool(sharpe_pass),
        "dd_pass": bool(dd_pass),
    }


def evaluate_gate_g3(
    training_dsr: float,
    heldout_dsr_result: dict,
    heldout_dd_result: dict,
    heldout_scorecard: pd.DataFrame,
    training_dsr_threshold_ratio: float = 0.6,
    threshold_max_dd: float = 0.25,
    min_regime_n: int = MIN_REGIME_REBALANCES,
) -> dict:
    """Gate G3 per contract §5 (v1.3)."""
    ho_dsr = heldout_dsr_result.get("psr", 0.0)
    required_dsr = training_dsr * training_dsr_threshold_ratio
    dsr_pass = ho_dsr >= required_dsr

    ho_dd = abs(heldout_dd_result.get("max_drawdown", 0.0))
    dd_pass = ho_dd <= threshold_max_dd

    real = heldout_scorecard.drop(index="UNKNOWN", errors="ignore")
    eligible = real[real["count"] >= min_regime_n]
    eligible_total = int(len(eligible))
    positive = int((eligible["mean"] > 0).sum())
    required_positive = eligible_total - 1 if eligible_total >= 3 else eligible_total
    regime_pass = eligible_total >= 2 and positive >= required_positive

    verdict = "PASS" if (dsr_pass and dd_pass and regime_pass) else "FAIL"

    return {
        "verdict": verdict,
        "training_dsr": float(training_dsr),
        "required_heldout_dsr": float(required_dsr),
        "observed_heldout_dsr": float(ho_dsr),
        "dsr_pass": bool(dsr_pass),
        "threshold_max_dd": float(threshold_max_dd),
        "observed_max_dd": float(ho_dd),
        "dd_pass": bool(dd_pass),
        "regime_positive": positive,
        "regime_eligible": eligible_total,
        "regime_pass": bool(regime_pass),
        "regime_required_positive": required_positive,
    }


# =============================================================================
# Serialization helpers
# =============================================================================


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=str)


def scorecard_to_dict(scorecard: pd.DataFrame) -> dict:
    return {
        regime: {"ic_mean": float(row["mean"]), "n_rebalances": int(row["count"])}
        for regime, row in scorecard.iterrows()
    }
