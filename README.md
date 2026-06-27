# personal-stock-alerter (v2)

A confluence-based buy/sell signal system for a stock watchlist, built for a
**monthly capital-deployment** plan: each month you add cash, then deploy it only
when high-quality technical opportunities appear — and you get email alerts for
buys, sells, trims, and stop/trailing-stop risk events. Includes an honest,
event-driven **backtester** so you can validate the rules before trusting them.

> **Not financial advice.** This is an educational automation of technical rules.
> It is not optimized for win rate alone, makes no performance guarantees, and can
> lose money. You make every actual trading decision.

---

## 1. What changed from v1 (and why)

v1 was a single daily indicator (ported from a Pine script) that emailed alerts on
a fixed schedule. It worked, but as an *investment system* it had real gaps:

| Area | v1 weakness | v2 fix |
|------|-------------|--------|
| Architecture | Indicator + signal + alert logic interleaved in a few scripts | Clean package: `indicators` → `features` → `regime`/`signals` → `portfolio`/`backtest` → `alerts` |
| Validation | **No backtest at all** — rules were never tested on history | Event-driven backtester with no-lookahead execution, costs, and proper metrics |
| Trend safety | Could fire buys with no market-regime context | Hard 200-day trend filter + SPY regime gate (no buying into broad downtrends) |
| Risk | No stops, no sizing, no exposure limits | ATR stops, trailing stops, risk-based sizing, max position/exposure, cash buffer |
| Capital plan | No notion of monthly cash or ranking opportunities | Monthly contributions, score-ranked deployment, keep cash if nothing qualifies |
| Explainability | "STRONG BUY" with little context | Every signal carries score, reasons, indicators, risk level, stop, size, invalidation |
| Testing | One synthetic smoke test | 19 tests incl. a no-lookahead guard and edge cases |
| Types/docs | Minimal | Type hints, dataclasses, docstrings, logging, error handling throughout |

Nothing from v1 was deleted destructively — it was reorganized and extended.

---

## 2. Strategy research summary (evidence, not hype)

The design borrows from four well-documented strategy families. None is a "highest
success rate" winner; each trades off return, drawdown, and robustness differently.

- **Trend-following (200-day / 10-month rule).** Faber's *A Quantitative Approach
  to Tactical Asset Allocation* (2007) showed a simple "hold above the 10-month SMA,
  go to cash below it" rule historically delivered roughly equity-like returns with
  much smaller drawdowns, by sidestepping the worst of bear markets. The catch:
  it whipsaws in choppy markets and **underperforms buy-and-hold in strong bull
  runs**. → We use the 200-day SMA as a hard buy filter and a regime gate.

- **Cross-sectional momentum.** Jegadeesh & Titman (1993) documented that past
  3–12-month winners keep outperforming past losers by ~1%/month, an effect later
  shown to be robust across markets and asset classes (Asness et al., 2013). The
  catch: **momentum crashes** — sharp reversals during turning points. → We reward
  positive 6-month momentum and breakouts, but cap chasing via RSI/extension penalties.

- **Absolute / dual momentum.** Antonacci's Global Equities Momentum combines
  relative strength with an absolute-momentum "risk-off to bonds" switch. Reported
  long-run results show reduced drawdowns vs. buy-and-hold, but with meaningful
  **model-specification fragility** (a 9- vs 10-month lookback can change results a
  lot) and whipsaws. → We treat regime as a gate, not a precise timer, and avoid
  over-tuning lookbacks.

- **Short-term mean reversion (Connors RSI-2, "buy dips above the 200-day").**
  Connors showed buying short-term oversold dips *within* an uptrend historically
  had a high hit rate; later work found the **edge decayed after publication** and
  that the no-stop original is risky. → We use "pullback to a rising MA" and
  "RSI recovering from oversold" as *entry-timing* confirmations layered on top of
  the trend filter — and we **do** use stops, unlike the original.

**Best fit for your goal (monthly deployment, wait for quality, manage risk):** a
*trend-filtered, momentum-confirmed pullback entry* with explicit risk management.
That's what the signal engine implements: only buy in confirmed uptrends, prefer
buying pullbacks/oversold-recoveries rather than chasing, confirm with momentum and
volume, size by risk, and exit on trend breaks or stops. It deliberately favors
**robustness and drawdown control over raw win rate.**

---

## 3. Architecture

```
                 ┌────────────┐
   Yahoo data →  │  data.py   │  load OHLCV (or synthetic for offline tests)
                 └─────┬──────┘
                       ▼
                 ┌────────────┐
                 │ features.py│  one shared indicator set (no lookahead)
                 └─────┬──────┘
            ┌──────────┴───────────┐
            ▼                      ▼
     ┌────────────┐         ┌────────────┐
     │ regime.py  │         │ signals.py │  confluence score → tier + reasons
     │ (SPY gate) │         │  + sizing  │  + stop + position size + invalidation
     └─────┬──────┘         └─────┬──────┘
           └──────────┬───────────┘
                      ▼
         ┌─────────────────────────┐
         │       portfolio.py      │  cash, positions, costs, stops, trailing
         └───────┬─────────────┬───┘
                 ▼             ▼
         ┌────────────┐  ┌────────────┐
         │ backtest.py│  │  alerts.py │  email digest + dedup state
         │ (validate) │  │  (act now) │
         └────────────┘  └────────────┘
                 ▲             ▲
        run_backtest.py   run_alerts.py     ← entry points
```

