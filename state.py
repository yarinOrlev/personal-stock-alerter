"""
state.py
--------
Remembers the last alert sent per ticker so the same signal on the same bar is
never sent twice, even if the script runs many times a day.

State is a small JSON file: { "AAPL": {"date": "2026-06-19", "signal": "STRONG_BUY"} }
"""

import json
import os

STATE_FILE = os.environ.get("ALERT_STATE_FILE", "alert_state.json")


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
    except Exception as e:
        print(f"[state] could not save: {e}")


def already_alerted(state: dict, ticker: str, date_str: str, signal: str) -> bool:
    entry = state.get(ticker)
    return bool(entry and entry.get("date") == date_str and entry.get("signal") == signal)


def record(state: dict, ticker: str, date_str: str, signal: str) -> None:
    state[ticker] = {"date": date_str, "signal": signal}
