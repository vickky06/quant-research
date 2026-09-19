"""Pipeline for v0.2 US-market prototype (S&P 500).

Adapted from v0.1 India prototype: same signal + Meta-Learner + regime
architecture, but US equities, S&P 500 universe, ^GSPC index proxy,
Alpaca commission-free cost model.

Pure-ish functions. No CLI, no orchestration — those live in run.py.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy import stats


# =============================================================================
# Contract-bound constants
# =============================================================================

TRAINING_START = pd.Timestamp("2015-01-01")
TRAINING_END = pd.Timestamp("2023-12-31")
HELD_OUT_START = pd.Timestamp("2024-01-01")

# Data must extend earlier than TRAINING_START for lookback needs (12m momentum + 200d MA)
DATA_START = pd.Timestamp("2013-01-01")

# US-market thresholds (previously named *_INR for India — variable names retained
# to minimize diff surface; semantics are now USD).
LIQUIDITY_THRESHOLD_INR = 10_000_000  # $10M avg daily turnover (S&P 500 large-cap floor)
LISTING_YEARS = 3
PRICE_FLOOR_INR = 5.0  # $5 minimum price (excludes penny)

MOMENTUM_LOOKBACK_MONTHS = 12
MOMENTUM_SKIP_MONTHS = 1
DECILES = 10

# Regime detection
VOL_WINDOW_DAYS = 60
VOL_PERCENTILE_WINDOW_DAYS = 252 * 5  # 5-year rolling
MA_WINDOW = 200
TREND_LOOKBACK_DAYS = 20

# Cost model: Alpaca is commission-free for US equities, so no brokerage.
# Slippage assumption 5 bps roundtrip (conservative for large-caps with SIP quotes).
ROUNDTRIP_COST_BPS = 5

INDEX_TICKER = "^GSPC"  # S&P 500 index as regime proxy


# =============================================================================
# Universe
# =============================================================================

# Hardcoded fallback: 30 S&P 500 mega-caps that reliably have Yahoo data.
FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "XOM", "MA", "PG", "JNJ", "HD",
    "COST", "AVGO", "MRK", "ABBV", "PEP", "KO", "WMT", "CVX",
    "ADBE", "CRM", "MCD", "TMO", "ORCL", "NKE",
]


SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# Hardcoded GICS sectors for the 30-stock fallback universe.
FALLBACK_SECTOR_MAP: dict[str, str] = {
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "GOOGL": "Communication Services", "AMZN": "Consumer Discretionary",
    "NVDA": "Information Technology", "META": "Communication Services",
    "TSLA": "Consumer Discretionary", "BRK-B": "Financials",
    "JPM": "Financials", "V": "Financials",
    "UNH": "Health Care", "XOM": "Energy",
    "MA": "Financials", "PG": "Consumer Staples",
    "JNJ": "Health Care", "HD": "Consumer Discretionary",
    "COST": "Consumer Staples", "AVGO": "Information Technology",
    "MRK": "Health Care", "ABBV": "Health Care",
    "PEP": "Consumer Staples", "KO": "Consumer Staples",
    "WMT": "Consumer Staples", "CVX": "Energy",
    "ADBE": "Information Technology", "CRM": "Information Technology",
    "MCD": "Consumer Discretionary", "TMO": "Health Care",
    "ORCL": "Information Technology", "NKE": "Consumer Discretionary",
}


def get_universe(fast: bool = False) -> list[str]:
    """Return S&P 500 tickers (Yahoo format — dots replaced with hyphens)."""
    if fast:
        return FALLBACK_UNIVERSE

    try:
        import io
        import requests

        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(SP500_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0]  # first table is the constituents
        if "Symbol" in df.columns and len(df) >= 400:
            symbols = (
                df["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False)
                .tolist()
            )
            print(f"[universe] fetched {len(symbols)} symbols from S&P 500 wiki")
            return symbols
    except Exception as e:
        print(f"[universe] S&P 500 fetch failed ({e!r}); using fallback list")

    return FALLBACK_UNIVERSE


def get_sector_map(fast: bool = False) -> dict[str, str]:
    """Return {ticker: GICS_sector_string} for all S&P 500 constituents.

    Fast mode returns the hardcoded FALLBACK_SECTOR_MAP for the 30-stock subset.
    Full mode extends the Wikipedia S&P 500 parse (same request as get_universe)
    to also capture the 'GICS Sector' column.
    Unmapped tickers default to 'Unknown' — treated as their own sector bucket.
    """
    if fast:
        return FALLBACK_SECTOR_MAP.copy()

    try:
        import io
        import requests

        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(SP500_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        df = tables[0]
        if "Symbol" in df.columns and "GICS Sector" in df.columns and len(df) >= 400:
            sector_map = {
                row["Symbol"].strip().replace(".", "-"): row["GICS Sector"]
                for _, row in df.iterrows()
            }
            print(f"[sectors] fetched {len(sector_map)} GICS sector assignments")
            return sector_map
    except Exception as e:
        print(f"[sectors] sector fetch failed ({e!r}); all symbols map to 'Unknown'")

    return {}


def to_yahoo(symbol: str) -> str:
    """US tickers pass through unchanged (already in Yahoo format)."""
    return symbol


# =============================================================================
# Data ingestion (yfinance → DuckDB)
# =============================================================================


def _init_db(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open DuckDB. Writer creates tables; reader opens read_only for concurrency."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        # Reader must not create tables — assumes writer has already initialized.
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
        time.sleep(0.5)  # gentle on yahoo

    con.close()


def download_index(db_path: Path, start: pd.Timestamp, end: pd.Timestamp) -> None:
    """Fetch S&P 500 index for regime detection. Date-range aware cache check."""
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
        if isinstance(close, pd.Series):  # multiindex quirk
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
    """Filter to symbols meeting listing, liquidity, and price rules.

    Contract requires 3-year listing before TRAINING_START. Our data window
    starts at DATA_START (2 years before TRAINING_START), so we cannot fully
    verify 3-year listing from data alone. We enforce the observable equivalent:
    "has data at least 13 months before TRAINING_START" — enough for the
    momentum lookback plus buffer. Documented in PROTOTYPE_NOTICE.md as a
    prototype-only relaxation.
    """
    close = prices_long.pivot(index="date", columns="symbol", values="adj_close")

    # Require history covering at least momentum lookback + buffer
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
# Signal — 12-1 momentum
# =============================================================================


def compute_momentum(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """12-1 momentum: return from t-13m to t-1m. Cross-sectionally rank-normalized."""
    # Approximate months as 21 trading days
    lookback = MOMENTUM_LOOKBACK_MONTHS * 21
    skip = MOMENTUM_SKIP_MONTHS * 21
    past = close_wide.shift(skip)
    older = close_wide.shift(lookback)
    raw_momentum = past / older - 1.0
    # Cross-sectional rank per date, in [0, 1]
    ranked = raw_momentum.rank(axis=1, pct=True)
    return ranked


LOW_VOL_WINDOW_DAYS = 60


def compute_low_vol(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Reference implementation of long-low-vol / short-high-vol.

    RETIRED — failed Gate G1 empirically on Nifty 500 2015-2023
    (see docs/adr/0002-low-vol-rejected-nifty500.md). Kept for reference
    only; excluded from the AGENTS registry.
    """
    log_returns = np.log(close_wide / close_wide.shift(1))
    realized_vol = log_returns.rolling(LOW_VOL_WINDOW_DAYS).std() * np.sqrt(252)
    inverted = -realized_vol
    ranked = inverted.rank(axis=1, pct=True)
    return ranked


