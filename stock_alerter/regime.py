"""
regime.py
---------
Market-regime filter. Buying into a broad downtrend is one of the biggest
destroyers of trend/momentum strategies, so we gate buys on the health of a
benchmark (default SPY). Evidence: trend filters like the 200-day/10-month rule
historically cut equity drawdowns sharply by moving to cash in bear phases
(Faber 2007), at the cost of whipsaws in choppy markets.

Regime is one of: BULL, NEUTRAL, BEAR.
"""

from __future__ import annotations

from enum import Enum

import pandas as pd

from . import indicators as ta


class Regime(str, Enum):
    BULL = "BULL"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"


def classify_regime(benchmark_close: pd.Series, bar: int = -1,
                     slow: int = 200, slope_lookback: int = 20) -> Regime:
    """Classify the market regime on a given bar.

    BULL    : price above the slow SMA and the SMA rising.
    BEAR    : price below the slow SMA and the SMA falling.
    NEUTRAL : mixed / not enough data.
    """
    if benchmark_close is None or len(benchmark_close) < slow + slope_lookback:
        return Regime.NEUTRAL
    sma_slow = ta.sma(benchmark_close, slow)
    price = float(benchmark_close.iloc[bar])
    ma_now = float(sma_slow.iloc[bar])
    ma_then = float(sma_slow.iloc[bar - slope_lookback])
    if pd.isna(ma_now) or pd.isna(ma_then):
        return Regime.NEUTRAL
    rising = ma_now >= ma_then
    if price >= ma_now and rising:
        return Regime.BULL
    if price < ma_now and not rising:
        return Regime.BEAR
    return Regime.NEUTRAL
