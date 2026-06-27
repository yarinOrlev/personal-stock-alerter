"""
portfolio.py
------------
Portfolio state and mechanics shared by the live (paper) runner and the
backtester: cash, positions, monthly contributions, transaction costs, ATR-based
initial stops, trailing stops, optional take-profit, and a trade log.

Costs are modeled realistically: slippage moves the fill against you on both
entry and exit, plus optional commissions. This keeps backtests honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import CostParams, RiskParams


@dataclass
class Position:
    symbol: str
    shares: int
    entry_price: float
    entry_date: str
    stop: float
    highest_close: float            # running peak for the trailing stop
    take_profit: Optional[float] = None

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    return_pct: float
    reason: str


@dataclass
class Portfolio:
    """Cash + open positions + closed-trade log."""

    cash: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)

    # ----- cash ----- #
    def add_cash(self, amount: float) -> None:
        self.cash += amount

    # ----- valuation ----- #
    def market_value(self, prices: Dict[str, float]) -> float:
        return sum(pos.shares * prices.get(sym, pos.entry_price)
                   for sym, pos in self.positions.items())

    def equity(self, prices: Dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def exposure(self, prices: Dict[str, float]) -> float:
        eq = self.equity(prices)
        return self.market_value(prices) / eq if eq > 0 else 0.0

    def holds(self, symbol: str) -> bool:
        return symbol in self.positions

    # ----- trading (costs applied here) ----- #
    def _buy_fill(self, price: float, costs: CostParams) -> float:
        return price * (1 + costs.slippage_pct / 100.0)

    def _sell_fill(self, price: float, costs: CostParams) -> float:
        return price * (1 - costs.slippage_pct / 100.0)

    def open_position(self, symbol: str, shares: int, price: float, date: str,
                      stop: float, costs: CostParams,
                      take_profit: Optional[float] = None) -> bool:
        """Buy ``shares`` at a slippage-adjusted fill. Returns True on success."""
        if shares <= 0 or symbol in self.positions:
            return False
        fill = self._buy_fill(price, costs)
        commission = costs.commission_per_trade + fill * shares * costs.commission_pct / 100.0
        total = fill * shares + commission
        if total > self.cash + 1e-9:
            return False
        self.cash -= total
        self.positions[symbol] = Position(
            symbol=symbol, shares=shares, entry_price=fill, entry_date=date,
            stop=stop, highest_close=price, take_profit=take_profit,
        )
        return True

    def close_position(self, symbol: str, price: float, date: str,
                       costs: CostParams, reason: str) -> Optional[Trade]:
        """Sell the whole position at a slippage-adjusted fill and log the trade."""
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        fill = self._sell_fill(price, costs)
        commission = costs.commission_per_trade + fill * pos.shares * costs.commission_pct / 100.0
        proceeds = fill * pos.shares - commission
        self.cash += proceeds
        pnl = proceeds - pos.cost_basis
        ret = (fill / pos.entry_price - 1.0) if pos.entry_price > 0 else 0.0
        trade = Trade(symbol, pos.entry_date, date, pos.entry_price, fill,
                      pos.shares, pnl, ret, reason)
        self.trades.append(trade)
        del self.positions[symbol]
        return trade

    # ----- stop management ----- #
    def update_trailing(self, symbol: str, close: float, atr: float,
                        risk: RiskParams) -> None:
        """Ratchet the stop up as price makes new highs (never lowers the stop)."""
        pos = self.positions.get(symbol)
        if pos is None or atr <= 0:
            return
        if close > pos.highest_close:
            pos.highest_close = close
            new_stop = close - risk.atr_trail_mult * atr
            if new_stop > pos.stop:
                pos.stop = round(new_stop, 2)

    def trade_returns(self) -> List[float]:
        return [t.return_pct for t in self.trades]
