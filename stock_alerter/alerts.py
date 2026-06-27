"""
alerts.py
---------
Email alerting (SMTP) plus formatting of rich Signal objects and a small JSON
state file that prevents the same signal from emailing you twice for the same bar.

Credentials come from environment variables (.env / GitHub Secrets):
  EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, EMAIL_USER, EMAIL_PASSWORD, EMAIL_TO
Use an app password, not your normal login password.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from typing import List

from .signals import Signal

logger = logging.getLogger(__name__)


# --------------------------- email -------------------------------------- #
def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else val


def send_email(subject: str, body: str) -> bool:
    host = _env("EMAIL_SMTP_HOST")
    port = int(_env("EMAIL_SMTP_PORT", "587"))
    user = _env("EMAIL_USER")
    password = _env("EMAIL_PASSWORD")
    to_addr = _env("EMAIL_TO") or user
    if not (host and user and password):
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to_addr
    recipients = [a.strip() for a in to_addr.split(",")]
    try:
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.sendmail(user, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.sendmail(user, recipients, msg.as_string())
        return True
    except Exception as e:  # pragma: no cover - network dependent
        logger.error("email send failed: %s", e)
        return False


# --------------------------- formatting --------------------------------- #
def format_signal(sig: Signal) -> str:
    lines = [
        f"{sig.symbol}  —  {sig.signal.value}  (score {sig.score}/100, risk {sig.risk_level.value})",
        f"Date:  {sig.date}",
        f"Price: {sig.price}",
    ]
    if sig.suggested_stop:
        lines.append(f"Suggested stop: {sig.suggested_stop}")
    if sig.suggested_shares:
        lines.append(f"Suggested size: {sig.suggested_shares} shares (~{sig.suggested_notional})")
    if sig.reasons:
        lines.append("Why: " + "; ".join(sig.reasons[:6]))
    ind = sig.indicators
    if ind:
        lines.append("Indicators: " + ", ".join(f"{k}={v}" for k, v in ind.items()))
    if sig.invalidation:
        lines.append(f"Invalidated if: {sig.invalidation}")
    return "\n".join(lines)


def format_digest(signals: List[Signal]) -> str:
    blocks = [format_signal(s) for s in signals]
    return ("\n" + "-" * 48 + "\n").join(blocks)


# --------------------------- dedup state -------------------------------- #
STATE_FILE = os.environ.get("ALERT_STATE_FILE", "alert_state.json")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
    except Exception as e:  # pragma: no cover
        logger.error("could not save state: %s", e)


def is_new(state: dict, sig: Signal) -> bool:
    entry = state.get(sig.symbol)
    return not (entry and entry.get("date") == sig.date and entry.get("signal") == sig.signal.value)


def record(state: dict, sig: Signal) -> None:
    state[sig.symbol] = {"date": sig.date, "signal": sig.signal.value}
