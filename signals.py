"""
signals.py
----------
A faithful Python port of your "DCA" Pine Script's buy/sell logic.

`compute_signals(df)` takes an OHLCV DataFrame (columns: open, high, low, close,
volume) and returns the same DataFrame with every indicator, score and signal
column added. `latest_signal(df)` returns a dict describing the recommendation on
the most recent bar, mirroring the script's RECOMMENDATION table cell.

Every threshold and formula below maps 1:1 to a line in your Pine Script so the
alerts you get here match what you see on your TradingView chart.
"""

import numpy as np
import pandas as pd

import indicators as ta


# Priority order, highest first. Mirrors the RECOMMENDATION cell precedence.
SIGNAL_PRIORITY = [
    "PREMIUM_BUY",
    "STRONG_BUY",
    "MODERATE_BUY",
    "SELL_TRIM",
    "WARNING",
    "AVOID",
]

SIGNAL_LABELS = {
    "PREMIUM_BUY": "\u2605\u2605\u2605 PREMIUM BUY",
    "STRONG_BUY": "\u2605\u2605 STRONG BUY",
    "MODERATE_BUY": "\u2605 MODERATE BUY",
    "SELL_TRIM": "\u2716 SELL / TRIM",
    "WARNING": "\u26a0 WARNING (overbought)",
    "AVOID": "\U0001f6d1 AVOID (weak trend)",
}


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]

    # === MOVING AVERAGES ===
    df["sma20"] = ta.sma(c, 20)
    df["sma50"] = ta.sma(c, 50)
    df["sma150"] = ta.sma(c, 150)
    df["sma200"] = ta.sma(c, 200)
    sma20, sma50, sma150, sma200 = df["sma20"], df["sma50"], df["sma150"], df["sma200"]

    # === RSI ===
    df["rsi"] = ta.rsi(c, 14)
    rsi = df["rsi"]

    # === MACD ===
    macd_line, signal_line, macd_hist = ta.macd(c, 12, 26, 9)
    df["macd"], df["macd_signal"] = macd_line, signal_line
    macd_bullish = macd_line > signal_line
    macd_cross_up = ta.crossover(macd_line, signal_line)
    macd_cross_down = ta.crossunder(macd_line, signal_line)

    # === BOLLINGER BANDS ===
    bb_basis = ta.sma(c, 20)
    bb_dev = 2.0 * ta.stdev(c, 20)
    bb_upper = bb_basis + bb_dev
    bb_lower = bb_basis - bb_dev
    price_near_lower_bb = c <= bb_lower * 1.02
    price_near_upper_bb = c >= bb_upper * 0.98

    # === VOLUME ===
    avg_vol20 = ta.sma(v, 20)
    volume_spike = v > avg_vol20 * 1.5
    volume_above_avg = v > avg_vol20
    volume_drying = v < avg_vol20 * 0.7

    # === TREND ===
    bearish_trend = (sma20 < sma50) & (sma50 < sma150)
    price_below_all = (c < sma20) & (c < sma50) & (c < sma150) & (c < sma200)

    trend_score = (
        (sma20 > sma50).astype(int) * 25
        + (sma50 > sma150).astype(int) * 25
        + (sma150 > sma200).astype(int) * 25
        + (c > sma50).astype(int) * 25
    )
    df["trend_score"] = trend_score

    # === CANDLESTICK PATTERNS ===
    o1, c1 = o.shift(1), c.shift(1)
    o2, c2 = o.shift(2), c.shift(2)
    h1, l1 = h.shift(1), l.shift(1)

    bullish_engulfing = (c1 < o1) & (c > o) & (c >= o1) & (o <= c1) & ((c - o) > (o1 - c1))
    hammer = ((h - l) > 3 * (c - o)) & (((c - l) / (0.001 + h - l)) > 0.6) & (((h - c) / (0.001 + h - l)) < 0.4)
    morningstar = (c2 < o2) & ((c1 - o1).abs() < (h1 - l1) * 0.3) & (c > o) & (c > (o2 + c2) / 2)
    bullish_harami = (c1 < o1) & (c > o) & (o > c1) & (c < o1)
    piercing = (c1 < o1) & (c > o) & (o < c1) & (c > (o1 + c1) / 2) & (c < o1)

    bearish_engulfing = (c1 > o1) & (c < o) & (c <= o1) & (o >= c1) & ((o - c) > (c1 - o1))
    shooting_star = ((h - l) > 3 * (o - c)) & (((h - c) / (0.001 + h - l)) > 0.6) & (((c - l) / (0.001 + h - l)) < 0.4)
    evening_star = (c2 > o2) & ((c1 - o1).abs() < (h1 - l1) * 0.3) & (c < o) & (c < (o2 + c2) / 2)
    bearish_harami = (c1 > o1) & (c < o) & (o < c1) & (c > o1)
    dark_cloud = (c1 > o1) & (c < o) & (o > c1) & (c < (o1 + c1) / 2) & (c > o1)

    bullish_pattern = bullish_engulfing | hammer | morningstar | bullish_harami | piercing
    bearish_pattern = bearish_engulfing | shooting_star | evening_star | bearish_harami | dark_cloud
    df["bullish_pattern"] = bullish_pattern
    df["bearish_pattern"] = bearish_pattern

    # === RSI DIVERGENCE ===
    price_lower_low = (l < l.shift(5)) & (l.shift(5) < l.shift(10))
    rsi_higher_low = (rsi > rsi.shift(5)) & (rsi.shift(5) > rsi.shift(10))
    bullish_div = price_lower_low & rsi_higher_low & (rsi < 45)

    price_higher_high = (h > h.shift(5)) & (h.shift(5) > h.shift(10))
    rsi_lower_high = (rsi < rsi.shift(5)) & (rsi.shift(5) < rsi.shift(10))
    bearish_div = price_higher_high & rsi_lower_high & (rsi > 55)

    # === MOMENTUM SCORE (0-100, may go negative) ===
    ms = pd.Series(0.0, index=df.index)
    ms += np.select([rsi < 30, rsi < 40, rsi < 50], [30, 20, 10], default=0)
    ms -= np.select([rsi > 70, rsi > 60], [30, 15], default=0)
    ms += np.where(macd_bullish, 10, 0)
    ms += np.where(macd_cross_up, 10, 0)
    ms -= np.where(macd_cross_down, 20, 0)
    ms += np.where(bullish_pattern, 15, 0)
    ms += np.where(bullish_div, 10, 0)
    ms -= np.where(bearish_pattern, 15, 0)
    ms -= np.where(bearish_div, 10, 0)
    ms += np.where(price_near_lower_bb, 15, 0)
    ms -= np.where(price_near_upper_bb, 15, 0)
    ms += np.where(volume_spike & (c > o), 10, 0)
    ms -= np.where(volume_drying, 5, 0)
    momentum_score = ms
    df["momentum_score"] = momentum_score

    # === BUY ZONES ===
    dist50 = (c - sma50).abs() / sma50 * 100.0
    dist150 = (c - sma150).abs() / sma150 * 100.0
    dist200 = (c - sma200).abs() / sma200 * 100.0
    near50 = (dist50 <= 5.0) & (c < sma50)
    near150 = (dist150 <= 7.0) & (c < sma150)
    near200 = (dist200 <= 10.0) & (c < sma200)
    deep_dip = near200
    medium_dip = near150 & ~near200
    shallow_dip = near50 & ~near150
    df["dist50"], df["dist200"] = dist50, dist200

    # === SIGNALS (multi-factor confluence) ===
    premium_buy_score = (trend_score >= 50) & (momentum_score >= 40) & deep_dip & volume_above_avg
    premium_buy = premium_buy_score | (bullish_pattern & (rsi < 35) & macd_cross_up & near200 & (trend_score >= 50))

    strong_buy_score = (trend_score >= 50) & (momentum_score >= 25) & (medium_dip | shallow_dip) & volume_above_avg
    strong_buy = strong_buy_score & ~premium_buy

    moderate_buy_score = (trend_score >= 40) & (momentum_score >= 15) & (near50 | near150 | bullish_pattern)
    moderate_buy = moderate_buy_score & ~strong_buy & ~premium_buy

    premium_sell = bearish_pattern & (rsi > 70) & macd_cross_down & price_near_upper_bb
    strong_sell = ((rsi > 75) | bearish_div) & price_near_upper_bb & ~premium_sell

    caution = (trend_score < 40) | bearish_trend | price_below_all
    avoid = caution & near200

    df["PREMIUM_BUY"] = premium_buy
    df["STRONG_BUY"] = strong_buy
    df["MODERATE_BUY"] = moderate_buy
    df["SELL_TRIM"] = premium_sell
    df["WARNING"] = strong_sell
    df["AVOID"] = avoid

    return df


def latest_signal(df: pd.DataFrame, bar: int = -1) -> dict:
    """Return the top-priority signal on the chosen bar (default = most recent)."""
    row = df.iloc[bar]
    fired = None
    for key in SIGNAL_PRIORITY:
        if bool(row.get(key, False)):
            fired = key
            break
    return {
        "signal": fired,                       # None means HOLD / no actionable signal
        "label": SIGNAL_LABELS.get(fired, "HOLD"),
        "date": df.index[bar],
        "close": float(row["close"]),
        "rsi": float(row["rsi"]) if pd.notna(row["rsi"]) else None,
        "trend_score": int(row["trend_score"]) if pd.notna(row["trend_score"]) else None,
        "momentum_score": int(round(row["momentum_score"])) if pd.notna(row["momentum_score"]) else None,
        "dist200": float(row["dist200"]) if pd.notna(row["dist200"]) else None,
    }
