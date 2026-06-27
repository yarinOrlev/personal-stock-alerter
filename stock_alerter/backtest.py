"""
backtest.py
-----------
Event-driven, daily backtester for a watchlist with monthly cash contributions.

How lookahead bias is avoided
-----------------------------
- Features at bar *t* use only data up to *t* (rolling windows, no `.shift(-k)`).
- A signal computed from the close of day *t-1* is executed at the **open of day
  *t*** - you can never trade on a price you couldn't have known.
- Stops/take-profits set from day *t-1* data are monitored against day *t*'s
  high/low, with gap-through fills handled conservatively.

How metrics stay honest
-----------------------
- Monthly contributions are external cash flows. Performance ratios are computed
  on a **time-weighted return** index that strips out contributions, so adding
  money never looks like "returns". The raw portfolio value and total contributed
  are reported separately.
- Transaction costs (slippage + optional commission) are charged on every fill.

Limitations (be honest): the watchlist is fixed and chosen today, so this does
NOT correct for survivorship bias - see README.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import Config
from .features import compute_features, min_bars_required
from .metrics import PerformanceReport, build_report
from .portfolio import Portfolio
from .regime import classify_regime, Regime
from .signals import evaluate_row, SignalType, size_position

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    report: PerformanceReport
    equity_curve: pd.Series                 # raw portfolio value (incl. contributions)
    twr_index: pd.Series                    # time-weighted return index (base 1.0)
    daily: pd.DataFrame                     # cash/value/exposure per day
    trades: List[dict] = field(default_factory=list)
    total_contributed: float = 0.0
    final_equity: float = 0.0

    def to_json(self, path: str) -> None:
        payload = {
            "report": self.report.to_dict(),
            "total_contributed": self.total_contributed,
            "final_equity": self.final_equity,
            "trades": self.trades,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)

    def export_csv(self, prefix: str) -> None:
        self.daily.to_csv(f"{prefix}_daily.csv")
        pd.DataFrame(self.trades).to_csv(f"{prefix}_trades.csv", index=False)


def _exit_reference_price(row: pd.Series, stop: float,
                          take_profit: Optional[float]) -> Optional[tuple[float, str]]:
    """Decide if/where a position exits on this bar (conservative gap handling)."""
    op, hi, lo = float(row["open"]), float(row["high"]), float(row["low"])
    # Stop checked first (worst case if both hit the same day).
    if lo <= stop:
        return (op if op <= stop else stop), "stop"
    if take_profit is not None and hi >= take_profit:
        return (op if op >= take_profit else take_profit), "take_profit"
    return None


def run_backtest(prices: Dict[str, pd.DataFrame], cfg: Config,
                 benchmark: Optional[pd.DataFrame] = None) -> BacktestResult:
    """Run the backtest.

    Args:
        prices: {symbol: OHLCV DataFrame}.
        cfg: full configuration.
        benchmark: OHLCV for the regime benchmark (e.g. SPY). If None, regime is
            derived from an equal-weight composite of the watchlist.
    """
    if not prices:
        raise ValueError("No price data provided to backtest.")

    p, risk, costs = cfg.strategy, cfg.risk, cfg.costs

    # Pre-compute features per symbol.
    feats = {sym: compute_features(df, p) for sym, df in prices.items() if len(df) > 5}

    # Master calendar = sorted union of all dates.
    all_dates = sorted(set().union(*[set(f.index) for f in feats.values()]))
    calendar = pd.DatetimeIndex(all_dates)

    # Align each symbol to the calendar (NaN where missing).
    aligned = {sym: f.reindex(calendar) for sym, f in feats.items()}

    # Benchmark close on the calendar for regime.
    if benchmark is not None and not benchmark.empty:
        bench_close = benchmark["close"].reindex(calendar).ffill()
    else:
        comp = pd.concat([f["close"] for f in aligned.values()], axis=1).mean(axis=1)
        bench_close = comp.ffill()

    warmup = min_bars_required(p)
    pf = Portfolio(cash=cfg.starting_cash)

    records = []
    twr_returns = []
    total_contributed = cfg.starting_cash
    prev_equity = cfg.starting_cash
    prev_month = None

    for i in range(1, len(calendar)):
        d = calendar[i]
        date_str = str(d.date())

        # ---- start-of-month contribution (external cash flow) ----
        flow = 0.0
        if prev_month is not None and d.month != prev_month:
            pf.add_cash(cfg.monthly_contribution)
            flow = cfg.monthly_contribution
            total_contributed += flow
        prev_month = d.month

        # Skip until warmed up.
        if i < warmup:
            prev_equity = pf.equity(_closes_on(aligned, i, calendar))
            continue

        regime = classify_regime(bench_close.iloc[: i], bar=-1, slow=p.sma_slow)

        # Today's tradeable rows (need a valid current bar AND a valid prior bar).
        today_rows = {}
        prior_signals = {}
        for sym, f in aligned.items():
            row_t = f.iloc[i]
            row_p = f.iloc[i - 1]
            if row_t[["open", "high", "low", "close"]].isna().any():
                continue
            if pd.isna(row_p["sma_slow"]) or pd.isna(row_p["atr"]):
                continue
            today_rows[sym] = row_t
            prior_signals[sym] = evaluate_row(sym, row_p, str(calendar[i - 1].date()),
                                              regime, p, risk)

        # ---- 1) EXITS (stops / take-profit / signal sells) at today's bar ----
        for sym in list(pf.positions.keys()):
            if sym not in today_rows:
                continue
            row_t = today_rows[sym]
            pos = pf.positions[sym]
            ref = _exit_reference_price(row_t, pos.stop, pos.take_profit)
            if ref is not None:
                price, reason = ref
                pf.close_position(sym, price, date_str, costs, reason)
                continue
            sig = prior_signals.get(sym)
            if sig and sig.signal in (SignalType.STRONG_SELL, SignalType.SELL):
                pf.close_position(sym, float(row_t["open"]), date_str, costs,
                                  sig.signal.value)

        # ---- 2) BUYS at today's open, best score first ----
        equity_for_sizing = pf.equity(_closes_on(aligned, i - 1, calendar))
        candidates = [
            (sym, prior_signals[sym]) for sym in today_rows
            if not pf.holds(sym)
            and prior_signals[sym].signal in (SignalType.STRONG_BUY, SignalType.BUY)
        ]
        candidates.sort(key=lambda x: x[1].score, reverse=True)

        for sym, sig in candidates:
            if len(pf.positions) >= risk.max_open_positions:
                break
            row_t = today_rows[sym]
            entry = float(row_t["open"])
            atr = float(aligned[sym].iloc[i - 1]["atr"])
            stop = round(entry - risk.atr_stop_mult * atr, 2)
            if stop <= 0 or stop >= entry:
                continue
            # Portfolio exposure cap.
            cur_prices = _closes_on(aligned, i, calendar)
            if pf.exposure(cur_prices) >= risk.max_portfolio_exposure_pct / 100.0:
                break
            shares, _ = size_position(equity_for_sizing, pf.cash, entry, stop, risk)
            if shares <= 0:
                continue
            tp = (round(entry + risk.take_profit_atr_mult * atr, 2)
                  if risk.take_profit_atr_mult > 0 else None)
            pf.open_position(sym, shares, entry, date_str, stop, costs, tp)

        # ---- 3) trailing stops on today's close ----
        for sym, pos in pf.positions.items():
            if sym in today_rows:
                row_t = today_rows[sym]
                pf.update_trailing(sym, float(row_t["close"]), float(row_t["atr"]), risk)

        # ---- 4) record end-of-day state ----
        cur_prices = _closes_on(aligned, i, calendar)
        equity = pf.equity(cur_prices)
        exposure = pf.exposure(cur_prices)
        records.append({"date": d, "cash": pf.cash, "equity": equity,
                        "exposure": exposure, "n_positions": len(pf.positions),
                        "contribution": flow})

        # time-weighted daily return (strip out the contribution made at start of day)
        base = prev_equity + flow
        twr_returns.append((d, (equity / base - 1.0) if base > 0 else 0.0))
        prev_equity = equity

    daily = pd.DataFrame(records).set_index("date") if records else pd.DataFrame()
    twr = pd.Series(dict(twr_returns)).sort_index() if twr_returns else pd.Series(dtype=float)
    twr_index = (1 + twr).cumprod() if not twr.empty else pd.Series(dtype=float)

    report = build_report(
        equity=twr_index if not twr_index.empty else daily.get("equity", pd.Series(dtype=float)),
        trade_returns=pd.Series(pf.trade_returns()),
        exposure=daily["exposure"] if "exposure" in daily else None,
    )
    return BacktestResult(
        report=report,
        equity_curve=daily["equity"] if "equity" in daily else pd.Series(dtype=float),
        twr_index=twr_index,
        daily=daily,
        trades=[t.__dict__ for t in pf.trades],
        total_contributed=total_contributed,
        final_equity=float(daily["equity"].iloc[-1]) if "equity" in daily and len(daily) else 0.0,
    )


def _closes_on(aligned: Dict[str, pd.DataFrame], i: int,
               calendar: pd.DatetimeIndex) -> Dict[str, float]:
    """Last-known close for each symbol at calendar position ``i`` (ffill-safe)."""
    out = {}
    for sym, f in aligned.items():
        val = f["close"].iloc[i]
        if pd.isna(val):
            prior = f["close"].iloc[: i + 1].dropna()
            if prior.empty:
                continue
            val = prior.iloc[-1]
        out[sym] = float(val)
    return out
