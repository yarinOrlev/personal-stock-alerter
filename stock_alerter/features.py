"""
features.py
-----------
Turns raw OHLCV into a feature DataFrame of indicator columns used by both the
signal engine and the backtester. Keeping this in one place guarantees that live
alerts and backtests see *identical* features (no logic drift between them).

No lookahead: every column at bar t depends only on bars <= t.
"""

from __future__ import annotations

import pandas as pd

from . import indicators as ta
from .config import StrategyParams


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def compute_features(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    """Compute the full indicator set. Input columns: open, high, low, close, volume."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")

    out = df.copy()
    c, h, l, v = out["close"], out["high"], out["low"], out["volume"]

    out["sma_fast"] = ta.sma(c, p.sma_fast)
    out["sma_slow"] = ta.sma(c, p.sma_slow)
    out["ema_pullback"] = ta.ema(c, p.ema_pullback)
    out["sma20"] = ta.sma(c, 20)

    out["rsi"] = ta.rsi(c, p.rsi_period)
    macd_line, macd_sig, macd_hist = ta.macd(c)
    out["macd"], out["macd_signal"], out["macd_hist"] = macd_line, macd_sig, macd_hist

    out["roc"] = ta.roc(c, p.roc_period)
    out["momentum"] = ta.momentum_lookback(c, p.momentum_lookback)

    basis, upper, lower = ta.bollinger(c, p.bb_period, p.bb_mult)
    out["bb_basis"], out["bb_upper"], out["bb_lower"] = basis, upper, lower

    out["atr"] = ta.atr(h, l, c, p.atr_period)
    out["atr_pct"] = out["atr"] / c * 100.0
    adx_val, plus_di, minus_di = ta.adx(h, l, c, p.adx_period)
    out["adx"], out["plus_di"], out["minus_di"] = adx_val, plus_di, minus_di

    out["rel_volume"] = ta.relative_volume(v, p.vol_avg_period)
    out["dist_to_high"] = ta.distance_to_high(c, h, p.high_lookback)
    out["breakout"] = ta.donchian_breakout(c, h, p.high_lookback)

    # Convenience booleans (still no lookahead)
    out["above_slow"] = c > out["sma_slow"]
    out["golden"] = out["sma_fast"] > out["sma_slow"]
    out["macd_cross_up"] = ta.crossover(macd_line, macd_sig)
    out["macd_cross_down"] = ta.crossunder(macd_line, macd_sig)
    out["dist_fast_pct"] = (c - out["sma_fast"]).abs() / out["sma_fast"] * 100.0
    out["dist_ema_pct"] = (c - out["ema_pullback"]).abs() / out["ema_pullback"] * 100.0
    return out


def min_bars_required(p: StrategyParams) -> int:
    """Bars needed before features are fully warmed up."""
    return max(p.sma_slow, p.high_lookback, p.momentum_lookback) + 5
