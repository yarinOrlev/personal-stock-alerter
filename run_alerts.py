#!/usr/bin/env python3
"""
run_alerts.py
-------------
Live (or scheduled) watchlist scan. Loads data, computes confluence signals on the
last closed bar, filters to the tiers you care about, de-duplicates, and emails a
digest. Sells/trims are always surfaced (risk management); buys are surfaced at or
above ``alert_min_tier``.

Usage:
    python run_alerts.py                # scan and email
    python run_alerts.py --test-email   # send a test email and exit
    python run_alerts.py --dry-run      # print to console, do not email
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from stock_alerter.config import DEFAULT_CONFIG, Config
from stock_alerter.data import load_history, load_watchlist
from stock_alerter.features import compute_features, min_bars_required
from stock_alerter.regime import classify_regime
from stock_alerter.signals import generate_signal, SignalType, BUY_TIERS, SELL_TIERS
from stock_alerter import alerts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run_alerts")

_TIER_RANK = {SignalType.STRONG_BUY: 3, SignalType.BUY: 2, SignalType.WATCH: 1}


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def scan(cfg: Config):
    """Return a list of actionable Signal objects for the watchlist."""
    data = load_watchlist(cfg.watchlist, cfg.period, cfg.interval, cfg.auto_adjust)
    bench_df = load_history(cfg.benchmark, cfg.period, cfg.interval, cfg.auto_adjust)
    bench_close = bench_df["close"] if not bench_df.empty else None

    bar = -2 if cfg.confirm_on_closed_bar else -1
    regime = classify_regime(bench_close, bar=bar, slow=cfg.strategy.sma_slow) if bench_close is not None else None

    min_tier = _TIER_RANK.get(SignalType(cfg.alert_min_tier), 2)
    out = []
    for sym, df in data.items():
        if len(df) < min_bars_required(cfg.strategy):
            log.warning("%s: insufficient history (%d bars)", sym, len(df))
            continue
        feat = compute_features(df, cfg.strategy)
        sig = generate_signal(sym, feat, regime or classify_regime(None),
                              cfg.strategy, cfg.risk, bar=bar,
                              equity=cfg.monthly_contribution, cash=cfg.monthly_contribution)
        if sig.signal in BUY_TIERS and _TIER_RANK.get(sig.signal, 0) >= min_tier:
            out.append(sig)
        elif sig.signal in SELL_TIERS:        # always surface risk-management signals
            out.append(sig)
    # Best buys first, then sells.
    out.sort(key=lambda s: (s.signal in SELL_TIERS, -s.score))
    return out, regime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-email", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    _load_dotenv()

    cfg = DEFAULT_CONFIG

    if args.test_email:
        ok = alerts.send_email("TEST: personal-stock-alerter email works",
                               "If you can read this, your EMAIL_* settings are correct.")
        print("Test email sent." if ok else "Email not configured / failed (see logs).")
        return

    signals, regime = scan(cfg)
    if not signals:
        log.info("No actionable signals. Market regime: %s", regime)
        return

    state = alerts.load_state()
    fresh = [s for s in signals if alerts.is_new(state, s)]
    if not fresh:
        log.info("All %d signal(s) already alerted.", len(signals))
        return

    body = (f"Market regime: {regime}\n\n" + alerts.format_digest(fresh))
    subject = f"Watchlist: {len(fresh)} signal(s) — " + ", ".join(
        f"{s.symbol} {s.signal.value}" for s in fresh[:4])

    print("\n" + "=" * 60 + f"\n{subject}\n" + "=" * 60 + f"\n{body}\n")
    if args.dry_run:
        log.info("Dry run - not emailing.")
        return
    if alerts.send_email(subject, body):
        for s in fresh:
            alerts.record(state, s)
        alerts.save_state(state)
        log.info("Emailed %d signal(s).", len(fresh))
    else:
        log.warning("Email not configured/failed; signals printed above only.")


if __name__ == "__main__":
    sys.exit(main())
