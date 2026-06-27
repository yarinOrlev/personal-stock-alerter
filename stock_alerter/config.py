"""
config.py
---------
Central, typed configuration. Edit ``DEFAULT_CONFIG`` (or build your own
:class:`Config`) to control the watchlist, monthly capital plan, risk limits,
trading costs, and signal thresholds.

Secrets (email credentials) are NOT here - they live in environment variables /
a .env file / GitHub Secrets. See alerts.py and the README.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class StrategyParams:
    """Indicator periods and signal thresholds. Defaults reflect widely-studied,
    robust settings (200/50-day trend filter, 14-day RSI, 6-month momentum)."""

    # Moving averages
    sma_fast: int = 50
    sma_slow: int = 200
    ema_pullback: int = 20            # pullback-to-trend reference
    # Oscillators
    rsi_period: int = 14
    rsi_oversold: float = 35.0
    rsi_overbought: float = 70.0
    # Momentum
    momentum_lookback: int = 126      # ~6 months of trading days
    roc_period: int = 20
    # Volatility / bands
    bb_period: int = 20
    bb_mult: float = 2.0
    atr_period: int = 14
    adx_period: int = 14
    adx_trend_min: float = 20.0       # ADX above this = a real trend
    # Volume
    vol_avg_period: int = 20
    rel_volume_min: float = 1.0       # volume confirmation threshold
    # Structure
    high_lookback: int = 252          # 52-week window
    pullback_max_pct: float = 8.0     # "near" an MA if within this %
    # Scoring thresholds (0..100 composite buy score)
    score_strong_buy: float = 75.0
    score_buy: float = 60.0
    score_watch: float = 45.0


@dataclass
class RiskParams:
    """Position sizing and portfolio risk limits."""

    risk_per_trade_pct: float = 1.0        # % of equity risked to the stop on a new buy
    atr_stop_mult: float = 2.5             # initial stop = entry - mult * ATR
    atr_trail_mult: float = 3.0            # trailing stop distance in ATRs
    take_profit_atr_mult: float = 0.0      # 0 = disabled (let trend/trail run)
    max_position_pct: float = 20.0         # max % of equity in a single name
    max_portfolio_exposure_pct: float = 100.0  # max % of equity invested at once
    max_open_positions: int = 8
    min_cash_buffer_pct: float = 5.0       # always keep at least this % in cash


@dataclass
class CostParams:
    """Transaction costs used by the backtester (and shown in live sizing)."""

    commission_per_trade: float = 0.0      # most US brokers are commission-free
    commission_pct: float = 0.0            # e.g. 0.001 = 0.1% per side
    slippage_pct: float = 0.05             # modeled slippage per side, in percent


@dataclass
class Config:
    """Top-level configuration object."""

    watchlist: List[str] = field(default_factory=lambda: [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "JPM", "COST", "UNH", "XOM",
    ])
    benchmark: str = "SPY"                 # market-regime filter symbol
    interval: str = "1d"
    period: str = "5y"                     # history to fetch (>= 2y so SMA200 is valid)
    auto_adjust: bool = True               # split/dividend-adjusted prices

    monthly_contribution: float = 1000.0   # cash added at the start of each month
    starting_cash: float = 0.0

    strategy: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskParams = field(default_factory=RiskParams)
    costs: CostParams = field(default_factory=CostParams)

    # Live alerting: only email signals at or above this tier.
    alert_min_tier: str = "BUY"            # one of STRONG_BUY, BUY, WATCH
    # False = evaluate the live, still-forming daily bar (current price) so you can
    #         act intraday. True = wait for the bar to close (fewer false alarms).
    confirm_on_closed_bar: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = Config()
