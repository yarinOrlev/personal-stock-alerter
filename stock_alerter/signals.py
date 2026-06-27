"""
signals.py
----------
Confluence-based signal engine. Instead of trusting one indicator, it builds a
0..100 *buy score* from several independent confirmations, then maps it to a tier.
It also detects sell/exit conditions. Every signal is explainable: it carries the
reasons, the indicator values, a suggested stop, a suggested position size, and the
condition that would invalidate it.

Design choices grounded in the research (see README "Strategy research"):
- Hard trend filter: a BUY requires price above the long-term SMA (200d). Buying
  below it is the classic way trend/momentum strategies bleed out.
- Regime gate: in a BEAR benchmark regime, buys are capped (no buying into a
  broad downtrend).
- Pullback-in-uptrend and recovering-from-oversold capture the mean-reversion edge
  (Connors-style) without abandoning the trend filter.
- Stops are ATR-based (volatility-aware) rather than fixed percentages.

Nothing here is financial advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional
import math

import pandas as pd

from .config import StrategyParams, RiskParams
from .regime import Regime


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCH = "WATCH"
    HOLD = "HOLD"
    TRIM = "TRIM"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


BUY_TIERS = {SignalType.STRONG_BUY, SignalType.BUY, SignalType.WATCH}
SELL_TIERS = {SignalType.TRIM, SignalType.SELL, SignalType.STRONG_SELL}
_TIER_ORDER = [SignalType.STRONG_BUY, SignalType.BUY, SignalType.WATCH,
               SignalType.HOLD, SignalType.TRIM, SignalType.SELL, SignalType.STRONG_SELL]


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class Signal:
    """A fully-explained recommendation for one symbol on one date."""

    symbol: str
    date: str
    signal: SignalType
    score: float                      # 0..100 buy-side composite (confidence)
    reasons: List[str] = field(default_factory=list)
    indicators: Dict[str, float] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    price: float = 0.0
    suggested_stop: Optional[float] = None
    suggested_shares: Optional[int] = None
    suggested_notional: Optional[float] = None
    invalidation: str = ""

    def is_actionable_buy(self) -> bool:
        return self.signal in (SignalType.STRONG_BUY, SignalType.BUY)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signal"] = self.signal.value
        d["risk_level"] = self.risk_level.value
        return d


def _risk_level(atr_pct: float) -> RiskLevel:
    if atr_pct < 2.0:
        return RiskLevel.LOW
    if atr_pct < 4.0:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def _buy_score(row: pd.Series, p: StrategyParams) -> tuple[float, List[str], Dict[str, float]]:
    """Compute the 0..100 buy composite from confluence of confirmations."""
    score = 0.0
    reasons: List[str] = []
    close = float(row["close"])

    # 1) Long-term trend (max 30) -- the backbone filter
    if bool(row["above_slow"]):
        score += 18
        reasons.append("Price above 200-day SMA (long-term uptrend)")
        if bool(row["golden"]):
            score += 12
            reasons.append("50-day above 200-day SMA (golden structure)")

    # 2) Momentum (max 20)
    if float(row["momentum"]) > 0:
        score += 8
        reasons.append(f"Positive 6-month momentum ({row['momentum']*100:.1f}%)")
    if bool(row["macd_cross_up"]) or float(row["macd_hist"]) > 0:
        score += 7
        reasons.append("MACD bullish")
    if float(row["roc"]) > 0:
        score += 5
        reasons.append("Positive rate-of-change")

    # 3) Pullback / oversold-recovery entry (max 20) -- buy dips within uptrend
    near_ema = float(row["dist_ema_pct"]) <= p.pullback_max_pct
    near_fast = float(row["dist_fast_pct"]) <= p.pullback_max_pct
    rsi = float(row["rsi"])
    if bool(row["above_slow"]) and (near_ema or near_fast):
        score += 12
        reasons.append("Pullback near rising 20/50 moving average")
    if p.rsi_oversold <= rsi <= 55:
        score += 8
        reasons.append(f"RSI recovering from oversold ({rsi:.0f})")

    # 4) Trend strength (max 10)
    if float(row["adx"]) >= p.adx_trend_min:
        score += 10
        reasons.append(f"ADX shows a real trend ({row['adx']:.0f})")

    # 5) Volume confirmation (max 10)
    if float(row["rel_volume"]) >= p.rel_volume_min and close >= float(row["open"]):
        score += 10
        reasons.append(f"Above-average volume on an up day ({row['rel_volume']:.1f}x)")

    # 6) Breakout (max 10)
    if bool(row["breakout"]):
        score += 10
        reasons.append("New 52-week high (breakout)")

    # Penalties
    if rsi > p.rsi_overbought:
        score -= 12
        reasons.append(f"RSI overbought ({rsi:.0f}) - chasing risk")
    if float(row["dist_fast_pct"]) > 15 and close > float(row["sma_fast"]):
        score -= 8
        reasons.append("Price stretched far above 50-day SMA")

    score = max(0.0, min(100.0, score))
    components = {
        "rsi": round(rsi, 1),
        "adx": round(float(row["adx"]), 1),
        "momentum_pct": round(float(row["momentum"]) * 100, 1),
        "rel_volume": round(float(row["rel_volume"]), 2),
        "dist_to_high_pct": round(float(row["dist_to_high"]), 1),
        "atr_pct": round(float(row["atr_pct"]), 2),
    }
    return score, reasons, components


def _sell_check(row: pd.Series, p: StrategyParams) -> tuple[Optional[SignalType], List[str]]:
    """Price-based exit/sell detection (position-independent)."""
    reasons: List[str] = []
    close = float(row["close"])
    rsi = float(row["rsi"])

    if close < float(row["sma_slow"]):
        reasons.append("Close below 200-day SMA (long-term trend break)")
        return SignalType.STRONG_SELL, reasons

    sell = False
    if bool(row["macd_cross_down"]):
        reasons.append("MACD bearish crossover")
        sell = True
    if close < float(row["sma_fast"]) and float(row["momentum"]) < 0:
        reasons.append("Below 50-day SMA with negative momentum")
        sell = True
    if sell:
        return SignalType.SELL, reasons

    if rsi > p.rsi_overbought and float(row["macd_hist"]) < 0:
        reasons.append(f"Overbought RSI ({rsi:.0f}) with weakening momentum")
        return SignalType.TRIM, reasons
    return None, reasons


def size_position(equity: float, cash: float, price: float, stop: float,
                  risk: RiskParams) -> tuple[int, float]:
    """Risk-based position sizing.

    Shares are chosen so that hitting the stop loses about ``risk_per_trade_pct``
    of equity, then capped by max position size and available cash.
    Returns (shares, notional).
    """
    if price <= 0 or stop <= 0 or stop >= price:
        return 0, 0.0
    risk_dollars = equity * risk.risk_per_trade_pct / 100.0
    per_share_risk = price - stop
    shares = math.floor(risk_dollars / per_share_risk) if per_share_risk > 0 else 0

    max_pos_dollars = equity * risk.max_position_pct / 100.0
    shares = min(shares, math.floor(max_pos_dollars / price))

    investable_cash = max(0.0, cash - equity * risk.min_cash_buffer_pct / 100.0)
    shares = min(shares, math.floor(investable_cash / price))
    return max(0, shares), max(0, shares) * price


def evaluate_row(symbol: str, row: pd.Series, date: str, regime: Regime,
                 p: StrategyParams, risk: RiskParams,
                 equity: Optional[float] = None,
                 cash: Optional[float] = None) -> Signal:
    """Produce a :class:`Signal` from a single pre-computed feature row.

    This is the shared core used by both the live runner and the backtester, so
    they can never drift apart.
    """
    close = float(row["close"])
    atr = float(row["atr"]) if pd.notna(row["atr"]) else 0.0
    atr_pct = float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else 0.0

    sell_type, sell_reasons = _sell_check(row, p)
    score, buy_reasons, comps = _buy_score(row, p)

    # Decide tier. Sells take precedence over weak buys.
    stop = round(close - risk.atr_stop_mult * atr, 2) if atr > 0 else None

    if sell_type == SignalType.STRONG_SELL:
        sig, reasons = SignalType.STRONG_SELL, sell_reasons
    elif score >= p.score_strong_buy and bool(row["above_slow"]) and regime != Regime.BEAR:
        sig, reasons = SignalType.STRONG_BUY, buy_reasons
    elif score >= p.score_buy and bool(row["above_slow"]) and regime != Regime.BEAR:
        sig, reasons = SignalType.BUY, buy_reasons
    elif sell_type == SignalType.SELL:
        sig, reasons = SignalType.SELL, sell_reasons
    elif sell_type == SignalType.TRIM:
        sig, reasons = SignalType.TRIM, sell_reasons
    elif score >= p.score_watch:
        sig, reasons = SignalType.WATCH, buy_reasons
        if regime == Regime.BEAR:
            reasons = reasons + ["Bearish market regime - buys held back"]
    else:
        sig, reasons = SignalType.HOLD, buy_reasons or ["No confluence of signals"]

    shares = notional = None
    if sig in (SignalType.STRONG_BUY, SignalType.BUY) and equity and stop:
        shares, notional = size_position(equity, cash if cash is not None else equity,
                                         close, stop, risk)

    invalidation = ""
    if sig in BUY_TIERS:
        sslow = float(row["sma_slow"])
        invalidation = (f"Close below stop {stop} (≈{risk.atr_stop_mult}×ATR) "
                        f"or below 200-day SMA {sslow:.2f}") if stop else \
                       f"Close below 200-day SMA {sslow:.2f}"
    elif sig in SELL_TIERS:
        invalidation = "Reclaim of the broken moving average on strong volume"

    return Signal(
        symbol=symbol, date=date, signal=sig, score=round(score, 1),
        reasons=reasons, indicators=comps, risk_level=_risk_level(atr_pct),
        price=round(close, 2), suggested_stop=stop,
        suggested_shares=shares, suggested_notional=round(notional, 2) if notional else None,
        invalidation=invalidation,
    )


def generate_signal(symbol: str, feat: pd.DataFrame, regime: Regime,
                    p: StrategyParams, risk: RiskParams, bar: int = -1,
                    equity: Optional[float] = None,
                    cash: Optional[float] = None) -> Signal:
    """Convenience wrapper: evaluate a symbol on a chosen bar of a feature frame.

    bar=-1 is the latest bar; bar=-2 is the last fully closed bar.
    """
    row = feat.iloc[bar]
    date = str(feat.index[bar].date())
    return evaluate_row(symbol, row, date, regime, p, risk, equity, cash)
