"""
test_engine.py
--------------
Validates the signal engine without needing internet or yfinance.
Generates a synthetic OHLCV series (random walk with a designed dip-and-recover
section) and confirms every indicator/signal column computes without error and
that signals actually fire.
"""

import numpy as np
import pandas as pd

from signals import compute_signals, latest_signal, SIGNAL_PRIORITY


def make_synthetic(n=600, seed=7):
    rng = np.random.default_rng(seed)
    # Trending random walk so SMAs stack bullishly part of the time
    drift = np.concatenate([
        np.full(250, 0.06),    # uptrend
        np.full(120, -0.18),   # pullback / dip
        np.full(230, 0.10),    # recovery uptrend
    ])[:n]
    shocks = rng.normal(0, 0.9, n)
    close = 100 + np.cumsum(drift + shocks)
    close = np.maximum(close, 5)

    # Build OHLC around close
    open_ = close + rng.normal(0, 0.5, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.6, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.6, n))
    vol = np.abs(rng.normal(1_000_000, 350_000, n)).astype(float)

    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def main():
    df = make_synthetic()
    out = compute_signals(df)

    required = [
        "sma20", "sma50", "sma150", "sma200", "rsi", "macd", "macd_signal",
        "trend_score", "momentum_score", "dist50", "dist200",
    ] + SIGNAL_PRIORITY
    missing = [c for c in required if c not in out.columns]
    assert not missing, f"Missing columns: {missing}"

    # No NaNs in the scores once warmed up (after 200 bars)
    warm = out.iloc[210:]
    assert warm["trend_score"].notna().all(), "trend_score has NaNs after warmup"
    assert warm["rsi"].between(0, 100).all(), "RSI out of bounds"

    print("Columns OK. RSI range:",
          round(warm["rsi"].min(), 1), "-", round(warm["rsi"].max(), 1))
    print("Trend score range:", int(warm["trend_score"].min()), "-", int(warm["trend_score"].max()))
    print("Momentum score range:", int(warm["momentum_score"].min()), "-", int(warm["momentum_score"].max()))

    # Count how often each signal fired over the series
    print("\nSignal counts over", len(warm), "warmed-up bars:")
    total = 0
    for key in SIGNAL_PRIORITY:
        cnt = int(out[key].iloc[210:].sum())
        total += cnt
        print(f"  {key:13s}: {cnt}")
    assert total > 0, "No signals fired at all - logic likely broken"

    # Show a few example fired bars with the top-priority recommendation
    print("\nSample of fired signals (top-priority per bar):")
    shown = 0
    for i in range(210, len(out)):
        sig = latest_signal(out, bar=i)
        if sig["signal"] is not None:
            print(f"  {sig['date'].date()}  {sig['label']:24s} "
                  f"close={sig['close']:.2f} rsi={sig['rsi']:.0f} "
                  f"trend={sig['trend_score']} mom={sig['momentum_score']}")
            shown += 1
            if shown >= 8:
                break

    print("\nLatest bar recommendation:", latest_signal(out)["label"])
    print("\nALL ENGINE TESTS PASSED.")


if __name__ == "__main__":
    main()