- **Signal flow (live):** load → features → regime → per-symbol signal on the last
  *closed* bar → filter by tier → dedup → email.
- **Backtest flow:** features for all symbols → daily loop where a signal from the
  close of day *t-1* executes at the **open of day *t***; stops monitored on day
  *t*'s range; monthly cash added at month starts; metrics computed on a
  time-weighted return index (contributions stripped out).

---

## 4. Install & quick start

```bash
pip install -r requirements.txt

python run_tests.py            # 19 tests, no pytest required (~seconds)
python run_backtest.py --synthetic   # offline sanity run, no network
python run_backtest.py         # real backtest on the configured watchlist (Yahoo)
python run_alerts.py --dry-run # scan and print signals without emailing
```

Email setup (for real alerts): copy `.env.example` to `.env`, fill in your SMTP
details (Gmail needs a 16-char **App Password** with 2-Step Verification on), then
`python run_alerts.py --test-email` to confirm delivery.

Cloud schedule (computer off): push to GitHub, add the `EMAIL_*` values as
**Settings → Secrets and variables → Actions**, and the included workflow scans
every 30 min during US market hours. Trigger a test from the Actions tab with the
"Send a TEST email" checkbox.

---

## 5. Configure your plan

Edit `stock_alerter/config.py` (all typed dataclasses):

- **Watchlist:** `Config.watchlist` (Yahoo symbols, e.g. `AAPL`, `BTC-USD`, `TEVA.TA`).
- **Monthly amount:** `Config.monthly_contribution` (cash added each month start).
- **Risk:** `RiskParams` — `risk_per_trade_pct`, `atr_stop_mult`, `atr_trail_mult`,
  `max_position_pct`, `max_portfolio_exposure_pct`, `max_open_positions`,
  `min_cash_buffer_pct`.
- **Costs (backtest realism):** `CostParams` — `slippage_pct`, commissions.
- **Signal thresholds:** `StrategyParams` — score cutoffs and indicator periods.
- **Alerting:** `alert_min_tier` (`STRONG_BUY`/`BUY`/`WATCH`), `confirm_on_closed_bar`.

---

## 6. How to read a signal

Each alert is a tier plus a 0–100 confidence score and full context:

| Tier | Meaning | Typical action (your call) |
|------|---------|----------------------------|
| `STRONG_BUY` | High-confluence entry in a confirmed uptrend | Deploy a full risk-sized position |
| `BUY` | Solid entry, fewer confirmations | Deploy, perhaps smaller |
| `WATCH` | Setup forming or held back by regime | No trade yet; monitor |
| `HOLD` | No edge | Do nothing |
| `TRIM` | Overbought + weakening momentum | Consider taking partial profit |
| `SELL` | Trend deteriorating (MA/MACD) | Consider exiting |
| `STRONG_SELL` | Long-term trend broken (below 200-day) | Exit / risk-off |

Also included: **reasons** (why it fired), **indicator values**, **risk level**
(from ATR volatility), **suggested stop** (ATR-based), **suggested size** (risk-based,
capped by your limits and cash), and the **invalidation condition** (what would prove
the idea wrong).

---

## 7. Monthly deployment logic

At each month start the system adds your contribution to cash. It does **not** force
investment. On each scan it ranks qualifying buys by score and deploys to the best
ones while respecting max position size, max open positions, total exposure, and a
minimum cash buffer — so leftover cash simply waits for better setups. In a bearish
regime, buys are withheld entirely.

---

## 8. Backtest integrity (what's handled, what isn't)

Handled: no-lookahead execution (signal at *t-1* close → fill at *t* open), ATR stops
with conservative gap-through fills, slippage + optional commissions, monthly cash
flows removed from return calculations (time-weighted returns), and a full metric set
(CAGR, vol, Sharpe, Sortino, max drawdown, Calmar, exposure, win rate, profit factor).

**Not** fully handled — be aware:
- **Survivorship bias:** the watchlist is fixed and chosen today. A true point-in-time
  universe needs a paid survivorship-bias-free dataset (e.g. CRSP, Norgate, Sharadar).
  Yahoo cannot provide this. Treat single-name backtests as indicative, not proof.
- **Overfitting:** defaults are deliberately conventional. If you tune parameters to
  maximize past returns, you are curve-fitting. Prefer out-of-sample checks.
- **Data quality:** Yahoo has occasional gaps/late revisions and ~60-day intraday
  history caps. Use daily bars for this system.
- **Order realism:** fills assume you can transact at the open/stop; real fills vary.

---

## 9. Tests

```bash
python run_tests.py     # or: pytest -q
```

Covers each indicator, a **no-lookahead guard** (feature values don't change when
future bars are appended), buy-requires-uptrend, regime gating, risk-based sizing,
portfolio cost/stop mechanics, metric correctness, and edge cases (insufficient
history, missing columns, NaN gaps).

---

## 10. Limitations & honest warnings

- Backtested/synthetic results are not predictions; live results will differ.
- The system can and will have losing streaks and drawdowns; the trend filter
  reduces but does not eliminate them and will whipsaw in choppy markets.
- Daily signals confirm on bar close; intraday "buy now" timing reads the unconfirmed
  bar and can change before close.
- This is software, not advice. Verify every signal yourself before acting.
