"""
indicators.py
-------------
Pure, vectorized technical indicators. Every function takes pandas Series/DataFrame
and returns pandas objects aligned to the input index. No function looks ahead:
the value at bar *t* uses only data up to and including *t*.

Implementations match TradingView/Pine ``ta.*`` conventions where relevant:
- RSI and ATR use Wilder's smoothing (RMA), seeded with an SMA.
- Bollinger Bands use the *population* standard deviation (ddof=0).
- EMA uses alpha = 2/(n+1).

These are deliberately separate from signal logic (see signals.py) so indicators
stay reusable and independently testable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Moving averages
# --------------------------------------------------------------------------- #
def sma(series: pd.Series, n: int) -> pd.Series:
    """Simple moving average over ``n`` periods."""
    return series.rolling(n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    """Exponential moving average, alpha = 2/(n+1)."""
    return series.ewm(span=n, adjust=False).mean()


def rma(series: pd.Series, n: int) -> pd.Series:
    """Wilder's moving average (Pine ``ta.rma``): EMA alpha=1/n seeded by SMA(n)."""
    arr = series.to_numpy(dtype="float64")
    out = np.full(len(arr), np.nan)
    if len(arr) < n:
        return pd.Series(out, index=series.index)
    alpha = 1.0 / n
    out[n - 1] = np.nanmean(arr[:n])
    for i in range(n, len(arr)):
        x = arr[i]
        out[i] = alpha * (0.0 if np.isnan(x) else x) + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def slope(series: pd.Series, n: int = 5) -> pd.Series:
    """Percent change of a series over ``n`` periods (a simple slope proxy)."""
    return (series - series.shift(n)) / series.shift(n) * 100.0


# --------------------------------------------------------------------------- #
# Oscillators / momentum
# --------------------------------------------------------------------------- #
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0).fillna(0)
    loss = (-delta.clip(upper=0)).fillna(0)
    avg_gain = rma(gain, n)
    avg_loss = rma(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    out = out.where(avg_loss != 0, 100.0).where(avg_gain != 0, 0.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Return (macd_line, signal_line, histogram)."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def roc(close: pd.Series, n: int = 20) -> pd.Series:
    """Rate of change (percent) over ``n`` periods."""
    return (close / close.shift(n) - 1.0) * 100.0


def momentum_lookback(close: pd.Series, n: int = 126) -> pd.Series:
    """Total return over ``n`` periods (e.g. 126 ~ 6 months) as a fraction."""
    return close / close.shift(n) - 1.0


# --------------------------------------------------------------------------- #
# Volatility / bands
# --------------------------------------------------------------------------- #
def stdev(series: pd.Series, n: int) -> pd.Series:
    """Population standard deviation (ddof=0), matching Pine ``ta.stdev``."""
    return series.rolling(n).std(ddof=0)


def bollinger(close: pd.Series, n: int = 20, mult: float = 2.0):
    """Return (basis, upper, lower) Bollinger Bands."""
    basis = sma(close, n)
    dev = mult * stdev(close, n)
    return basis, basis + dev, basis - dev


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return rma(tr, n)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """Average Directional Index plus +DI/-DI. Measures trend *strength*.

    Returns (adx, plus_di, minus_di). ADX > ~25 is conventionally "trending".
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move.clip(lower=0)
    tr = pd.concat([(high - low).abs(),
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr_n = rma(tr, n)
    plus_di = 100 * rma(plus_dm, n) / atr_n.replace(0, np.nan)
    minus_di = 100 * rma(minus_dm, n) / atr_n.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return rma(dx.fillna(0), n), plus_di, minus_di


# --------------------------------------------------------------------------- #
# Volume
# --------------------------------------------------------------------------- #
def volume_sma(volume: pd.Series, n: int = 20) -> pd.Series:
    return volume.rolling(n).mean()


def relative_volume(volume: pd.Series, n: int = 20) -> pd.Series:
    """Volume divided by its ``n``-period average (1.0 = average)."""
    avg = volume_sma(volume, n)
    return volume / avg.replace(0, np.nan)


# --------------------------------------------------------------------------- #
# Structure: highs/lows, breakouts, distance to 52-week high
# --------------------------------------------------------------------------- #
def rolling_high(high: pd.Series, n: int) -> pd.Series:
    return high.rolling(n).max()


def rolling_low(low: pd.Series, n: int) -> pd.Series:
    return low.rolling(n).min()


def distance_to_high(close: pd.Series, high: pd.Series, n: int = 252) -> pd.Series:
    """Percent below the trailing ``n``-period high (0 = at the high, negative = below)."""
    hh = rolling_high(high, n)
    return (close / hh - 1.0) * 100.0


def donchian_breakout(close: pd.Series, high: pd.Series, n: int = 252) -> pd.Series:
    """Boolean: close makes a new ``n``-period high (uses prior bars' high to avoid self-reference)."""
    prior_high = rolling_high(high, n).shift(1)
    return close > prior_high


# --------------------------------------------------------------------------- #
# Crossovers
# --------------------------------------------------------------------------- #
def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """True on the bar where ``a`` crosses above ``b``."""
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """True on the bar where ``a`` crosses below ``b``."""
    return (a < b) & (a.shift(1) >= b.shift(1))
