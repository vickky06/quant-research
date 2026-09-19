"""Pipeline for v0.3 R2K prototype (S&P SmallCap 600 / Russell 2000 proxy).

Thesis: S&P 500 large-caps have a ~0.35 Sharpe ceiling for pure-price L/S
due to tech-sector dominance (ADR-0006). Small-caps have less tech
concentration, more idiosyncratic price behavior, and momentum is documented
to work in small-caps post-2020 (literature-supported). This prototype tests
both momentum (12-1) and mean_reversion (20d) on the S&P SmallCap 600 as a
representative small-cap universe.

Adapted from proto-v0.2-us. Key changes:
  - INDEX_TICKER = "^RUT" (Russell 2000 as regime proxy)
  - ROUNDTRIP_COST_BPS = 10 (small-cap spreads wider than large-cap)
  - LIQUIDITY_THRESHOLD = $1M daily turnover floor (small-cap appropriate)
  - PRICE_FLOOR = $1.00 (no penny stocks; small-caps trade lower than large)
  - DATA_START / TRAINING_START / TRAINING_END updated
  - Universe: S&P SmallCap 600 via Wikipedia
  - AGENTS: both momentum AND mean_reversion (vs. v0.2-us which retired momentum)
  - skip_regimes parameter added to run_meta_ensemble_backtest (not activated
    by default; small-caps may not have the same LOW_VOL_UP_TREND failure mode
    as large-caps — evaluate unconditionally first)
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

# 2-year warmup before TRAINING_START for momentum lookback (12m) + regime (200d MA + 5yr vol)
DATA_START = pd.Timestamp("2015-01-01")

LIQUIDITY_THRESHOLD = 1_000_000   # $1M avg daily turnover (small-cap floor)
LISTING_YEARS = 3
PRICE_FLOOR = 1.0                  # $1 minimum price (excludes penny stocks)

MOMENTUM_LOOKBACK_MONTHS = 12
MOMENTUM_SKIP_MONTHS = 1
DECILES = 10

# Regime detection
VOL_WINDOW_DAYS = 60
VOL_PERCENTILE_WINDOW_DAYS = 252 * 5  # 5-year rolling
MA_WINDOW = 200
TREND_LOOKBACK_DAYS = 20

# Small-cap cost model: no brokerage (Alpaca), but wider spreads than large-cap.
# 10 bps roundtrip is conservative for S&P 600 liquid names.
ROUNDTRIP_COST_BPS = 10

INDEX_TICKER = "^RUT"  # Russell 2000 as regime proxy for small-cap universe


# =============================================================================
# Universe — S&P SmallCap 600
# =============================================================================

# Hardcoded fallback: 50 S&P 600 liquid small-cap names with consistent Yahoo data.
SP600_FALLBACK = [
    "SAIA", "UFPI", "TREX", "LNTH", "BECN", "AAON", "MGEE", "HLIO",
    "CASS", "NBTB", "CVBF", "WSFS", "PEBO", "FULT", "IBOC",
    "HLNE", "PRGS", "QLYS", "PLUS", "EVTC", "CORT", "AEIS",
    "APOG", "AWR", "CBSH", "CHCO", "CIZN", "CLFD", "CNS",
    "CVCO", "DSGX", "EGBN", "ENSG", "EPRT", "EXPO", "FIZZ",
    "FRPH", "GKOS", "GRBK", "HCKT", "HIFS", "HWKN", "IOSP",
    "JACK", "JBSS", "JOUT", "KFRC", "LANC", "MGRC", "MIDD",
]

SP600_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"


def get_universe(fast: bool = False) -> list[str]:
    """Return S&P SmallCap 600 tickers (Yahoo format)."""
    if fast:
        return list(SP600_FALLBACK)

    try:
        import io
        import requests

        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(SP600_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text))
        for tbl in tables:
            cols = [str(c).lower() for c in tbl.columns]
            ticker_col = next(
                (tbl.columns[i] for i, c in enumerate(cols) if "ticker" in c or "symbol" in c),
                None,
            )
            if ticker_col is not None and len(tbl) >= 400:
                symbols = (
                    tbl[ticker_col].astype(str).str.strip()
                    .str.replace(".", "-", regex=False)
                    .tolist()
                )
                # Filter out non-ticker rows (headers, footnotes)
                symbols = [s for s in symbols if s and len(s) <= 6 and s.isalpha() or "-" in s]
                print(f"[universe] fetched {len(symbols)} symbols from S&P 600 wiki")
                return symbols
    except Exception as e:
        print(f"[universe] S&P 600 fetch failed ({e!r}); using fallback list")

    return list(SP600_FALLBACK)


def to_yahoo(symbol: str) -> str:
    """US tickers pass through unchanged (already in Yahoo format)."""
    return symbol


# =============================================================================
# Data ingestion (yfinance → DuckDB)
# =============================================================================


def _init_db(db_path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
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
    """Fetch Russell 2000 index for regime detection. Date-range-aware cache check."""
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
    """Filter to symbols meeting listing, liquidity, and price rules.

    Requires history covering at least momentum lookback + buffer before
    TRAINING_START. With DATA_START = 2015-01-01 and TRAINING_START = 2017-01-01,
    we have 2 years of warmup — enough for 12-1 momentum lookback (13 months).
    """
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
    price_ok = close.loc[rebalance_date] > PRICE_FLOOR
    if rebalance_date in liquidity_60d.index:
        liq_ok = liquidity_60d.loc[rebalance_date] > LIQUIDITY_THRESHOLD
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
    """Short-term mean reversion (Jegadeesh 1990).

    Ranks by the inverse of the 20-day return: recent losers score high,
    recent winners score low. Cross-sectionally ranked per date.
    """
    past_return = close_wide.pct_change(MEAN_REVERSION_WINDOW_DAYS)
    inverted = -past_return
    return inverted.rank(axis=1, pct=True)


# Agent registry.
# Both momentum and mean_reversion are evaluated on small-caps.
# Momentum was retired on S&P 500 large-caps (ADR-0006) due to tech-sector
# dominance, but small-caps have less tech concentration — hypothesis is that
# momentum works here (literature: Fama-French small-cap momentum premium).
AGENTS: dict[str, callable] = {
    "momentum": compute_momentum,
    "mean_reversion": compute_mean_reversion,
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
    """Probabilistic Sharpe Ratio (Bailey-López de Prado 2012/2014)."""
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
# Gate G1
# =============================================================================

MIN_REGIME_REBALANCES = 10


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
# Meta-Learner — IC-weighted signal combining
# =============================================================================

META_IC_WINDOW_MONTHS = 24
META_MIN_WEIGHT = 0.05
META_MAX_WEIGHT_FLOOR = 0.30
META_SHRINKAGE = 0.5
META_RESET_EVERY_MONTHS = 12


def dynamic_max_weight(n_agents: int) -> float:
    """Contract v1.2: cap = max(0.30, 1.2 / n_agents)."""
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
) -> MetaEnsembleResult:
    """Backtest the ensemble with a dynamic IC-weighted Meta-Learner.

    skip_regimes: when the regime at a rebalance date is in this set, record
    0.0 return and skip portfolio construction. Not activated by default for
    R2K — evaluate unconditionally first to characterize regime behavior.
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

    prev_long: set[str] = set()
    prev_short: set[str] = set()

    for i, rb in enumerate(rebalance_dates[:-1]):
        next_rb = rebalance_dates[i + 1]

        current_regime = regime_df.loc[rb, "regime"] if rb in regime_df.index else "UNKNOWN"
        regime_snapshot[rb] = current_regime

        # Regime gate: record 0.0 and skip portfolio construction for gated months
        if skip_regimes and current_regime in skip_regimes:
            monthly_returns.append((rb, 0.0))
            turnovers.append((rb, 0.0))
            weights_records.append({"date": rb, **{a: 1.0 / len(agent_names) for a in agent_names}})
            ic_records.append({"date": rb, **{a: np.nan for a in agent_names}})
            prev_long = set()
            prev_short = set()
            continue

        elig = per_rebalance_universe(close_wide, liquidity_60d, rb)
        if len(elig) < min_eligible:
            continue

        weights = _compute_meta_weights_for_step(
            agent_names, ic_history, i, ic_window_months,
            min_weight, max_weight, shrinkage, reset_every_months,
        )
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


def evaluate_gate_g1(
    dsr_result: dict, scorecard: pd.DataFrame, threshold_dsr: float = 0.5,
    min_regime_n: int = MIN_REGIME_REBALANCES,
) -> dict:
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
    """Gate G2: ensemble validation on training set (Contract §5 v1.3)."""
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
