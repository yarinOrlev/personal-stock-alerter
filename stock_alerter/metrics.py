"""
metrics.py
----------
Performance and risk metrics for an equity curve and a trade log.

All functions are pure and operate on plain pandas/numpy objects so they are easy
to unit-test. Returns are treated as simple (arithmetic) period returns unless
stated otherwise. Annualization uses ``periods_per_year`` (252 for daily bars).

Nothing here is financial advice; these are descriptive statistics on a series.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd


TRADING_DAYS = 252


@dataclass
class PerformanceReport:
    """Container for headline performance/risk statistics."""

    start: Optional[str]
    end: Optional[str]
    n_periods: int
    total_return_pct: float
    cagr_pct: float
    annual_vol_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    calmar: float
    best_period_pct: float
    worst_period_pct: float
    exposure_pct: float
    n_trades: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float

    def to_dict(self) -> dict:
        return asdict(self)


def equity_returns(equity: pd.Series) -> pd.Series:
    """Simple period-over-period returns from an equity curve."""
    return equity.pct_change().dropna()


def cagr(equity: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    """Compound annual growth rate from first to last equity value."""
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    years = len(equity) / periods_per_year
    if years <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)


def annual_volatility(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> float:
    if returns.empty:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0,
                 periods_per_year: int = TRADING_DAYS) -> float:
    """Annualized Sharpe ratio. risk_free_rate is an annual rate."""
    if returns.empty:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return 0.0
    return float(excess.mean() / sd * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0,
                  periods_per_year: int = TRADING_DAYS) -> float:
    """Annualized Sortino ratio (downside deviation in the denominator)."""
    if returns.empty:
        return 0.0
    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    downside = excess[excess < 0]
    dd = np.sqrt((downside ** 2).mean()) if not downside.empty else 0.0
    if dd == 0 or np.isnan(dd):
        return 0.0
    return float(excess.mean() / dd * np.sqrt(periods_per_year))


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown at each point relative to the running peak (0 to -1)."""
    equity = equity.dropna()
    running_max = equity.cummax()
    return equity / running_max - 1.0


def max_drawdown(equity: pd.Series) -> float:
    dd = drawdown_series(equity)
    return float(dd.min()) if not dd.empty else 0.0


def build_report(equity: pd.Series,
                 trade_returns: Optional[pd.Series] = None,
                 exposure: Optional[pd.Series] = None,
                 risk_free_rate: float = 0.0,
                 periods_per_year: int = TRADING_DAYS) -> PerformanceReport:
    """Assemble a full :class:`PerformanceReport` from an equity curve.

    Args:
        equity: portfolio value over time (indexed by date).
        trade_returns: per-trade percentage returns (for win-rate stats).
        exposure: fraction of capital invested at each step (0..1) for exposure %.
    """
    equity = equity.dropna()
    rets = equity_returns(equity)
    mdd = max_drawdown(equity)
    cagr_val = cagr(equity, periods_per_year)

    if trade_returns is None or len(trade_returns) == 0:
        n_trades = 0
        win_rate = avg_win = avg_loss = profit_factor = 0.0
    else:
        tr = pd.Series(trade_returns).dropna()
        n_trades = int(len(tr))
        wins = tr[tr > 0]
        losses = tr[tr < 0]
        win_rate = float(len(wins) / n_trades * 100) if n_trades else 0.0
        avg_win = float(wins.mean() * 100) if not wins.empty else 0.0
        avg_loss = float(losses.mean() * 100) if not losses.empty else 0.0
        gross_win = float(wins.sum())
        gross_loss = float(-losses.sum())
        profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")

    return PerformanceReport(
        start=str(equity.index[0].date()) if len(equity) else None,
        end=str(equity.index[-1].date()) if len(equity) else None,
        n_periods=int(len(equity)),
        total_return_pct=float((equity.iloc[-1] / equity.iloc[0] - 1) * 100) if len(equity) >= 2 else 0.0,
        cagr_pct=round(cagr_val * 100, 2),
        annual_vol_pct=round(annual_volatility(rets, periods_per_year) * 100, 2),
        sharpe=round(sharpe_ratio(rets, risk_free_rate, periods_per_year), 2),
        sortino=round(sortino_ratio(rets, risk_free_rate, periods_per_year), 2),
        max_drawdown_pct=round(mdd * 100, 2),
        calmar=round(cagr_val / abs(mdd), 2) if mdd < 0 else 0.0,
        best_period_pct=round(float(rets.max() * 100), 2) if not rets.empty else 0.0,
        worst_period_pct=round(float(rets.min() * 100), 2) if not rets.empty else 0.0,
        exposure_pct=round(float(exposure.mean() * 100), 2) if exposure is not None and len(exposure) else 0.0,
        n_trades=n_trades,
        win_rate_pct=round(win_rate, 2),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else float("inf"),
    )
