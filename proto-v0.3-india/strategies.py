"""Strategy (algo) definitions — each strategy is a named weighting scheme
over the available signals. Selectable from the app sidebar.

Weights are normalised at runtime, so they only need to express relative
importance. Zero-weight signals are skipped entirely.
"""

from __future__ import annotations

STRATEGIES: dict[str, dict] = {
    "regime_ensemble": {
        "name": "🏆 Regime-Conditional Ensemble",
        "tag": "Validated",
        "color": "#2ecc71",
        "description": (
            "Signal weights shift based on the detected market regime. "
            "The only backtested and statistically validated strategy (India). "
            "UP_TREND → momentum-heavy. DOWN_TREND → mean-reversion-heavy."
        ),
        "use_regime_weights": True,
        "weights": {          # fallback only — actual weights come from REGIME_SIGNAL_WEIGHTS
            "mean_reversion": 0.33, "sector_neutral_mr": 0.34,
            "momentum": 0.33, "volume_mr": 0.0,
        },
    },
    "equal_weight": {
        "name": "⚖️ Equal Weight",
        "tag": "Exploratory",
        "color": "#3498db",
        "description": (
            "Simple 1/3 split across mean reversion, sector-neutral MR, and momentum. "
            "No regime conditioning. A clean baseline — easier to understand, "
            "slightly weaker than regime-conditional in practice."
        ),
        "use_regime_weights": False,
        "weights": {
            "mean_reversion": 0.333, "sector_neutral_mr": 0.334,
            "momentum": 0.333, "volume_mr": 0.0,
        },
    },
    "momentum_only": {
        "name": "🚀 Pure Momentum",
        "tag": "Exploratory",
        "color": "#f39c12",
        "description": (
            "100% 12-1 month momentum. Recent winners keep winning. "
            "Strong in sustained bull markets (UP_TREND regimes). "
            "Can hurt badly in sharp reversals."
        ),
        "use_regime_weights": False,
        "weights": {
            "mean_reversion": 0.0, "sector_neutral_mr": 0.0,
            "momentum": 1.0, "volume_mr": 0.0,
        },
    },
    "mr_heavy": {
        "name": "↩️ Mean Reversion Heavy",
        "tag": "Exploratory",
        "color": "#9b59b6",
        "description": (
            "50/50 mean reversion and sector-neutral MR. Zero momentum. "
            "Best in high-volatility or down-trend regimes. "
            "Fades recent losers expecting a bounce."
        ),
        "use_regime_weights": False,
        "weights": {
            "mean_reversion": 0.5, "sector_neutral_mr": 0.5,
            "momentum": 0.0, "volume_mr": 0.0,
        },
    },
    "volume_confirmed": {
        "name": "📊 Volume-Confirmed MR",
        "tag": "Experimental",
        "color": "#e67e22",
        "description": (
            "Mean reversion amplified by relative volume. "
            "Stocks that fell on high volume are stronger bounce candidates "
            "(institutional selling exhaustion). Uses OHLC volume data. "
            "Not yet backtested — treat as exploratory."
        ),
        "use_regime_weights": False,
        "weights": {
            "mean_reversion": 0.2, "sector_neutral_mr": 0.2,
            "momentum": 0.1, "volume_mr": 0.5,
        },
    },
}

DEFAULT_STRATEGY = "regime_ensemble"
