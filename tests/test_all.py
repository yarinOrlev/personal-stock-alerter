"""
test_all.py
-----------
Tests for indicators, the no-lookahead property, the signal engine, portfolio
mechanics, performance metrics, the backtester, and edge cases.

Runs under pytest *or* standalone via ../run_tests.py (no pytest needed).
"""

import numpy as np
import pandas as pd

from stock_alerter import indicators as ta
from stock_alerter import metrics as M
from stock_alerter.config import Config, RiskParams
from stock_alerter.data import synthetic_ohlcv
from stock_alerter.features import compute_features, min_bars_required
from stock_alerter.regime import classify_regime, Regime
from stock_alerter.signals import (evaluate_row, generate_signal, size_position,
                                   SignalType, BUY_TIERS, SELL_TIERS)
from stock_alerter.portfolio import Portfolio
from stock_alerter.config import CostParams
from stock_alerter.backtest import run_backtest


# --------------------------- indicators --------------------------------- #
def test_sma_matches_manual():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    assert abs(ta.sma(s, 3).iloc[-1] - 4.0) < 1e-9


def test_rsi_bounds():
    df = synthetic_ohlcv(400, seed=1)
    r = ta.rsi(df["close"], 14).dropna()
    assert r.between(0, 100).all()


def test_atr_positive():
    df = synthetic_ohlcv(400, seed=2)
    a = ta.atr(df["high"], df["low"], df["close"], 14).dropna()
    assert (a >= 0).all() and len(a) > 0


def test_crossover_logic():
    a = pd.Series([1, 2, 3, 2, 1], dtype=float)
    b = pd.Series([2, 2, 2, 2, 2], dtype=float)
    co = ta.crossover(a, b)
    cu = ta.crossunder(a, b)
    assert bool(co.iloc[2]) is True       # 2->3 crosses above 2
    assert bool(cu.iloc[4]) is True       # 2->1 crosses below 2 (equals 2 doesn't count)


def test_bollinger_ordering():
    df = synthetic_ohlcv(200, seed=3)
    basis, up, lo = ta.bollinger(df["close"], 20, 2.0)
    valid = basis.dropna().index
    assert (up.loc[valid] >= basis.loc[valid]).all()
    assert (lo.loc[valid] <= basis.loc[valid]).all()


# --------------------------- no lookahead ------------------------------- #
def test_features_no_lookahead():
    """A feature value at bar t must not change when future bars are appended."""
    p = Config().strategy
    df = synthetic_ohlcv(500, seed=4)
    full = compute_features(df, p)
    t = 400
    truncated = compute_features(df.iloc[: t + 1], p)
    for col in ["sma_slow", "rsi", "macd", "atr", "adx", "momentum"]:
        a = full[col].iloc[t]
        b = truncated[col].iloc[t]
        if pd.notna(a) and pd.notna(b):
            assert abs(a - b) < 1e-6, f"lookahead in {col}: {a} vs {b}"


# --------------------------- signals ------------------------------------ #
def test_buy_requires_above_slow():
    """No BUY/STRONG_BUY may be issued when price is below the 200-day SMA."""
    p, risk = Config().strategy, Config().risk
    df = synthetic_ohlcv(900, seed=5)
    feat = compute_features(df, p)
    for i in range(min_bars_required(p), len(feat)):
        row = feat.iloc[i]
        sig = evaluate_row("X", row, str(feat.index[i].date()), Regime.BULL, p, risk)
        if sig.signal in (SignalType.STRONG_BUY, SignalType.BUY):
            assert bool(row["above_slow"]), "buy issued below 200-SMA"


def test_bear_regime_caps_buys():
    p, risk = Config().strategy, Config().risk
    df = synthetic_ohlcv(900, seed=6)
    feat = compute_features(df, p)
    found = False
    for i in range(min_bars_required(p), len(feat)):
        s_bull = evaluate_row("X", feat.iloc[i], "d", Regime.BULL, p, risk)
        s_bear = evaluate_row("X", feat.iloc[i], "d", Regime.BEAR, p, risk)
        if s_bull.signal in (SignalType.STRONG_BUY, SignalType.BUY):
            found = True
            assert s_bear.signal not in (SignalType.STRONG_BUY, SignalType.BUY)
    assert found, "test never produced a buy to check"


