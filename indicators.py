"""
indicators.py
-------------
Faithful Python ports of the Pine Script `ta.*` functions used in your DCA script.

Notes on fidelity:
- ta.rsi / ta.atr use Wilder's smoothing (RMA), seeded with an SMA. Reproduced here.
- ta.ema uses alpha = 2/(n+1). pandas ewm(adjust=False) matches once warmed up.
- ta.stdev defaults to the *population* standard deviation (divides by N), so we
  use ddof=0 to match Bollinger Bands exactly.
- ta.crossover / ta.crossunder reproduced explicitly.
With a long history (we fetch ~2y of daily bars), all of these converge to
TradingView's values to well within rounding for the signal thresholds.
"""

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def rma(series: pd.Series, n: int) -> pd.Series:
    """Wilder's moving average (Pine ta.rma): EMA with alpha = 1/n, seeded by SMA(n)."""
    arr = series.to_numpy(dtype="float64")
    out = np.full(len(arr), np.nan)
    if len(arr) < n:
        return pd.Series(out, index=series.index)
    alpha = 1.0 / n
    seed = np.nanmean(arr[:n])
    out[n - 1] = seed
    for i in range(n, len(arr)):
        prev = out[i - 1]
        x = arr[i]
        if np.isnan(x):
            x = 0.0
        out[i] = alpha * x + (1.0 - alpha) * prev
    return pd.Series(out, index=series.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Pine ta.rsi — Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).fillna(0)
    loss = (-delta.clip(upper=0)).fillna(0)
    avg_gain = rma(gain, n)
    avg_loss = rma(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # When avg_loss == 0 -> RSI 100; when avg_gain == 0 -> RSI 0
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(avg_gain != 0, 0.0)
    return out


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return rma(tr, n)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def stdev(series: pd.Series, n: int) -> pd.Series:
    """Pine ta.stdev defaults to population stdev (ddof=0)."""
    return series.rolling(n).std(ddof=0)


def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """a crosses above b on this bar."""
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """a crosses below b on this bar."""
    return (a < b) & (a.shift(1) >= b.shift(1))
