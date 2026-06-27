#!/usr/bin/env python3
"""
run_backtest.py
---------------
Run the watchlist backtest and print a performance report.

Usage:
    python run_backtest.py                  # use Yahoo data for the configured watchlist
    python run_backtest.py --synthetic      # offline: deterministic fake data (no network)
    python run_backtest.py --out results    # also export results_daily.csv / _trades.csv / .json
"""

from __future__ import annotations

import argparse
import logging

from stock_alerter.config import DEFAULT_CONFIG
from stock_alerter.backtest import run_backtest
from stock_alerter.data import load_watchlist, load_history, synthetic_ohlcv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run_backtest")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true", help="use offline synthetic data")
    ap.add_argument("--out", default=None, help="export prefix for CSV/JSON results")
    args = ap.parse_args()

    cfg = DEFAULT_CONFIG

    if args.synthetic:
        log.info("Using synthetic data (offline).")
        prices = {s: synthetic_ohlcv(n=1000, seed=i) for i, s in enumerate(cfg.watchlist)}
        bench = synthetic_ohlcv(n=1000, seed=999)
    else:
        log.info("Downloading %d symbols + benchmark from Yahoo Finance...", len(cfg.watchlist))
        prices = load_watchlist(cfg.watchlist, cfg.period, cfg.interval, cfg.auto_adjust)
        bench = load_history(cfg.benchmark, cfg.period, cfg.interval, cfg.auto_adjust)
        if not prices:
            log.error("No data downloaded. Try --synthetic, or check connectivity/tickers.")
            return

    result = run_backtest(prices, cfg, benchmark=bench if not bench.empty else None)
    r = result.report

    print("\n=== BACKTEST REPORT ===")
    print(f"Period:           {r.start} -> {r.end}  ({r.n_periods} days)")
    print(f"Total contributed:{result.total_contributed:>12,.0f}")
    print(f"Final value:      {result.final_equity:>12,.0f}")
    print(f"Time-weighted CAGR:{r.cagr_pct:>10.2f}%")
    print(f"Annual volatility: {r.annual_vol_pct:>10.2f}%")
    print(f"Sharpe / Sortino:  {r.sharpe:>5.2f} / {r.sortino:.2f}")
    print(f"Max drawdown:      {r.max_drawdown_pct:>10.2f}%   Calmar: {r.calmar}")
    print(f"Avg exposure:      {r.exposure_pct:>10.2f}%")
    print(f"Trades:            {r.n_trades}   Win rate: {r.win_rate_pct}%   "
          f"Profit factor: {r.profit_factor}")
    print(f"Avg win / loss:    {r.avg_win_pct}% / {r.avg_loss_pct}%")

    if args.out:
        result.export_csv(args.out)
        result.to_json(f"{args.out}.json")
        log.info("Exported %s_daily.csv, %s_trades.csv, %s.json", args.out, args.out, args.out)


if __name__ == "__main__":
    main()