def test_size_position_risk_math():
    risk = RiskParams(risk_per_trade_pct=1.0, max_position_pct=100.0, min_cash_buffer_pct=0.0)
    # equity 100k, risk 1% = $1000; stop $5 away -> 200 shares
    shares, notional = size_position(100_000, 100_000, price=100, stop=95, risk=risk)
    assert shares == 200
    assert abs(notional - 20_000) < 1e-6


def test_size_position_capped_by_cash():
    risk = RiskParams(risk_per_trade_pct=50.0, max_position_pct=100.0, min_cash_buffer_pct=0.0)
    shares, _ = size_position(100_000, 1_000, price=100, stop=90, risk=risk)
    assert shares == 10                     # only $1000 cash -> 10 shares


# --------------------------- portfolio ---------------------------------- #
def test_portfolio_open_close_costs():
    costs = CostParams(commission_per_trade=0.0, commission_pct=0.0, slippage_pct=0.0)
    pf = Portfolio(cash=10_000)
    assert pf.open_position("A", 10, 100, "2020-01-01", 90, costs)
    assert abs(pf.cash - 9_000) < 1e-6
    pf.close_position("A", 110, "2020-02-01", costs, "exit")
    assert abs(pf.cash - 10_100) < 1e-6     # +$100 profit
    assert pf.trades[0].return_pct > 0


def test_trailing_stop_only_rises():
    risk = RiskParams(atr_trail_mult=2.0)
    costs = CostParams(slippage_pct=0.0)
    pf = Portfolio(cash=10_000)
    pf.open_position("A", 10, 100, "d", 90, costs)
    pf.update_trailing("A", 110, atr=2.0, risk=risk)      # stop -> 106
    assert pf.positions["A"].stop == 106
    pf.update_trailing("A", 105, atr=2.0, risk=risk)      # lower close -> no change
    assert pf.positions["A"].stop == 106


def test_slippage_costs_money():
    costs = CostParams(slippage_pct=0.1)
    pf = Portfolio(cash=10_000)
    pf.open_position("A", 10, 100, "d", 90, costs)
    # bought above 100 due to slippage -> less cash than the frictionless 9000
    assert pf.cash < 9_000


# --------------------------- metrics ------------------------------------ #
def test_max_drawdown_known():
    eq = pd.Series([100, 120, 60, 90], index=pd.bdate_range("2020-01-01", periods=4))
    assert abs(M.max_drawdown(eq) - (-0.5)) < 1e-9     # 120 -> 60 = -50%


def test_cagr_doubling():
    idx = pd.bdate_range("2020-01-01", periods=M.TRADING_DAYS + 1)
    eq = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    assert abs(M.cagr(eq) - 1.0) < 0.05                # ~doubled in ~1y


# --------------------------- backtest ----------------------------------- #
def test_backtest_runs_and_reports():
    cfg = Config()
    cfg.watchlist = ["A", "B", "C"]
    prices = {s: synthetic_ohlcv(700, seed=i) for i, s in enumerate(cfg.watchlist)}
    bench = synthetic_ohlcv(700, seed=50)
    res = run_backtest(prices, cfg, benchmark=bench)
    assert res.report.n_periods > 0
    assert res.total_contributed >= cfg.monthly_contribution
    assert -1.0 <= res.report.max_drawdown_pct / 100 <= 0.0


def test_backtest_handles_insufficient_history():
    cfg = Config()
    cfg.watchlist = ["A"]
    prices = {"A": synthetic_ohlcv(50, seed=1)}        # far less than warmup
    bench = synthetic_ohlcv(50, seed=2)
    res = run_backtest(prices, cfg, benchmark=bench)   # must not raise
    assert res.report.n_trades == 0


def test_compute_features_missing_column_raises():
    df = synthetic_ohlcv(50, seed=1).drop(columns=["volume"])
    try:
        compute_features(df, Config().strategy)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_nan_rows_do_not_crash_backtest():
    cfg = Config()
    cfg.watchlist = ["A", "B"]
    a = synthetic_ohlcv(700, seed=1)
    b = synthetic_ohlcv(700, seed=2)
    b.iloc[300:320] = np.nan                           # simulate a data gap
    res = run_backtest({"A": a, "B": b}, cfg, benchmark=synthetic_ohlcv(700, seed=3))
    assert res.report.n_periods > 0


if __name__ == "__main__":
    # allow `python tests/test_all.py`
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed.")
