"""
data.py
-------
Data access. ``load_history`` pulls OHLCV from Yahoo Finance (free, no API key).
``synthetic_ohlcv`` generates deterministic fake data so the whole system can be
tested offline and in CI without network or survivorship-free datasets.

Recommended source: Yahoo Finance via the ``yfinance`` package. It is free and
split/dividend-adjusts by default (``auto_adjust=True``), which keeps SMA200
continuous across splits. Its main limitations: occasional gaps/late revisions,
intraday history caps (~60 days), and no point-in-time index membership (so true
survivorship-bias-free backtests need a different paid dataset - see README).
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED = ["open", "high", "low", "close", "volume"]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns, lowercase, keep OHLCV, drop NaN rows."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    keep = [c for c in REQUIRED if c in df.columns]
    df = df[keep].dropna()
    return df


def load_history(symbol: str, period: str = "5y", interval: str = "1d",
                 auto_adjust: bool = True) -> pd.DataFrame:
    """Load OHLCV for one symbol from Yahoo Finance.

    Returns an empty DataFrame on failure (caller decides how to handle it).
    """
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover - environment dependent
        raise ImportError("yfinance not installed. Run: pip install -r requirements.txt") from e

    try:
        raw = yf.download(symbol, period=period, interval=interval,
                          auto_adjust=auto_adjust, progress=False, threads=False)
    except Exception as e:  # network/ticker errors
        logger.warning("Download failed for %s: %s", symbol, e)
        return pd.DataFrame()
    if raw is None or raw.empty:
        logger.warning("No data returned for %s", symbol)
        return pd.DataFrame()
    return _normalize(raw)


def load_watchlist(symbols, period="5y", interval="1d",
                   auto_adjust=True) -> Dict[str, pd.DataFrame]:
    """Load history for many symbols; silently skips ones that fail."""
    out: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = load_history(sym, period, interval, auto_adjust)
        if not df.empty:
            out[sym] = df
        else:
            logger.warning("Skipping %s (no data)", sym)
    return out


def synthetic_ohlcv(n: int = 800, seed: int = 0, start: str = "2021-01-04",
                    drift: float = 0.04, vol: float = 1.0,
                    regime_shifts: bool = True) -> pd.DataFrame:
    """Deterministic synthetic OHLCV for tests/CI.

    Produces a trending random walk with optional bull/bear/bull regime shifts so
    that buy *and* sell signals both have a chance to fire.
    """
    rng = np.random.default_rng(seed)
    if regime_shifts:
        seg = n // 3
        drifts = np.concatenate([
            np.full(seg, abs(drift)),
            np.full(seg, -abs(drift) * 1.5),
            np.full(n - 2 * seg, abs(drift) * 1.2),
        ])
    else:
        drifts = np.full(n, drift)
    shocks = rng.normal(0, vol, n)
    close = 100 + np.cumsum(drifts + shocks)
    close = np.maximum(close, 1.0)
    open_ = close + rng.normal(0, vol * 0.4, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, vol * 0.5, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, vol * 0.5, n))
    volume = np.abs(rng.normal(1_000_000, 300_000, n)).astype(float)
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)
