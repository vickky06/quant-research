"""Persistent SQLite run log — every backtest execution is auditable.

Kept intentionally small: a `runs` table with one row per run, and a
`run_regimes` table with one row per (run, regime). Not intended to hold
every rebalance-level tick; that's a v0.2+ concern (Attribution).

Location: ./data/run_log.sqlite (alongside prices.duckdb, gitignored).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


DEFAULT_LOG_PATH = Path(__file__).parent / "data" / "run_log.sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    mode TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT 'momentum',
    universe_size INTEGER,
    params_json TEXT,
    verdict TEXT,
    dsr REAL,
    sharpe_annualized REAL,
    cumulative_return REAL,
    ic_mean REAL,
    ic_positive_regimes INTEGER,
    ic_total_regimes INTEGER,
    n_rebalances INTEGER,
    n_monthly_observations INTEGER,
    avg_turnover REAL,
    max_drawdown REAL,
    max_dd_duration_months INTEGER,
    max_dd_recovery_months INTEGER,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS run_regimes (
    run_id INTEGER NOT NULL,
    regime TEXT NOT NULL,
    ic_mean REAL,
    n_rebalances INTEGER,
    PRIMARY KEY (run_id, regime),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_runs_verdict ON runs(verdict);
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent);
"""


def _init(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.executescript(SCHEMA)
    return con


def log_run(
    *,
    mode: str,
    agent: str,
    universe_size: int,
    params: dict,
    verdict: str,
    dsr: float,
    sharpe_annualized: float,
    cumulative_return: float,
    ic_mean: float,
    ic_positive_regimes: int,
    ic_total_regimes: int,
    n_rebalances: int,
    n_monthly_observations: int,
    avg_turnover: float,
    scorecard: dict,
    max_drawdown: float = 0.0,
    max_dd_duration_months: int | None = None,
    max_dd_recovery_months: int | None = None,
    notes: str = "",
    db_path: Path = DEFAULT_LOG_PATH,
) -> int:
    """Insert one run + its per-regime rows. Returns the new run id."""
    con = _init(db_path)
    try:
        cur = con.execute(
            """
            INSERT INTO runs (
                timestamp, mode, agent, universe_size, params_json, verdict,
                dsr, sharpe_annualized, cumulative_return, ic_mean,
                ic_positive_regimes, ic_total_regimes, n_rebalances,
                n_monthly_observations, avg_turnover,
                max_drawdown, max_dd_duration_months, max_dd_recovery_months,
                notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                mode,
                agent,
                universe_size,
                json.dumps(params),
                verdict,
                float(dsr),
                float(sharpe_annualized),
                float(cumulative_return),
                float(ic_mean),
                int(ic_positive_regimes),
                int(ic_total_regimes),
                int(n_rebalances),
                int(n_monthly_observations),
                float(avg_turnover),
                float(max_drawdown),
                max_dd_duration_months,
                max_dd_recovery_months,
                notes,
            ),
        )
        run_id = cur.lastrowid
        for regime, vals in scorecard.items():
            con.execute(
                "INSERT INTO run_regimes (run_id, regime, ic_mean, n_rebalances) VALUES (?, ?, ?, ?)",
                (run_id, regime, float(vals["ic_mean"]), int(vals["n_rebalances"])),
            )
        con.commit()
        return int(run_id)
    finally:
        con.close()


def read_runs(db_path: Path = DEFAULT_LOG_PATH) -> pd.DataFrame:
    """Return all runs as a DataFrame, newest first."""
    if not db_path.exists():
        return pd.DataFrame()
    con = sqlite3.connect(str(db_path))
    try:
        return pd.read_sql_query(
            "SELECT * FROM runs ORDER BY timestamp DESC", con
        )
    finally:
        con.close()


def read_run_regimes(run_id: int, db_path: Path = DEFAULT_LOG_PATH) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame()
    con = sqlite3.connect(str(db_path))
    try:
        return pd.read_sql_query(
            "SELECT * FROM run_regimes WHERE run_id = ? ORDER BY regime",
            con,
            params=(run_id,),
        )
    finally:
        con.close()