MEAN_REVERSION_WINDOW_DAYS = 20  # ~1 month
MAX_LOTTERY_WINDOW_DAYS = 20


def compute_max_lottery(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """MAX/lottery anomaly: short stocks with extreme single-day gains in past month.

    Bali, Cakici, Whitelaw (2011) 'Maxing out: Stocks as lotteries and the
    cross-section of expected returns', JFE. Investors overpay for lottery-like
    payoffs (recent large single-day gain). MAX = maximum daily return in past N
    days; high MAX predicts underperformance. Signal is INVERTED (short high MAX).

    Different mechanism from mean_reversion (cumulative 20d return level vs max
    single-day spike) — expected to be anti-correlated in crisis months and
    partially uncorrelated in quiet months.
    """
    daily_returns = close_wide.pct_change()
    max_daily_return = daily_returns.rolling(MAX_LOTTERY_WINDOW_DAYS).max()
    inverted = -max_daily_return
    return inverted.rank(axis=1, pct=True)


def compute_mean_reversion(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Short-term mean reversion — Jegadeesh (1990) "Evidence of Predictable
    Behavior of Security Returns", JoF.

    Ranks by the *inverse* of the 20-day return: recent losers score high,
    recent winners score low. Cross-sectionally ranked per date.

    Hypothesis: 1-month returns exhibit negative auto-correlation. This is
    the direct counterpart to the skip-1-month gap in 12-1 momentum — the
    reason momentum skips the last month is *because* short-term reversion
    lives there. That makes this Agent a naturally anti-correlated pair
    to the momentum Agent, ideal for ensemble diversification.
    """
    past_return = close_wide.pct_change(MEAN_REVERSION_WINDOW_DAYS)
    inverted = -past_return
    ranked = inverted.rank(axis=1, pct=True)
    return ranked


def compute_sector_neutral_mean_reversion(
    close_wide: pd.DataFrame,
    sector_map: dict[str, str] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Sector-neutralized short-term mean reversion.

    Subtracts the GICS sector median 20-day return from each stock's 20-day
    return before ranking. This strips the sector-level direction and captures
    only idiosyncratic reversion — a stock that fell while its sector rose is
    a stronger mean-reversion long than a stock that fell with the whole sector.

    Motivation: Raw cross-sectional mean reversion develops systematic sector
    tilts in trending markets (US large-caps 2015-2023: tech dominates the top
    decile → raw mean_reversion shorts tech systematically → short leg bleeds).
    Sector-neutral ranking avoids this by comparing stocks only within sector.

    If sector_map is None or empty, degrades to raw mean_reversion.
    """
    past_return = close_wide.pct_change(MEAN_REVERSION_WINDOW_DAYS)

    if not sector_map:
        return (-past_return).rank(axis=1, pct=True)

    symbols = close_wide.columns.tolist()
    sym_to_sector = pd.Series(
        {s: sector_map.get(s, "Unknown") for s in symbols}, name="sector"
    )

    # For each sector group, subtract the group median 20d return per date
    idio_return = past_return.copy()
    for sector, group_syms in sym_to_sector.groupby(sym_to_sector).groups.items():
        group_syms = [s for s in group_syms if s in past_return.columns]
        if len(group_syms) < 2:
            continue
        sector_median = past_return[group_syms].median(axis=1)
        idio_return[group_syms] = past_return[group_syms].sub(sector_median, axis=0)

    return (-idio_return).rank(axis=1, pct=True)


DOWNSIDE_BETA_WINDOW_DAYS = 120
DOWNSIDE_BETA_MIN_DOWN_DAYS = 20


def compute_low_downside_beta(
    close_wide: pd.DataFrame,
    index_close: pd.Series | None = None,
    **kwargs,
) -> pd.DataFrame:
    """Low-downside-beta: beta measured only on index-DOWN days.

    Frazzini-Pedersen "Betting Against Beta" (2014). Low-beta stocks tend
    to outperform on a risk-adjusted basis; low *downside* beta specifically
    targets stocks that resist market drawdowns. Signal is INVERSE beta
    ranked cross-sectionally — lower downside beta gets higher signal.

    Computed at each month-end using trailing 120 trading days, filtered
    to days where index return < 0. Requires at least 20 down-days in the
    window to yield a value; otherwise NaN. Forward-filled to daily
    granularity for compatibility with downstream aggregation.
    """
    if index_close is None:
        raise ValueError("compute_low_downside_beta requires index_close")

    stock_returns = close_wide.pct_change()
    index_returns = index_close.pct_change()
    common_dates = stock_returns.index.intersection(index_returns.index)
    stock_returns = stock_returns.loc[common_dates]
    index_returns = index_returns.loc[common_dates]

    window = DOWNSIDE_BETA_WINDOW_DAYS
    result = pd.DataFrame(index=close_wide.index, columns=close_wide.columns, dtype=float)
    monthly_dates = month_end_dates(close_wide.index)

    for rb in monthly_dates:
        if rb not in common_dates:
            continue
        pos = common_dates.get_loc(rb)
        if pos < window:
            continue
        window_dates = common_dates[pos - window : pos]
        s_window = stock_returns.loc[window_dates]
        i_window = index_returns.loc[window_dates]
        down_mask = i_window < 0
        if int(down_mask.sum()) < DOWNSIDE_BETA_MIN_DOWN_DAYS:
            continue
        s_down = s_window[down_mask]
        i_down = i_window[down_mask]
        i_var = float(i_down.var())
        if not np.isfinite(i_var) or i_var == 0:
            continue
        s_demean = s_down.sub(s_down.mean(), axis=1)
        i_demean = i_down - i_down.mean()
        cov_by_stock = s_demean.multiply(i_demean, axis=0).mean()
        beta_by_stock = cov_by_stock / i_var
        # Invert (lower beta = higher signal) then cross-sectional rank
        result.loc[rb] = (-beta_by_stock).rank(pct=True)

    # Forward-fill monthly-computed signal to daily granularity
    return result.ffill()


QUALITY_WINDOW_DAYS = 252  # 12 months trailing


def compute_return_smoothness(close_wide: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Return smoothness — a quality proxy from prices alone.

    Signal is the rolling 12-month Sharpe ratio of each stock's own daily
    log returns (annualized). Cross-sectionally ranked so the smoothest
    compounders (high individual Sharpe) rank highest.

    Rationale: high individual Sharpe requires positive mean *and* low vol
    — the combination is not simply "low vol" (large-cap tilt) or simply
    "momentum" (high mean, any vol). It selects for *stable compounders*,
    which can be either large-cap grinders or small-cap steady growers.
    Should avoid the size-premium short-leg failure mode of ADR-0004.

    Long-term evidence: Novy-Marx "Quality Investing" style — quality
    portfolios show defensive characteristics in DOWN_TREND regimes.
    """
    log_returns = np.log(close_wide / close_wide.shift(1))
    rolling_mean = log_returns.rolling(QUALITY_WINDOW_DAYS).mean()
    rolling_std = log_returns.rolling(QUALITY_WINDOW_DAYS).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        rolling_sharpe = (rolling_mean / rolling_std) * np.sqrt(252)
    rolling_sharpe = rolling_sharpe.replace([np.inf, -np.inf], np.nan)
    return rolling_sharpe.rank(axis=1, pct=True)


# Agent registry — each entry is a pure signal-producing function.
# US-market signal evaluation status (training window 2015-2023, S&P 500):
# - compute_momentum:          RETIRED — Sharpe -0.20, DSR 0.270, FAILS G1
# - compute_return_smoothness: RETIRED — Sharpe -0.35, DSR 0.146, FAILS G1
# - compute_low_vol:           RETIRED — Sharpe -0.60, DSR 0.035, FAILS G1
# - compute_max_lottery:       RETIRED — Sharpe -0.65, DSR 0.025, FAILS G1
# All four fail for the same structural reason: US large-cap tech dominance 2015-2023
# punishes any signal that systematically shorts volatile or high-momentum names.
# compute_sector_neutral_mean_reversion: under evaluation — strips GICS sector median
# return to avoid the systematic short-tech tilt that raw cross-sectional ranking creates.
AGENTS: dict[str, callable] = {
    "mean_reversion": compute_mean_reversion,
    "sector_neutral_mr": compute_sector_neutral_mean_reversion,
}


def compute_ensemble(signals_by_agent: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Equal-weight ensemble of per-Agent rank signals.

    Trivial Meta-Learner for v0.2. Later versions replace this with an
    IC-weighted or regime-conditional weighting scheme.

    All input frames must share the same (date × symbol) grid. Result is
    the per-cell mean across Agents. Ranks are re-normalized at the end so
    the ensemble is again in [0, 1] and directly comparable to a single
    Agent's signal.
    """
    if not signals_by_agent:
        raise ValueError("no signals provided")
    frames = list(signals_by_agent.values())
    # Simple average across frames — pandas broadcasts on shared index/columns
    total = frames[0].copy()
    for f in frames[1:]:
        total = total.add(f, fill_value=np.nan)
    avg = total / len(frames)
    # Re-rank cross-sectionally so ensemble output is in [0, 1]
    return avg.rank(axis=1, pct=True)


# =============================================================================
# Regime — 2×2 Vol × Trend
# =============================================================================


def compute_regime(index_close: pd.Series) -> pd.DataFrame:
    """Return DataFrame with columns [vol_regime, trend_regime, regime]."""
    returns = index_close.pct_change()
    vol_60d = returns.rolling(VOL_WINDOW_DAYS).std() * np.sqrt(252)

    # Expanding rank until enough history, then rolling 5-year percentile
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
    # Mark early rows (before regime is computable) as UNKNOWN
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
    monthly_returns: pd.Series  # net-of-cost long-short monthly returns
    signal_at_rebalance: dict  # {date: {symbol: rank}}
    forward_returns: dict  # {date: {symbol: 1-month forward return}}
    regime_at_rebalance: pd.Series  # {date: regime}
    turnover: pd.Series  # per rebalance turnover fraction


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

    # Minimum universe for a valid rebalance: 20 stocks, or 50% of the
    # potentially-eligible pool, whichever is smaller. Prototype-appropriate.
    min_eligible = min(20, max(10, close_wide.shape[1] // 2))

    for i, rb in enumerate(rebalance_dates[:-1]):
        next_rb = rebalance_dates[i + 1]
        elig = per_rebalance_universe(close_wide, liquidity_60d, rb)
        if len(elig) < min_eligible:
            continue

        momo_today = momentum.loc[rb, elig].dropna()
        if len(momo_today) < min_eligible:
            continue

        # Recompute rank inside eligible universe only (contract-clean)
        momo_ranked = momo_today.rank(pct=True)
        n = len(momo_ranked)
        top_cut = 1.0 - 1.0 / DECILES
        bot_cut = 1.0 / DECILES
        long_names = momo_ranked[momo_ranked >= top_cut].index.tolist()
        short_names = momo_ranked[momo_ranked <= bot_cut].index.tolist()

        # Forward returns from rb to next_rb using adj_close
        fwd = (close_wide.loc[next_rb, elig] / close_wide.loc[rb, elig] - 1.0).dropna()

        long_ret = fwd.reindex(long_names).mean()
        short_ret = fwd.reindex(short_names).mean()
        gross_ls = long_ret - short_ret

        # Turnover: fraction of new names in long+short vs previous
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


def compute_ic_per_rebalance(
    signals: dict, forwards: dict
) -> pd.Series:
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

    With N=1 trial, PSR ≈ DSR. Returns dict with sharpe, psr, and inputs.
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
    excess_kurt = float(stats.kurtosis(r, fisher=True, bias=False))  # excess (γ4 - 3)

    # PSR formula uses (γ_4 - 1)/4 where γ_4 is raw kurtosis (not excess).
    # Convert: raw_kurt = excess_kurt + 3, so (γ_4 - 1)/4 = (excess_kurt + 2)/4
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
# Gate G1
# =============================================================================


MIN_REGIME_REBALANCES = 10  # Contract v1.1 / ADR-0003


def compute_max_drawdown(monthly_returns: pd.Series) -> dict:
    """Max drawdown of the equity curve implied by monthly_returns.

    Returns a dict with:
      max_drawdown       peak-to-trough proportional loss (negative number)
      peak_date          date of the pre-drawdown high
      trough_date        date of the drawdown low
      recovery_date      date when equity first recovered to prior peak (or None if never)
      duration_months    peak to trough
      recovery_months    trough to recovery (None if never)
    """
    r = monthly_returns.dropna()
    if len(r) == 0:
        return {"max_drawdown": 0.0, "peak_date": None, "trough_date": None,
                "recovery_date": None, "duration_months": None, "recovery_months": None}
    equity = (1 + r).cumprod()
    running_max = equity.cummax()
    dd = equity / running_max - 1.0
    trough_date = dd.idxmin()
    max_dd = float(dd.loc[trough_date])
    # Peak is the last date before trough with equity == running_max
    peak_slice = equity.loc[:trough_date]
    peak_date = peak_slice[peak_slice == running_max.loc[trough_date]].index[0]
    # Recovery: first date after trough where equity >= running_max at peak
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
META_MAX_WEIGHT_FLOOR = 0.30  # per Contract v1.2 §6.6 — see ADR-0005
META_SHRINKAGE = 0.5  # 0 = pure IC weights, 1 = pure equal-weight prior
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
    """Return weights for the next Rebalance given per-Agent IC history so far.

    Warmup: while step_index < window or reset boundary → equal-weight.
    Otherwise: rolling-window mean IC per Agent → positive-only proportional
    weights → shrink toward equal-weight prior → clip to [min_w, max_w] →
    renormalize.
    """
    n = len(agent_names)
    equal = 1.0 / n
    equal_weights = {a: equal for a in agent_names}

    # Warmup or forced reset
    if step_index < window or (reset_every > 0 and step_index % reset_every == 0):
        return equal_weights

    # Rolling window mean IC per agent
    mean_ic = {}
    for a in agent_names:
        recent = ic_history_by_agent.get(a, [])[-window:]
        if not recent:
            return equal_weights
        mean_ic[a] = float(np.mean(recent))

    # Positive-only proportional weights
    pos = {a: max(0.0, ic) for a, ic in mean_ic.items()}
    total_pos = sum(pos.values())
    if total_pos <= 0:
        raw = equal_weights.copy()
    else:
        raw = {a: pos[a] / total_pos for a in agent_names}

    # Shrink toward equal-weight prior
    shrunk = {a: shrinkage * equal + (1 - shrinkage) * raw[a] for a in agent_names}

    # Clip to [min_w, max_w] and renormalize
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
    weights_at_rebalance: pd.DataFrame  # rows = rebalance dates, cols = agents
    per_agent_ic_at_rebalance: pd.DataFrame  # same shape as weights


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
    max_weight: float | None = None,  # None → dynamic per ADR-0005
    shrinkage: float = META_SHRINKAGE,
    reset_every_months: int = META_RESET_EVERY_MONTHS,
    heldout_mode: bool = False,
) -> MetaEnsembleResult:
    """Backtest the ensemble with a dynamic IC-weighted Meta-Learner.

    Meta-Learner mechanics per contract §6:
      - Rolling IC per Agent computed strictly out-of-sample
      - Weights shrunk toward equal-weight prior
      - Hard floor min_weight, cap max_weight, renormalized
      - Forced equal-weight reset every reset_every_months rebalances
      - Warmup with equal weights until ic_window_months rebalances complete
    """
    if not heldout_mode:
        assert training_end < HELD_OUT_START, "training/held-out overlap"

    agent_names = list(signals_by_agent.keys())
    ic_history: dict[str, list[float]] = {a: [] for a in agent_names}

    # Resolve max_weight per Contract v1.2 (ADR-0005): scales with n_agents.
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

    prev_long: set[str] = set()
    prev_short: set[str] = set()

    for i, rb in enumerate(rebalance_dates[:-1]):
        next_rb = rebalance_dates[i + 1]
        elig = per_rebalance_universe(close_wide, liquidity_60d, rb)
        if len(elig) < min_eligible:
            continue

        # Weights for THIS rebalance use IC history strictly before it
        weights = _compute_meta_weights_for_step(
            agent_names, ic_history, i, ic_window_months,
            min_weight, max_weight, shrinkage, reset_every_months,
        )
        weights_records.append({"date": rb, **weights})

        # Weighted ensemble score across eligible instruments
        weighted_score = pd.Series(0.0, index=elig, dtype=float)
        weight_mass = pd.Series(0.0, index=elig, dtype=float)
        for a, sig_df in signals_by_agent.items():
            agent_sig = sig_df.loc[rb, elig].dropna() if rb in sig_df.index else pd.Series(dtype=float)
            if agent_sig.empty:
                continue
            weighted_score.loc[agent_sig.index] += agent_sig * weights[a]
            weight_mass.loc[agent_sig.index] += weights[a]
        # Normalize by actual mass in case some agents were NaN for some instruments
        with np.errstate(divide="ignore", invalid="ignore"):
            score = (weighted_score / weight_mass).replace([np.inf, -np.inf], np.nan).dropna()
        if len(score) < min_eligible:
            continue
        ensemble_rank = score.rank(pct=True)

        # Decile portfolios
        top_cut = 1.0 - 1.0 / DECILES
        bot_cut = 1.0 / DECILES
        long_names = ensemble_rank[ensemble_rank >= top_cut].index.tolist()
        short_names = ensemble_rank[ensemble_rank <= bot_cut].index.tolist()

        # Forward returns
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
        regime_snapshot[rb] = (
            regime_df.loc[rb, "regime"] if rb in regime_df.index else "UNKNOWN"
        )
        turnovers.append((rb, turnover_fraction))

        # Record per-agent IC for THIS rebalance (now that forward return is known)
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

    weights_df = pd.DataFrame(weights_records).set_index("date")
    ic_df = pd.DataFrame(ic_records).set_index("date")

    return MetaEnsembleResult(
        monthly_returns=mr,
        signal_at_rebalance=signals_snapshot,
        forward_returns=fwd_snapshot,
        regime_at_rebalance=reg_ser,
        turnover=tv,
        weights_at_rebalance=weights_df,
        per_agent_ic_at_rebalance=ic_df,
    )


# =============================================================================
# Walk-forward validation
# =============================================================================


def compute_walkforward_folds(
    monthly_returns: pd.Series,
    fold_years: int = 1,
    min_months_per_fold: int = 6,
) -> pd.DataFrame:
    """Slice a full backtest into per-year (or per-N-year) folds.

    Since our Meta-Learner is online (weights use only past IC), the full
    backtest IS a walk-forward — each rebalance decision was already
    out-of-sample. Partitioning the output by year gives us the fold
    distribution needed to check *stability* across time.
    """
    if monthly_returns.empty:
        return pd.DataFrame()
    df = monthly_returns.to_frame("ret")
    df["fold"] = (df.index.year // fold_years) * fold_years  # aligned bucketing

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
    """Bailey-López de Prado deflated Sharpe corrected for N independent trials.

    Applies when we've tested N strategies and want an overfit-honest
    verdict on the winning one. Uses the *cross-fold* variance of Sharpe
    as an estimator of Sharpe's dispersion under the null.

    Formula (Bailey-López de Prado 2014, "Deflated Sharpe Ratio"):

        SR_0 = sqrt(V[SR]) * ((1 - γ) Φ^{-1}(1 - 1/N) + γ Φ^{-1}(1 - 1/(N·e)))

    where γ is the Euler-Mascheroni constant. SR_0 is the expected maximum
    Sharpe under the null hypothesis of no skill, given N trials. The
    aggregate DSR then asks: does our observed mean SR beat SR_0?
    """
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

    # PSR-style probability that our observed SR beats the null max
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
# Purged K-Fold Cross-Validation (López de Prado 2018)
# =============================================================================


def purged_kfold_splits(
    rebalance_dates: list[pd.Timestamp],
    n_splits: int = 5,
    purge_months: int = 13,
    embargo_months: int = 1,
) -> list[tuple[list[pd.Timestamp], list[pd.Timestamp]]]:
    """Purged K-Fold split for time-series backtests.

    Standard k-fold leaks in time-series because samples adjacent to a
    test fold often share information (lookbacks like 12-month momentum
    span multiple rebalances). We remove observations within `purge_months`
    of any test-fold boundary from the training set, plus `embargo_months`
    of post-test observations.

    Args:
        rebalance_dates: sequential Rebalance timestamps (monthly).
        n_splits: number of folds (default 5).
        purge_months: how many months of pre-test observations to drop
            from train (should cover signal lookback; momentum uses 13m).
        embargo_months: post-test months to also drop from train
            (accounts for forward-return leakage).

    Returns:
        List of (train_dates, test_dates) tuples, one per fold.
    """
    n = len(rebalance_dates)
    if n < n_splits * 2:
        raise ValueError(f"need at least {n_splits * 2} rebalances, got {n}")
    fold_size = n // n_splits
    splits = []
    for k in range(n_splits):
        test_start = k * fold_size
        test_end = (k + 1) * fold_size if k < n_splits - 1 else n
        test = rebalance_dates[test_start:test_end]

        test_start_date = test[0]
        test_end_date = test[-1]
        train = []
        for d in rebalance_dates:
            if d in test:
                continue
            # Purge: drop if within purge_months of test start
            months_from_test_start = (
                (test_start_date.year - d.year) * 12
                + (test_start_date.month - d.month)
            )
            if 0 < months_from_test_start <= purge_months:
                continue
            # Embargo: drop if in the embargo window after test
            months_from_test_end = (
                (d.year - test_end_date.year) * 12
                + (d.month - test_end_date.month)
            )
            if 0 < months_from_test_end <= embargo_months:
                continue
            train.append(d)
        splits.append((train, test))
    return splits


# =============================================================================
# Gate G3 (Held-out) evaluation
# =============================================================================


def evaluate_gate_g3(
    training_dsr: float,
    heldout_dsr_result: dict,
    heldout_dd_result: dict,
    heldout_scorecard: pd.DataFrame,
    training_dsr_threshold_ratio: float = 0.6,
    threshold_max_dd: float = 0.25,
    min_regime_n: int = MIN_REGIME_REBALANCES,
) -> dict:
    """Gate G3 per contract §5 (v1.2).

    - Realized DSR on held-out ≥ 60% of training DSR
    - Max DD ≤ 25% on held-out
    - Positive IC in ≥ (eligible_regimes - 1) of eligible regimes,
      where eligible regimes have n ≥ min_regime_n

    The 60% degradation floor is contract-native: it acknowledges that
    static-backtest DSR *over-estimates* real edge (multi-trial + selection).
    A realized held-out DSR of at least 60% of training suggests the edge
    survives out-of-sample; a lower value suggests overfit.
    """
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


def evaluate_gate_g2(
    dsr_result: dict, dd_result: dict,
    threshold_sharpe: float = 1.0,
    threshold_psr: float = 0.90,
    threshold_max_dd: float = 0.25,
) -> dict:
    """Gate G2: ensemble validation on training set.

    Contract §5 (corrected — prior implementation incorrectly used PSR ≥ 1.0,
    an impossible threshold):
      - Annualized Sharpe ≥ 1.0 net of costs
      - PSR ≥ 0.90 (90% confidence that true Sharpe > 0)
      - Max drawdown ≤ 25%
    All three must pass. PSR is provided separately for the G3 60%-degradation
    baseline (run_held_out.py reads 'observed_psr').
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
        "observed_dsr": psr,  # backward-compat alias used by run_held_out.py
        "observed_max_dd": max_dd,
        "sharpe_pass": bool(sharpe_pass),
        "psr_pass": bool(psr_pass),
        "dsr_pass": bool(sharpe_pass),  # alias kept for run.py display
        "dd_pass": bool(dd_pass),
    }


def evaluate_gate_g1(
    dsr_result: dict, scorecard: pd.DataFrame, threshold_dsr: float = 0.5,
    min_regime_n: int = MIN_REGIME_REBALANCES,
) -> dict:
    """Gate G1 per contract v1.1.

    Regime spread now requires n >= min_regime_n Rebalances per Regime.
    Regimes with fewer observations are excluded from evaluation
    (numerator and denominator both).
    """
    dsr = dsr_result.get("psr", 0.0)
    dsr_pass = dsr >= threshold_dsr

    # Filter to real regimes (drop UNKNOWN)
    real = scorecard.drop(index="UNKNOWN", errors="ignore")
    # Contract v1.1: exclude insufficient-sample regimes
    eligible = real[real["count"] >= min_regime_n]
    insufficient = real[real["count"] < min_regime_n]

    positive = int((eligible["mean"] > 0).sum())
    eligible_total = int(len(eligible))
    # Spirit of the original 3-of-4 rule: allow at most one Regime failure among
    # eligible Regimes; require at least 3 eligible Regimes total.
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
