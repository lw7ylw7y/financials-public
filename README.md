# Investment Dashboard

A single-user tool for watching the economy and a stock watchlist: a scheduled email digest of macro indicators with AI commentary, a private web dashboard, and a screener for small and mid-cap tech stocks.

## What it does

- **Digest email:** ten macro indicators from FRED, a computed improving/mixed/weakening read for each of the leading, coincident and lagging groups, explained by AI, a table with trends, and a countdown to the next releases. Sent as a weekly rollup when something has meaningfully changed.
- **Indicator Digest page** (`/`): the same content on demand, refreshed in the background.
- **Ticker Dashboard** (`/tickers`): a watchlist grouped by asset type with price, 52-week range and fundamentals from Finnhub, market news, and a computed Discount / Fair / Overpriced verdict for each ticker and group, shown as hoverable pills.
- **Small and Mid-Cap Tech Screener:** a nightly job that finds and scores small and mid-cap tech stocks from SEC EDGAR and Finnhub data. Its review page (`/screener`) lists the ranked candidates with live prices, and lets you shortlist, dismiss and annotate them.

## Quick start

**Requirements:** Python 3.12 or newer, and accounts for Upstash Redis (required everywhere), FRED, Finnhub, Gemini and Gmail for the features that use them.

```text
pip install -r requirements.txt
# create .env with the variables from Configuration, the sign-in ones included (quote values containing | or spaces)
set -a && source .env && set +a
python3 src/web/app.py         # then open http://127.0.0.1:5000/
```

The web app binds to the loopback address only. To sign in locally, add `http://127.0.0.1:5000/auth/callback` as an authorized redirect URI on the Google OAuth client. If port 5000 is still held by an earlier run, stop that process before starting a new one.

**Run the tests** (offline, no environment variables needed):

```text
python3 -m unittest discover -s tests -v
```

## Configuration

Names only; keep values in `.env` locally, in the hosting dashboard, and in GitHub Actions secrets.

| Setting | Required for | Set in | If missing |
|---|---|---|---|
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | everything (all state lives in Redis) | local, hosting, Actions | a `KvStoreError` on first use |
| `FRED_API_KEY` | indicator ingestion, including the hosted page's live check | local, hosting, Actions | ingestion fails |
| `GEMINI_API_KEY` | AI commentary | local, hosting, Actions | the computed read is shown without commentary |
| `GEMINI_FALLBACK_MODELS` | optional comma-separated fallback models | local, hosting | built-in defaults |
| `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL` | sending the digest | local, Actions | no email is sent |
| `FINNHUB_API_KEY` | Ticker Dashboard, screener job | local, hosting, Actions | tickers fall back to cached data or an error row; the job fails |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAIL`, `SECRET_KEY` | Google sign-in; required to run the web app, locally too | hosting | with any of them unset, every route returns 503 |
| `SEC_CONTACT` | screener job (your name and email, sent to the SEC as the User-Agent) | local, Actions | the job refuses to run |
| `SCREENER_NIGHTLY_CALL_CAP` | optional cap on Finnhub calls per screener run | local, Actions (repository variable) | 1500 |

Each setting's behavior is described in [the technical design](docs/v2_technical_design.md) (Sections 11.2, 11.5 and 11.17).

## Automation

| Job | Runs | What it does | Run it by hand |
|---|---|---|---|
| Indicator Check (`.github/workflows/indicator-check.yml`) | every 6 hours (UTC) | pulls FRED data, refreshes the release calendar and the AI take, sends the digest when due | `python3 src/main.py`, or dispatch the workflow |
| Screener Refresh (`.github/workflows/screener.yml`) | daily at 05:30 UTC | classifies new symbols, refreshes a candidate after its company reports (about every 90 days when no report date is known), builds candidate records | `python3 src/screener/job.py`, or `gh workflow run "Screener Refresh"` |
| Backfill | once, if history is sparse | seeds indicator history from FRED; safe to repeat | `python3 src/backfill.py` |
| Seed reads | once, after the first deploy of the history chart | replays the reads since 1978 into Redis for the chart (writes only months with no entry; safe to repeat) | `python3 src/seed_reads.py` |
| Backtest | by hand, when a rule changes | reads FRED only, replays the indicator reads against NBER recessions since 1978 and writes a Markdown report (about 12 seconds) | `python3 src/backtest.py report.md` |

The screener's first runs are long (about 4,700 EDGAR lookups and a Finnhub call per tech symbol), so run it in CI. It stops at its Finnhub call cap or on a rate limit and the next night continues. Each run ends with a line of counts (`new`, `no_cik_rechecked`, `refreshed`, `new_candidates`, `dates_fetched`, `failed`, `stopped`, `finnhub_calls`) and saves them, with symbol totals, to the `screener_state` key in Redis. What each count means, and the sample measurements behind the thresholds, are in [the technical design](docs/v2_technical_design.md), Section 11.23.

### Periodic review of the screener list

The screener's shortlisted and dismissed names go stale as companies report. The Next Earnings column shows when each reports, and a name marked "Review due" has filed a new report since it was last reviewed. Re-check the list by asking Claude Code to do the periodic review, about every 90 days, at the pace of the quarterly reports. The method and the data it relies on are in [the technical design](docs/v2_technical_design.md), Section 11.23.

## Project layout

```text
src/fred/       FRED client and the indicator list
src/storage/    indicator history in Redis
src/digest/     digest content, AI explanation, computed market read, email-send rules
src/mailer/     email rendering and sending
src/web/        Flask app, page rendering, Finnhub and Redis clients, ticker dashboard
src/screener/   EDGAR client, scoring, storage, live quotes and the nightly job
src/main.py     scheduled ingestion and digest entry point
tests/          offline unit tests
docs/           requirements, stories, design, UX
```

## Documentation

- [Requirements](docs/investment_dashboard_requirements.md): what the product must do.
- [v2 stories and tasks](docs/v2_user_stories.md): scope, acceptance criteria, tasks and status, including the screener.
- [v2 technical design](docs/v2_technical_design.md): how the web dashboard and screener work and why.
- [v1 stories](docs/v1_user_stories.md), [design](docs/v1_technical_design.md) and [tasks](docs/v1_task_breakdown.md): the digest email.
- [UX design](docs/ux_design.md): screens, behavior and mockups (`docs/ux_mockups/`).

## Deployment and operations

The web app runs on Render and redeploys on every push to `main`. Its start command is `gunicorn --chdir src/web app:app -b 0.0.0.0:$PORT --timeout 80 --worker-class gthread --threads 8` (the `--timeout` value does not matter under `gthread`). After changing an environment variable in Render, use "Save and Redeploy"; the service keeps its old environment otherwise. The scheduled jobs run in GitHub Actions and read the same Redis.

## Status and limits

The digest email, both web pages and the screener's scoring and nightly job are built; the screener's review page is built; its triage (shortlist, dismiss, notes) and filter settings are built. The settings and their defaults are in [the technical design](docs/v2_technical_design.md), Section 11.23. The Finnhub free tier has no fund-level P/E or PEG, and the Gemini free tier allows about 20 requests a day, used by the digest alone.
