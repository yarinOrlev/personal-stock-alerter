"""
config.py
---------
Edit this file to control what gets watched and which signals alert you.
Secrets (Telegram token, email password) do NOT go here - they go in
environment variables / GitHub Secrets. See README.
"""

# ---- YOUR WATCHLIST ----
# Use Yahoo Finance ticker symbols.
#   US stocks:      "AAPL", "MSFT", "NVDA"
#   crypto:         "BTC-USD", "ETH-USD"
#   London:         "BARC.L"        (suffix .L)
#   Tel Aviv (TASE):"TEVA.TA"       (suffix .TA)
#   indices/ETFs:   "SPY", "QQQ", "^GSPC"
WATCHLIST = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "VOO",
    "VTV",
    "VEA",
    "META",
    "AVGO",
    "ANET",
    "SOFI",
    "MA",
    "V",
    "CRM",
    "LLY",
    "URNU",
]

# ---- TIMEFRAME ----
# Your script uses SMA200/150, which is built for the daily timeframe (DCA / swing).
# INTERVAL: "1d" (recommended), "1h", "30m", "15m"
# PERIOD:   how much history to fetch so the 200-bar averages are valid.
INTERVAL = "1d"
PERIOD = "2y"            # use "60d" for intraday intervals (Yahoo caps intraday history)

# Adjust prices for splits & dividends. Keeps SMA200 continuous across splits.
# (May differ slightly from a TradingView chart with adjustment turned off.)
AUTO_ADJUST = True

# ---- WHICH SIGNALS SHOULD ALERT YOU ----
# Remove any you don't want. These keys match signals.SIGNAL_PRIORITY.
ALERT_ON = [
    "PREMIUM_BUY",
    "STRONG_BUY",
    "MODERATE_BUY",
    "SELL_TRIM",
    "WARNING",
    # "AVOID",   # off by default - tends to be noisy
]

# Evaluate the signal on the last fully CLOSED bar (recommended).
# If True, the in-progress current bar is ignored so you don't get alerts that
# vanish before the bar closes - this matches TradingView's "Once per bar close".
CONFIRM_ON_CLOSED_BAR = True
