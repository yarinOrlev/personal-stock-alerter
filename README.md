# Free Watchlist Buy/Sell Alerts (Email)

A free replacement for TradingView's paid real-time alerts. It runs the **exact
same logic as your "DCA" Pine Script** in Python, pulls free price data from
Yahoo Finance, and **emails you** whenever a watchlist stock hits a buy or sell
signal.

No paid subscriptions. No API keys for the price data. Can run entirely free in
the cloud so your computer doesn't have to be on.

---

## What's inside

| File | Purpose |
|------|---------|
| `indicators.py` | Pine `ta.*` functions ported to Python (RSI, ATR, MACD, BB, etc.) |
| `signals.py` | Line-for-line port of your buy/sell logic and scores |
| `config.py` | **Your watchlist and settings — edit this** |
| `notifier.py` | Sends the email alerts |
| `run_alerts.py` | The main program you run |
| `state.py` | Stops duplicate alerts for the same bar |
| `test_engine.py` | Offline self-test of the signal math |
| `.github/workflows/alerts.yml` | Free scheduled cloud runs (GitHub Actions) |

Signals reproduced: **Premium Buy, Strong Buy, Moderate Buy, Sell/Trim, Warning,
Avoid** — same trend score, momentum score, candlestick patterns, RSI divergence,
Bollinger Bands and volume confluence as your script.

---

## Step 1 — Set up the email account (do this once)

You need an email account to *send from*. The cleanest option is a free Gmail
account used only for these alerts.

1. Turn on **2-Step Verification** on the account
   (Google Account → Security).
2. Create an **App Password**: Google Account → Security → 2-Step Verification →
   **App passwords**. Pick "Mail" / "Other", and Google gives you a 16-character
   password. **Use that**, not your normal password.
3. You'll send to and from the same address (or set `EMAIL_TO` to any inbox you
   want the alerts to land in — even a different provider).

Other providers work too; just change the SMTP host/port:

| Provider | EMAIL_SMTP_HOST | EMAIL_SMTP_PORT |
|----------|-----------------|-----------------|
| Gmail | smtp.gmail.com | 587 |
| Outlook/Hotmail | smtp-mail.outlook.com | 587 |
| Yahoo | smtp.mail.yahoo.com | 465 |

---

## Step 2 — Configure

1. Install Python 3.10+ and dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Edit **`config.py`** → put your tickers in `WATCHLIST` (Yahoo symbols, e.g.
   `AAPL`, `BTC-USD`, `TEVA.TA`).
3. Copy `.env.example` to `.env` and fill in your `EMAIL_*` values.

---

## Step 3 — Run it

```bash
python run_alerts.py
```
You'll see each ticker's status in the console and get an email for any active
signal. Check the math any time, offline, with `python test_engine.py`.

Then pick **one** way to make it run automatically:

---

## Option A — Free cloud, computer can be off (GitHub Actions) ⭐ recommended

1. Create a free GitHub account and a **new repository**, then upload these files
   (or `git push`).
2. Repo → **Settings → Secrets and variables → Actions → New repository secret.**
   Add each one: `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_USER`,
   `EMAIL_PASSWORD`, `EMAIL_TO`.
3. The schedule in `.github/workflows/alerts.yml` runs Mon–Fri at **21:30 UTC**
   (~after US market close). Edit the `cron:` line for your market/timezone.
4. Test immediately: **Actions tab → stock-alerts → Run workflow.**

GitHub then scans your watchlist on schedule and emails you. Free for this kind
of light job, no credit card.

---

## Option B — Free cloud alternative (PythonAnywhere)

Good if you'd rather not use GitHub. The free tier includes one scheduled daily
task — perfect for a once-a-day daily-timeframe scan.

1. Sign up free at pythonanywhere.com.
2. **Files** tab → upload the project files (or open a Bash console and
   `git clone` your repo).
3. Bash console: `pip install --user -r requirements.txt`.
4. Set credentials: easiest is to create the `.env` file in the project folder
   (the script reads it automatically). Or set them in the task command.
5. **Tasks** tab → add a scheduled task with the command:
   ```
   cd ~/stock-alerts && python3 run_alerts.py
   ```
   Pick a daily UTC time after your market closes.

(Note: free PythonAnywhere accounts can only reach allow-listed sites; Yahoo
Finance `query1/query2.finance.yahoo.com` is normally reachable, but if a fetch
is blocked, use Option A instead.)

---

## Option C — Your own computer (cron / Task Scheduler)

- **Mac/Linux:** `crontab -e` then
  `30 16 * * 1-5 cd /path/to/stock-alerts && /usr/bin/python3 run_alerts.py`
- **Windows:** Task Scheduler → Create Basic Task → Daily → Program `python`,
  arguments `run_alerts.py`, "Start in" = the project folder.

Only runs while the machine is on.

---

## Settings you can tune (`config.py`)

- `WATCHLIST` — your tickers.
- `INTERVAL` — `"1d"` (recommended; your script is built around SMA200). Intraday
  like `"1h"`/`"15m"` works but set `PERIOD="60d"` (Yahoo limits intraday history).
- `ALERT_ON` — which signals email you. Remove ones you don't care about.
- `CONFIRM_ON_CLOSED_BAR` — `True` evaluates the last *closed* bar so alerts
  don't flicker mid-bar (matches TradingView "Once Per Bar Close").

---

## Important notes

- **Daily signals fire on bar close.** With `INTERVAL="1d"`, run the scan once
  after your market closes — that's the free equivalent of a daily alert. For
  intraday, schedule it to run every 15–60 min during market hours.
- **Data source differences.** Yahoo data is split/dividend-adjusted by default
  (`AUTO_ADJUST=True`), so values can differ slightly from a TradingView chart
  with adjustment off. Set `AUTO_ADJUST=False` for a closer match to an
  unadjusted chart.
- **Gmail "less secure app" errors** almost always mean you used your normal
  password instead of an App Password, or 2-Step Verification isn't on.
- **This is not financial advice.** It's an automation of your own indicator.
  Always confirm before trading.
