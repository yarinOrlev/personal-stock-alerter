"""
run_alerts.py
-------------
The main loop. For each ticker in your watchlist it:
  1. downloads recent OHLCV from Yahoo Finance (free, no API key),
  2. runs your DCA signal engine,
  3. reads the recommendation on the last closed bar,
  4. sends an alert if it's an actionable signal you asked for and hasn't been
     sent already for that bar.

Run it manually (`python run_alerts.py`), on a local schedule (cron / Task
Scheduler), or for free in the cloud via GitHub Actions (see README).
"""

import os
import sys
import datetime as dt

import pandas as pd


def _load_dotenv(path: str = ".env") -> None:
    """Tiny .env loader (no extra dependency). Existing env vars take priority."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_dotenv()

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance is not installed. Run:  pip install -r requirements.txt")

import config
from signals import compute_signals, latest_signal
from notifier import notify
from state import load_state, save_state, already_alerted, record


def fetch(ticker: str) -> pd.DataFrame:
    df = yf.download(
        ticker,
        period=config.PERIOD,
        interval=config.INTERVAL,
        auto_adjust=config.AUTO_ADJUST,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    # yfinance can return a MultiIndex column frame; flatten to single level.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df


def format_alert(ticker: str, sig: dict) -> tuple[str, str]:
    date_str = pd.Timestamp(sig["date"]).date().isoformat()
    subject = f"{ticker}: {sig['label']}"
    lines = [
        f"Ticker:   {ticker}",
        f"Signal:   {sig['label']}",
        f"Bar date: {date_str}  ({config.INTERVAL})",
        f"Price:    {sig['close']:.2f}",
    ]
    if sig["rsi"] is not None:
        lines.append(f"RSI(14):  {sig['rsi']:.0f}")
    if sig["trend_score"] is not None:
        lines.append(f"Trend:    {sig['trend_score']}/100")
    if sig["momentum_score"] is not None:
        lines.append(f"Momentum: {sig['momentum_score']}")
    if sig["dist200"] is not None:
        lines.append(f"vs SMA200: {sig['dist200']:.1f}%")
    return subject, "\n".join(lines)


def main():
    print(f"Run at {dt.datetime.now().isoformat(timespec='seconds')} | "
          f"{len(config.WATCHLIST)} tickers | interval={config.INTERVAL}")
    state = load_state()
    alerts_sent = 0

    for ticker in config.WATCHLIST:
        try:
            df = fetch(ticker)
        except Exception as e:
            print(f"[{ticker}] fetch error: {e}")
            continue
        if df.empty or len(df) < 210:
            print(f"[{ticker}] not enough data ({0 if df.empty else len(df)} bars) - skipped")
            continue

        out = compute_signals(df)
        bar = -2 if config.CONFIRM_ON_CLOSED_BAR and len(out) >= 2 else -1
        sig = latest_signal(out, bar=bar)

        if sig["signal"] is None:
            print(f"[{ticker}] HOLD (close {sig['close']:.2f})")
            continue
        if sig["signal"] not in config.ALERT_ON:
            print(f"[{ticker}] {sig['signal']} present but not in ALERT_ON - skipped")
            continue

        date_str = pd.Timestamp(sig["date"]).date().isoformat()
        if already_alerted(state, ticker, date_str, sig["signal"]):
            print(f"[{ticker}] {sig['signal']} already alerted for {date_str} - skipped")
            continue

        subject, body = format_alert(ticker, sig)
        notify(subject, body)
        record(state, ticker, date_str, sig["signal"])
        alerts_sent += 1

    save_state(state)
    print(f"Done. {alerts_sent} alert(s) sent.")


if __name__ == "__main__":
    main()
