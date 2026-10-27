# V2 User Stories, Acceptance Criteria & Tasks — Web Dashboard

**Companion to:** investment_dashboard_requirements.md, v2_technical_design.md
**Scope:** Section 4 of the requirements doc (Indicator Digest Page, Ticker Dashboard)

v2 is two web pages: a read-only Indicator Digest Page (mirrors the v1 email) and the Ticker Dashboard. Ticker Email Alerts and Discount-Buy Thresholds are backlog items (Section 5 of the requirements doc), not covered here.

---

## Foundation and Integration Tasks (not tied to one story)
- [x] F.1 `requirements.txt` and venv: `flask`
- [x] F.2 `src/web/app.py`: Flask scaffold, route registration, explicit `host="127.0.0.1"` binding
- [x] F.3 `run_web.sh`: convenience start script
- [x] F.4 `static/dashboard.css`: shared styling for both pages
- [x] F.5 Verified the running app is unreachable from another device on the same network (manual)
- [x] I.1 `FINNHUB_API_KEY` in the local `.env`, read via `os.environ.get`
- [x] I.2 Manual end-to-end run of `/`: instant render, then the background check patches sections or clears the indicator
- [x] I.3 Manual end-to-end run of `/tickers` with the real watchlist; the per-row error state confirmed with a broken symbol
- [x] I.4 The state's diff after a background check was limited to the expected fields

---

## Epic: Indicator Digest Page

### Story 1 — On-Demand Indicator Page
**As** the investor, **I want** to open a web page and see the same macro-indicator content the digest email already sends me, **so that** I can check the current picture whenever I want instead of waiting for the next triggering email.

**Acceptance Criteria**
- [x] Page runs locally (e.g. `localhost`) — no public hosting, no domain, no login needed (hosted/non-local is a backlog item)
- [x] Page displays the same three content pieces as the digest email: the holistic AI interpretation + a read per indicator group (one overall read until Story 31), the indicator table grouped by category, and the next-release countdown
- [x] AI-generated content is labeled as informational commentary, not personalized financial advice
- [x] If the AI interpretation is missing or failed on the most recent ingestion/live-pull run, the page still renders the table and countdown
- [x] The email digest continues to fire on its existing trigger, unchanged by the page's existence

**Tasks**
- [x] P.1 Extract the table/countdown/AI-assembly logic into `digest/build_digest_content.py`, returning `{table, countdown, ai_result}`
- [x] P.2 `post_release.py` calls the extracted function; throttle and email-send logic unchanged
- [x] P.3 Regression tests: the weekly email's content is byte-for-byte equivalent to the pre-refactor output
- [x] 1.3 `page_template.py`: AI section, table (grouped Leading/Coincident/Lagging, each row with an inline-SVG sparkline; a single-point history renders as a dot), countdown, disclaimer, "Checking for updates..." indicator
- [x] 1.4 `/` and `/api/check` wiring in `app.py`

### Story 1a — Background Live Check with In-Place Updates
**As** the investor, **I want** the page to load instantly from the last stored data and check for anything new in the background, updating only what's actually changed, **so that** I'm not staring at a spinner every time I open the page, and the AI isn't re-run for no reason when nothing's changed.

**Acceptance Criteria**
- [x] The page's initial load is built entirely from stored data — no live fetch blocks the response
- [x] After the initial render, the page checks for updates on its own — a live pull from FRED
- [x] If the check finds at least one indicator with a genuinely new value, the affected parts of the page (table, countdown, AI section) update in place, and the AI interpretation is re-run and shown
- [x] If the check finds nothing new, the page is left exactly as it was — no re-render, and **no AI call is made**
- [x] A check that finds new data writes it back to the shared historical data store, so the page and email stay consistent
- [x] If the background check fails outright, the page simply stays on the last stored data
- [x] The fallback/initial state includes the last successful AI summary/directional read, not just the indicator table — requires persisting the most recent AI response (text + computed reads + generated-at timestamp; a single directional read until Story 31) to the data store
- [x] While the background check is in flight, the page shows a visible "checking for updates" indicator; it disappears once the check settles, regardless of outcome

**Tasks**
- [x] A.1 `last_ai_response` field in the state schema, absent until the first write (no migration)
- [x] A.2 `build_digest_content.py` persists `{summary, computed_reads, generated_at, as_of}` on every successful Gemini call (`{summary, directional_read, generated_at}` until Story 31), on both the email and live-pull paths; a failed call leaves the previous value untouched
- [x] 1.1 `live_pull.py`: `get_initial_page_data()` (stored data only) and `check_for_updates()` (gated live pull)
- [x] 1.2 Independent freshness per section: the table and countdown update while the AI section stays on the last `last_ai_response` if only Gemini fails

---

## Epic: Ticker Dashboard

### Story 2 — Ticker Watchlist Configuration
**As** the investor, **I want** to maintain my ticker watchlist — and the groups it's organized into — in a simple config file, **so that** I can add, remove, or regroup tickers without touching application code.

**Acceptance Criteria**
- [x] Tickers are defined in a local JSON config file (Section 7 of the requirements doc), grouped under group names defined by the file itself — not a fixed list hardcoded in the app
- [x] Initial watchlist matches the config draft: broad stock ETFs (stocks); bond ETFs (bonds); international ETFs (international); sector ETFs (sector); trusted individual stocks (individual)
- [x] Adding or removing a ticker requires only editing the config file — no code change
- [x] Adding, removing, or renaming an entire group requires only editing the config file — no code change
- [x] An invalid or unrecognized ticker symbol in the config is skipped with a logged warning rather than breaking the whole dashboard

**Tasks**
- [x] 2.1 Watchlist config with `sector` and `individual` as separate groups (the file was later replaced by the `ticker_config` Redis hash, Story 13)
- [x] 2.2 Config loader in `ticker_dashboard.py` reads `groups` as an open map in file order; no group name hardcoded
- [x] 2.3 Symbol format validation: a malformed entry is skipped with a logged warning

---

### Story 3 — Ticker Dashboard Page
**As** the investor, **I want** a web page showing my ticker watchlist grouped by asset type, **so that** I can review prices and trends across all my holdings in one place without logging into a brokerage.

**Acceptance Criteria**
- [x] Page runs locally (e.g. `localhost`) — no public hosting, no domain, no login needed
- [x] Tickers are displayed grouped under headers matching the group names in the config file exactly
- [x] Each ticker row shows: current price and 52-week range
- [x] The 52-week range is shown as a green (near the low)→amber→red (near the high) gradient with a marker for the current price, plus the low/high as text, so the read doesn't depend on color alone
- [x] Price data is sourced from Finnhub (Section 6 of the requirements doc); the free-tier ~20-minute delay is acceptable and does not need to be surfaced as an error state
- [x] A ticker whose data fails to load, and has never been successfully fetched before, shows a visible per-row error state rather than breaking the rest of the dashboard
- [x] The page's initial paint shows the last cached snapshot instantly, with a background check re-fetching live moments later (Story 5)
- [x] **Percent off 52-week high** — its own column, computed from price + the existing 52-week range, no new data source
- [x] **Change since last close** — its own column, current session's absolute and % move versus the previous close, colored green-up/red-down
- **Removed (2026-09-16):** the 20-day/50-day/200-day moving-average columns (and the Yahoo Finance daily-close fetch they depended on) were dropped from the table and from `ticker_cache`'s stored snapshot shape — not replaced by anything
- [x] **Sortable columns** — the Ticker and % in Range column headers are clickable and sort that group's table (ascending, then descending on a second click); pending/errored rows always sort last regardless of direction; sorting is independent per group table
- [x] **Market Cap** and **P/E (trailing)** — their own columns, sourced from the same Finnhub call already used for the 52-week range (no new fetch); either renders "n/a" rather than erroring the row when Finnhub has no value for that symbol
- **Added (2026-09-17):** Finnhub never has a P/E for a fund, so the equity-ETF groups (`stocks`, `international`, `sector`) additionally fall back to Yahoo's aggregate-holdings P/E when Finnhub's own is empty — best-effort against an undocumented, unofficial Yahoo endpoint; a failure there degrades to "n/a" like any other missing value, never an error
- [x] **PEG ratio** — its own column (2026-09-17), sourced from the same Finnhub call as P/E (`pegTTM`, falling back to `forwardPEG`); no Yahoo fallback exists for it, so it's only ever populated for individual stocks — every ETF's PEG renders "n/a"

**Tasks**
- [x] 3.1 `finnhub_client.py`: quote endpoint
- [x] 3.2 `fetch_stock_metrics`: 52-week range, market cap and P/E from `/stock/metric`
- [ ] ~~3.3 20/50/200-day moving averages from Yahoo daily closes~~ removed 2026-09-16, not replaced
- [x] 3.4 `ticker_dashboard.py`: per-ticker assembly with an independent try/except per ticker
- [x] 3.5 `page_template.py`: grouped tables, per-row error state
- [x] 3.6 `/tickers` wiring in `app.py`
- [x] 3.7 `pct_off_high` computed from the price and the 52-week high, no new fetch
- [x] 3.8 `fetch_quote()` also parses `d`/`dp`
- [x] 3.9 % Off High and Change columns, with the signed value plus arrow convention
- [x] 3.10 Market Cap and P/E columns, "n/a" when Finnhub has no value
- [ ] ~~3.11 ETF aggregate P/E fallback via Yahoo `quoteSummary` (Section 11.11)~~ removed 2026-09-18 with `yahoo_client.py`: the endpoint needed a crumb and its only consumer was already hidden for every group but `individual`
- [x] 3.12 PEG column from the same `/stock/metric` call (`pegTTM`, falling back to `forwardPEG`); ETFs always show "n/a" (Section 11.12)
- [x] 3.13 Growth/quality stats and a sector-peer P/E benchmark (`fetch_company_industry`, `_SECTOR_ETF_BY_INDUSTRY`), data only, no new columns (Section 11.13)

---

### Story 4 — Cross-Page Navigation
**As** the investor, **I want** to get from one v2 page to the other by clicking rather than typing a URL, **so that** the two pages feel like one dashboard rather than two disconnected tools.

**Acceptance Criteria**
- [x] Both the Indicator Digest Page and the Ticker Dashboard show a small nav linking to the other page
- [x] The nav visibly marks which page is currently active

**Tasks**
- [x] 4.1 Shared `_render_nav(active_path)` on both pages

---

### Story 5 — Ticker Dashboard: Instant Load with Background Refresh
**As** the investor, **I want** the Ticker Dashboard to load instantly from the last known prices and refresh live in the background, **so that** I'm not staring at a blank page while dozens of tickers' worth of Finnhub calls complete one by one.

**Acceptance Criteria**
- [x] The page's initial load is built entirely from a local snapshot cache (`data/tickers.json`, one entry per ticker) — no live fetch blocks the response, same pattern as the Indicator Digest Page
- [x] A ticker with no cached snapshot yet renders as a "Loading…" placeholder row, not an error
- [x] After the initial render, the page checks for live data on its own; unlike the Indicator Digest Page there's no "skip if nothing changed" gate — every check re-fetches every ticker live
- [x] A successful live fetch for a ticker is persisted to the snapshot cache
- [x] A ticker whose live fetch fails falls back to its last cached snapshot, flagged as saved (Story 36); only a ticker with no cached snapshot *and* a failed live fetch shows the error state
- [x] While the background check is in flight, the page shows the same visible "checking for updates" indicator as the Indicator Digest Page

**Tasks**
- [x] 5.1 Snapshot cache with the `get_initial_ticker_page_data()` / `check_for_ticker_updates()` split (the cache is now the `ticker_cache` Redis hash, Stories 12-13)
- [x] 5.2 `/api/check-tickers` route (replaced by per-group routes in Story 12)
- [x] 5.3 Concurrent fetch via `ThreadPoolExecutor` (`max_workers=5`); a test forces out-of-order completion and asserts group/row order holds

---

### Story 6 — US Stock Market News
**As** the investor, **I want** to see general market headlines at the top of the Ticker Dashboard, **so that** I know what's moving the market before I look at individual ticker prices.

**Acceptance Criteria**
- [x] A short feed of general US stock market news is shown once, at the top of the page, above the grouped ticker tables — not per-ticker
- [x] Sourced from Finnhub's general-news endpoint (Section 6 of the requirements doc), filtered to Finnhub's own `"top news"` category tag
- [x] Follows the same instant-load-then-background-refresh pattern as the rest of the page (Story 5): rides along in the same `/api/check-tickers` round trip, with its own cache file (`data/market_news.json`)
- [x] A failure to load market news degrades gracefully (the section is empty or shows a muted "unavailable" state) rather than breaking the rest of the page

**Tasks**
- [x] 6.1 `finnhub_client.fetch_market_news()`: general-news endpoint filtered to `"top news"`
- [x] 6.2 Folded into the ticker check with its own cache (now the `market_news_cache` key; its own route since Story 12)
- [x] 6.3 `page_template.py`: market-news section at the top of the Ticker Dashboard

---

### Story 7 — In-App Ticker Editing
**As** the investor, **I want** to add or remove a ticker from within an existing group right on the Ticker Dashboard, **so that** I don't have to open the config file for a routine watchlist change.

**Acceptance Criteria**
- [x] Each ticker row has a remove control, placed as the row's trailing column rather than beside the ticker symbol; each group has an add-ticker field. Both write straight to `config/tickers.json`
- [x] Adding or removing a whole group is still a hand-edit of the file — out of scope here
- [x] An invalid symbol or unknown group is rejected with an error, not silently accepted
- [x] Neither page requires user authentication

**Tasks**
- [x] 7.1 `add_ticker_to_group` / `remove_ticker_from_group` (now one hash field per group, Story 12)
- [x] 7.2 `/api/tickers/add` and `/remove` routes, 400 on rejection
- [x] 7.3 `page_template.py`: remove button in each row's trailing cell, add-ticker form per group, event-delegated JS

---

## Epic: Hosted Live Dashboard (v2.1)

### Story 8 — Google Sign-In-Protected Public Hosting
**As** the investor, **I want** both dashboard pages reachable from anywhere behind my Google account, **so that** I can check them without needing my own laptop running, while keeping them private to me.

**Acceptance Criteria**
- [x] Both pages are served from a single hosted web service reachable over the public internet — no VPN, tunnel, or laptop required
- [x] Every route requires signing in with Google before rendering any content; there is no page reachable without authenticating. A logged-out page visit redirects to Google's sign-in; a logged-out `/api/*` call gets a 401
- [x] Only the one Google account named by `ALLOWED_EMAIL` (with a verified email) is let in; any other Google account gets a 403
- [x] Credentials (`GOOGLE_CLIENT_ID`/`SECRET`, `ALLOWED_EMAIL`, `SECRET_KEY`) are configured via environment variables on the host, never hardcoded or committed to the repo
- [x] The sign-in flow guards against forged callbacks (a per-request `state` value, single-use) and, once enabled, fails closed (503) if any required setting is missing
- [x] Traffic is served over HTTPS (provided by the host)
- [x] Local development is unaffected — running `src/web/app.py` locally with `GOOGLE_CLIENT_ID` unset behaves exactly as it does today, with no sign-in

**Tasks**
- [x] H.1 `gunicorn` in `requirements.txt`; no entry-point shim needed (`gunicorn --chdir src/web app:app`, Section 11.5)
- [x] H.2 `app.py` auth `before_request` hook gated on `GOOGLE_CLIENT_ID` (`google_auth.py`, `/login`, `/auth/callback`, `/logout`; replaced an earlier HTTP Basic Auth gate)
- [x] H.6 Render service created, GitHub repo connected, auto-deploy on push to `main`, env vars set, auth confirmed over HTTPS (env var edits need an explicit "Save and Redeploy", Section 11.5)
- [x] Verified live: hosted `/` and `/tickers` require sign-in before rendering anything; wrong credentials are rejected

**Tests:** `tests/test_app.py` and `tests/test_google_auth.py` cover the redirect and 401, the forged, missing or replayed `state`, a missing code, an unverified or wrong email, a partial configuration (503) and unauthenticated access with `GOOGLE_CLIENT_ID` unset.

---

### Story 9 — Durable Ticker Config & Caches on a Host With No Persistent Disk
**As** the investor, **I want** my watchlist edits and cached prices to survive a restart of the hosted app, **so that** the in-app ticker editor and the instant-load caches keep working the same way they do when run locally.

**Acceptance Criteria**
- [x] When a Redis connection is configured (hosted deployment), `config/tickers.json`'s content, `data/tickers.json`'s cache, and `data/market_news.json`'s cache are all read from and written to Redis instead of local files
- [x] When no Redis connection is configured (local development), behavior is unchanged — the same local JSON files are used as today (verified: the full pre-existing test suite passes unmodified with no Redis env vars set)
- [x] On first read with nothing yet in Redis, the ticker config is seeded from the repo's committed `config/tickers.json`, so a fresh deploy starts with the existing watchlist rather than an empty one
- [x] Adding or removing a ticker through the in-app editor on the hosted deployment persists in Redis and survives a container restart — verified live that a hosted removal updates the `ticker_config` key in Upstash; an explicit restart-and-recheck was not separately performed
- [x] A Redis outage degrades gracefully: the ticker/news caches fall back to their existing "no cache yet" pending/error states rather than crashing the page; a failed ticker-config load fails loudly with a clear error rather than silently rendering an empty watchlist

**Tasks**
- [x] H.3 `src/web/kv_store.py`: Upstash REST wrapper (`get_json` / `set_json`), wire format confirmed against a real instance
- [x] H.4 `ticker_dashboard.py` config and cache load/save through `kv_store.py` (the local-file branch was removed in Story 13)
- [x] H.5 Seed-on-first-read of the ticker config from the committed file (removed in Story 13)
- [x] H.7 Tests: `tests/test_kv_store.py` (round trip; a non-200 raises) and `ticker_dashboard` tests for config and cache through a mocked Redis, including an outage in the cache (degrades) and the config (propagates)
- [x] Verified live: a hosted add/remove persists to `ticker_config` in Upstash

---

### Story 10 — Indicator Data Stays Git-Sourced When Hosted (superseded by Story 11)
Superseded by Story 11 before any of it was built: the hosted page reading indicator history from git was dropped because a visitor's fresher AI take was lost on restart.

---

### Story 11 — Durable, Consistent Indicator Data on a Host With No Persistent Disk
**As** the investor, **I want** the hosted Indicator Digest Page and the scheduled email pipeline to share one always-current copy of indicator data and its AI take, **so that** I never see a stale AI response just because the emailed digest is throttled to a weekly cadence.

**Acceptance Criteria**
- [x] Indicator state is read from and written to Redis (`indicator_state`, via `kv_store.py`), not a local file
- [x] The AI response is regenerated every ingestion cycle that finds at least one genuinely new indicator value — no longer gated on whether the weekly digest email is also about to send
- [x] The weekly digest email's send decision is based on a content fingerprint (has the digest's actual conclusion changed since the last email) plus the existing minimum-interval floor, rather than a raw "changed since last email" timestamp scan — so a week passing with no real change doesn't trigger a repeat email
- [x] A hosted visitor's live background check (`/api/check`) writes to the same Redis-backed state the scheduled Action uses, so its result is no longer discarded on the next container restart
- [x] A fresh or cleared Redis key starts as `{"indicators": {}}`; history is restored with `python3 src/backfill.py` (no automatic seed; Section 11.10)

**Verified:** `tests/test_storage.py`, `TestRefreshAiResponseIfUpdated` and `TestMaybeSendDigestEmail` (sends only when the fingerprint differs and the interval has elapsed; a failed send does not update the fingerprint). Live: `load_state` / `save_state` round-trip against the real Upstash instance, and a manual `workflow_dispatch` run against real Redis, FRED and Gmail sent a digest email. `indicator-check.yml` has no commit step and no `contents: write`.

---

### Story 12 — Ticker Dashboard: Per-Group Live Checks
**As** the investor, **I want** each ticker group (and market news) to refresh independently in the background, **so that** I'm not waiting on the entire ~36-ticker watchlist to finish before seeing anything update.

**Acceptance Criteria**
- [x] The ticker page's background script fires one live-check request per group (`/api/tickers/groups/<name>/check`) plus one for market news (`/api/market-news/check`), all concurrently, instead of one combined request
- [x] Each group's table repaints as soon as its own request resolves, independent of every other group's — a group with fewer tickers finishes and repaints before a slower one does
- [x] A failed per-group or market-news check falls back silently to that section's last cached/pending state, same as before, without affecting any other group
- [x] The shared ticker snapshot cache (`data/tickers.json`, or Redis when hosted) is safe against concurrent per-group writes — one group's check can't silently overwrite another's freshly-fetched values when both finish close together, at any concurrency level (no lock needed on the Redis path — see below)
- [x] Sorting and remove-ticker behavior are unchanged from the single-request design
- [x] The ticker cache is a Redis hash with one field per symbol and atomic per-field writes, not a lock around a whole-cache read-modify-write; the watchlist is a hash with one field per group, each with an explicit order index (design Sections 11.8, 11.9)
- [x] Adding a ticker shows it immediately as a new pending row in its group and re-checks just that group for real data, without reloading the whole page (superseding the original design's `window.location.reload()`)
- [x] `_require_auth` gates the new routes exactly as it does every other route

**Tests:** `test_page_template.py`, `test_app.py`, `test_kv_store.py`, `test_ticker_dashboard.py` cover the per-group routes and 404, the fragments, auth, the hash wire format, two snapshot writes landing as independent fields, and edits to two groups never touching each other's field.
**Manual:** all 5 groups (36 tickers) completed concurrently in 1.2-4.5s each against the real Upstash instance with no data loss in `ticker_cache`.

---

### Story 13 — Redis as the Only Source of Truth (no local-file fallback)
**As** the investor, **I want** the app to always read and write the same live Redis state, on my own machine or hosted, **so that** there's never a question of which copy — a stale committed file, or Redis's current state — is actually authoritative.

**Acceptance Criteria**
- [x] `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN` are required unconditionally, wherever the app runs — no local-file fallback exists anywhere for the watchlist, either cache, or indicator state
- [x] `config/tickers.json` and `data/indicators.json` are removed from the repo, since no code reads them anymore; `.gitignore`'s now-meaningless `data/tickers.json`/`data/market_news.json` entries are removed too
- [x] A wiped or brand-new Redis key comes back empty (an empty watchlist, or a "nothing cached/recorded yet" state) rather than crashing — recovering indicator history is `python3 src/backfill.py`'s job; recovering a wiped watchlist is re-adding tickers through the in-app editor. Neither is automatic, and that's an accepted tradeoff, not a gap
- [x] The now-unused process-local lock (`ticker_dashboard._ticker_state_lock`) is deleted along with the local-file code it existed to guard — every remaining write is either a single Redis key or an atomic per-field hash write, neither needing a lock

**Tests:** a write-then-reload round trip; a missing key initializes to `{"indicators": {}}`; a new entry never overwrites prior history across two save/load cycles; load/save failures propagate; config order restores from a scrambled hash; add/remove touch only their own field; a malformed symbol is skipped with a warning; the cache and news paths degrade to `{}` / `None` on an outage.

---

### Story 14 — Ticker Dashboard: AI Valuation Section
**Status:** superseded by Story 34: the AI section, `ticker_valuation.py`, the cache and the check route are gone; the computed verdicts it fell back to are now the only source, shown in the tables.

**As** the investor, **I want** an AI read on which of my tickers/groups look like a discount, fair value, or overpriced, **so that** I don't have to manually compare P/E, PEG, growth, and sector benchmarks myself for every row.

**Why:** the Market Cap/P/E/PEG columns (this doc's Section 4.2) and the sector-peer/growth-quality data gathered for it give the raw numbers, but reading them ticker-by-ticker to spot a value trap (a low P/E paired with shrinking revenue or high debt) is exactly the kind of synthesis an LLM is well-suited for, mirroring what `interpret.py` already does for the indicator digest.

**Acceptance Criteria**
- [x] One section at the top of `/tickers`, above market news: an overview paragraph plus a discount/fair/overpriced badge per ETF group, sorted most-attractive-first
- [x] Every ticker in the `individual` group gets its own discount/fair/overpriced verdict with a one-sentence reasoning, listed under three "Discount"/"Fair"/"Overpriced" headings (not one flat list) — an explicit requirement, not just whatever order the AI returns them in
- [x] One batched AI call reasons across the *entire* watchlist at once, not one call per ticker — confirmed live that gemini-3.8-flash's free tier caps at 20 requests/day total, shared with the indicator digest's own calls on the same model, making a per-ticker design unworkable
- [x] The AI is given the sector-peer P/E benchmark and growth/quality stats (revenue growth, EPS growth, ROE, margin, debt/equity) alongside P/E and PEG, and its system prompt explicitly instructs it to call out a low P/E backed by weak fundamentals as a value trap (superseded by Story 19: the value trap is decided in code and the prompt only explains it) rather than a genuine discount — confirmed live it does this (e.g. flagged INTC and QCOM as value traps despite low P/Es)
- [x] The valuation is cached (`ticker_valuation_cache`) and refreshes on a multi-hour throttle, not on every page load or background check — protecting the shared Gemini quota
- [x] Any AI failure, including a quota/rate-limit error, falls back to the last successfully cached valuation shown as-is, never an error state — confirmed live against a real `429 RESOURCE_EXHAUSTED` response. With nothing ever cached, degrades to a muted "not yet available" placeholder instead (superseded by Story 19: the fallback is the computed verdicts, with cached AI text kept only where its verdict still matches)
- [x] Has its own background-check route (`/api/tickers/valuation/check`), checked independently of any ticker group's or market news' own check, folded into the same "Checking for updates..." indicator

**Tasks**
- [x] 3.14 One batched Gemini call (`ticker_valuation.py`) judging each group and every individual stock, cached and throttled (`MIN_VALUATION_INTERVAL`) against the shared 20-requests/day quota (Section 11.14)

### Story 15 — AI Calls Fall Back Through Other Gemini Models
**Status:** built for the digest. The ticker valuation parts (its fallback chain, `VALUATION_FAILURE_COOLDOWN`) were removed by Story 34.

**As** the investor, **I want** the AI sections to keep working when the primary Gemini model is overloaded or out of quota, **so that** a single-model outage doesn't leave the digest and valuation sections empty.

**Why:** Gemini's free tier returned `503 UNAVAILABLE` almost continuously during a real incident, making both AI sections useless. Free-tier quota and serving capacity are tracked per model, and which models are overloaded shifts through the day (a newer model can be down while an older one answers), so a longer chain survives more spells.

**Acceptance Criteria**
- [x] When the primary Gemini call fails for any reason (API error, quota `429`, overload `503`, missing key, empty or unparseable response), the same prompt is retried on each fallback model in turn (`gemini-3.6-flash`, `gemini-3.5-flash-lite` by default; `GEMINI_FALLBACK_MODELS`, a comma-separated list, overrides it), using the same `GEMINI_API_KEY`
- [x] The first model to return a valid response wins; later models are never called
- [x] If every model fails, behavior is unchanged from before: the digest omits the AI section and the ticker valuation degrades to the last cached valuation (superseded by Story 19: the computed verdicts). The error names each model and its failure
- [x] Each model is called at most once per request (no retries)
- [x] After every model has failed, the ticker valuation's AI call isn't retried for 15 minutes (`VALUATION_FAILURE_COOLDOWN`), so a page load during an outage doesn't spend one request per model on the shared quota

**Tasks**
- [x] 15.1 `src/web/gemini_models.py`: the ordered default fallback list and `fallback_models()` (comma-separated `GEMINI_FALLBACK_MODELS` overrides it)
- [x] 15.2 `interpret.py` / `ticker_valuation.py`: a per-model helper and `_run_with_fallbacks`; an injected `client` runs alone; the error names every model and its failure (verified live: with three models returning `503`, `gemini-3.5-flash-lite` answered)
- [x] 15.3 `check_for_ticker_valuation`: `VALUATION_FAILURE_COOLDOWN` (15 min, process memory) after a total failure
- [x] 15.4 Tests: `test_gemini_models.py`, `TestGeminiModelFallbackChain` in `test_interpret.py` and `test_ticker_valuation.py`, and the cooldown tests in `test_ticker_dashboard.py`
- [ ] ~~15.5 Further fallback providers (GitHub Models, Claude via the Anthropic API)~~ dropped: `models.github.ai` returned a bare `HTTP 200 text/plain OK` on every path, and the Anthropic API needs separately billed credits

### Story 16 — A Failed AI Call Is Retried, Not Left Stale
**As** the investor, **I want** the indicator digest's AI take to be regenerated after a failed attempt, **so that** a Gemini outage at the moment new data arrived doesn't leave an outdated take on the page until the next release, weeks later.

**Why:** the AI call used to happen only in the same run that found new data. If every model failed then, the new values were saved, the old take stayed, and no later check had a reason to try again.

**Acceptance Criteria**
- [x] Each saved AI take records which reading of each indicator it covers (`as_of`); a take is stale when any indicator's latest date differs from it, or when it's missing or predates `as_of`
- [x] A stale take is retried by the next scheduled run and by the next page's background check, even if no indicator has a new value
- [x] After a failed attempt, no further attempt is made for 15 minutes (`AI_RETRY_COOLDOWN`), unless a genuinely new value arrives, so an outage doesn't cost one request per model on every page load
- [x] A successful attempt clears the failure record; the current take is never regenerated, so a "nothing new, take current" check still costs a FRED call and no Gemini call
- [x] A retry that fails again doesn't repaint the page; a successful one patches the AI section in place

**Tasks**
- [x] 16.1 `build_digest_content.py`: `as_of` on `last_ai_response`; `stale_indicator_keys`, `ai_retry_keys`, `AI_RETRY_COOLDOWN`; a failure records `ai_last_failed_at`, a success clears it
- [x] 16.2 `post_release.refresh_ai_response_if_updated` merges `ai_retry_keys` into the run's updated keys
- [x] 16.3 `live_pull.check_for_updates` does the same, skips the calendar refresh unless data updated, and reports `data_updated: False` for a retry that fails again
- [x] 16.4 Tests in `test_build_digest_content.py`, `test_post_release.py`, `test_live_pull.py`: staleness (current, no take, a take predating `as_of`, a newer reading, indicators without history) and retry (not within the cooldown, again after it)

### Story 17 — A 12-Month History for Every Indicator, and a Same-Day Fed Funds Rate
**As** the investor, **I want** every indicator's sparkline and AI context to span a full 12 months whether the series updates daily, weekly or monthly, and the Fed Funds Rate to reflect a rate change within a day, **so that** trends are comparable across indicators and a Fed decision doesn't stay invisible until the following month.

**Why:** history was cut to the last 12 *readings*, which is a year for a monthly series but 12 weeks for jobless claims and about two weeks for the daily yield curve spread. Separately, the Fed Funds indicator tracked the monthly-average series (`FEDFUNDS`), which publishes once a month is over and blends a rate change with the days before it, so a September hike showed 3.63% until October.

**Acceptance Criteria**
- [x] Each indicator's table sparkline and AI context cover every stored reading, i.e. the rolling 12-month window, not the last 12 entries
- [x] `backfill.py` seeds each indicator with every FRED observation from the start of that window (about 250 for a daily series, 52 weekly, 10–13 monthly), and stays safe to re-run (never overwrites or removes existing entries)
- [x] The AI prompt receives at most about one reading per week for a daily series, so it stays short; shorter series are sent in full
- [x] The Fed Funds Rate uses the daily effective rate (`DFF`), which reflects a change within about a day
- [x] Switching an indicator's FRED series discards the old series' readings (a monthly average isn't comparable to a daily rate), both in the scheduled/live ingestion and in `backfill.py`

**Tasks**
- [x] 17.1 `fetch_fred.fetch_recent_observations`: optional `start_date` fetches a time span instead of a count
- [x] 17.2 `storage.history_start_date()`; `backfill.py` backfills from it for every indicator
- [x] 17.3 `build_indicators_context`: `history_window` is every stored reading
- [x] 17.4 `interpret.py`: a daily series is sampled weekly above `MAX_PROMPT_READINGS` (60)
- [x] 17.5 `indicators_config.py`: Fed Funds Rate uses `DFF` instead of `FEDFUNDS`
- [x] 17.6 `run_ingestion` and `backfill.py`: a changed `fred_series_id` discards the old series' history
- [x] 17.7 Tests in `test_fetch_fred`, `test_storage`, `test_backfill`, `test_ingestion`, `test_interpret`, `test_build_digest_content`
- [x] 17.8 Run `python3 src/backfill.py` against the live Redis after deploying (manual) (done: run against the live Redis; it was run again on 22 October 2026 for Story 39's series)

**Notes:** verified against live FRED with an in-memory state: 52 jobless-claims readings, ~250 yield-curve, ~365 fed-funds, 10-11 for the monthly series. CPI and unemployment have only 10 because October 2025 has no reading (the federal shutdown), and a window starting on the current date reaches back only to the following 1st. The Sahm Rule heuristic needs 12 monthly readings, so it stays unavailable for that reason.

### Story 18 — Ticker Valuation Covers Every Ticker and Knows the Macro Backdrop
**Status:** superseded by Story 34 (the AI valuation and its macro backdrop are gone; the three returns stay in the snapshots, which the computed verdicts use).

**As** the investor, **I want** the discount/fair/overpriced columns to list ETFs as well as individual stocks, and the AI to weigh the economic backdrop, **so that** I can see both where to put money in general (the group cards) and which specific tickers, ETFs included, to put it in.

**Acceptance Criteria**
- [x] The per-group cards (bonds, stocks, international, sector, individual) are unchanged
- [x] The Discount/Fair/Overpriced columns list every ticker in every group, ETFs and individual stocks, each with a one-sentence reasoning and a small tag naming its group, in watchlist order within each column (the columns are replaced by Story 34's pills and Verdict column)
- [x] An ETF's verdict is based on how far it sits below its 52-week high, its recent price returns (13-week, 26-week, year-to-date) and its peers (funds have no P/E), and the reasoning says so plainly rather than inventing a P/E-based read
- [x] Each ticker's cached snapshot carries those three returns (from the same Finnhub call already made), shown to the AI for ETFs and individual stocks alike but not as new table columns
- [x] The valuation isn't generated until at least half the cached snapshots carry the returns, so the first check after they were introduced doesn't cache a valuation built without them
- [x] The valuation call is given the indicator digest's saved summary and direction as background; the model is told to let each ticker's own numbers decide, and a missing or unreadable digest take doesn't stop the valuation
- [x] A valuation cached before this change is regenerated on the next check instead of being served for up to 6 hours, and still renders (individual stocks only) if the regeneration fails
- [x] A ticker the AI leaves out is simply absent from the columns, not an error

**Tasks**
- [x] 18.1 `ticker_valuation.py`: schema `individual_tickers` to `tickers` covering every group; `_group_by_verdict` buckets every card and tags each with its group; result key `tickers_by_verdict`; system prompt rewritten for ETFs
- [x] 18.2 `macro_context` parameter, prepended to the prompt as a "Macro backdrop" section
- [x] 18.3 `_load_macro_context()` from `state["last_ai_response"]` (absent or a Redis failure means none); a cache without `tickers_by_verdict` is stale
- [x] 18.4 `page_template.py`: columns render every ticker with a `(Group)` tag; an older cache still renders
- [x] 18.5 Tests in `test_ticker_valuation.py`, `test_ticker_dashboard.py`, `test_page_template.py`, `test_app.py`
- [x] 18.6 `fetch_stock_metrics`: `return_13w` / `return_26w` / `return_ytd`, carried through `_SNAPSHOT_FIELDS` and the cards and shown in the prompt
- [x] 18.7 `_returns_are_cached`: hold the AI call (no failure cooldown) until at least half the cached snapshots have the return fields

**Verified live** (read-only): with the saved indicator take as backdrop, the model returned verdicts for all 31 cached tickers via the third model in the chain after `gemini-3.8-flash` returned `503`. With returns in the prompt it cited them and separated a sector off its high because it is weak (FDIS) from one merely resting, but judgement stayed uneven: bonds and utilities that had fallen were called "discount" on the fall alone, while FDIS, also falling, was "overpriced". That unevenness is what Story 19 addresses.

### Story 19 — Verdicts Are Computed in Code; the AI Only Explains Them
**Status:** built; the ticker-page parts are superseded in part by Story 34 (the AI valuation and its "computed, no AI commentary" fallback are gone from `/tickers`, and the verdicts show as pills and a Verdict column). The digest keeps everything here.
**As** the investor, **I want** the market read and every ticker verdict to come from statistics computed in code, with the AI explaining them, **so that** a verdict is reproducible and checkable, and doesn't disappear when every Gemini model is down.
Rationale, expected sizes and the verdict rules: `docs/v2_technical_design.md` Section 11.21. Code sets every verdict; the AI explains it and cannot change it.

**Acceptance Criteria**

*Indicators*
- [x] Each indicator gets computed statistics from its stored 12-month history: latest value, percentile within the window, z-score, change over 1/3/6 months (as the series' frequency allows) and the slope sign of a short trailing window
- [x] Each indicator is classified favorable / neutral / unfavorable by a rule in code, using a per-indicator "which direction is good" setting kept next to the indicator definitions (e.g. jobless claims and unemployment: lower is favorable; payrolls, permits, production: higher is favorable). An indicator with no inherent direction is reported as context, not scored (the Fed Funds Rate was one until Story 31 scored it as the policy stance, lower being favorable). The thresholds are named constants, not magic numbers
- [x] The existing named heuristics (Sahm Rule, yield-curve inversion streak) feed that classification: a triggered Sahm Rule or an inverted curve forces its indicator to unfavorable
- [x] A market read (bullish / neutral / bearish; improving / mixed / weakening from Story 31) is derived from the indicator classifications by a documented rule; an indicator with too little history is excluded, the read says how many indicators it used, and with too few scored there is no read at all (shown as "No read yet", never a guessed "neutral"). From Story 31 this is a read per group, not one overall read

*Tickers*
- [x] Each ticker gets a computed discount / fair / overpriced verdict from the numbers already in `ticker_cache`, with no fixed cutoffs on a raw number: where its price sits in **its own 52-week range** (needs no peers, so it works in a group of any size) and its 26-week return ranked against **the other tickers in its own group**. One signal alone is never enough for "discount" or "overpriced" (two are needed), so a ticker in a group too small to rank is "fair"
- [x] An individual stock is also ranked on PEG and on a quality rank averaged over ROE, net margin, revenue growth, EPS growth and debt/equity (negative earnings, i.e. no EPS growth and no P/E, count as the worst growth rank). A discount resting on a bottom-third quality rank is a value trap and shown as "fair"
- [x] The one absolute guard: a ticker within 3% of its 52-week high is never a "discount", however it ranks
- [x] A ticker with no usable input is **not scored**: it appears in no verdict column and not in a group's figures, and the page lists it under "Not scored (not enough data yet)". A group with fewer than three tickers can't be ranked
- [x] A group's verdict is judged against its own history, not against other groups: the median position of its scored tickers' prices within their own 52-week ranges (bottom third discount, top third overpriced), so a calm bond fund and a volatile sector are on the same scale. A group needs at least three tickers with a range
- [x] The sector-peer P/E isn't used while it's always `None`; the rule uses it again only if a fund-level P/E source is added
- [x] Per-group badges and the Discount/Fair/Overpriced columns keep their current layout and ordering; each verdict carries the one or two numbers that decided it

*AI and fallback*
- [x] The AI prompts for the digest (and, until Story 34, the valuation) receive the computed statistics and verdicts, and the system prompts tell the model not to contradict them
- [x] If every model in the chain fails, the page and the email show the computed verdict and the stats, labeled "computed, no AI commentary", never an error and never an empty section. This replaces showing a stale cached valuation as the fallback: current numbers beat an hours-old take
- [x] Cached AI text is only shown beside a computed verdict that is the one it was written for, entry by entry (each ticker, each group, the overview); any entry whose verdict has since changed shows computed text instead
- [x] The email's reads and the AI-section badges use the computed reads (one per indicator group from Story 31), so the two surfaces can never disagree
- [x] The content fingerprint that gates the weekly email hashes the computed verdict (the fingerprint hashes `compute_market_read` directly, not the stored take), so a prose-only reword never triggers a send

*Quality*
- [x] Unit tests cover each rule's boundaries (signal threshold, trend veto, scored-count and read thresholds, the discount guard, group size), a missing/short history, a flat series (zero variance), and an out-of-order input list; no network, and the AI mocked
- [x] The thresholds and the direction table are documented in `docs/v2_technical_design.md` (Section 11.21), with the verdict rule stated so it can be checked by hand against a real reading. **The threshold values are first proposals awaiting the investor's sign-off; each is a named constant.**

**Out of scope (named, not backlogged):** a backtest of whether the computed read predicts anything (the rule is a transparent summary, not a forecast); a fund-level P/E source; a UI to edit thresholds.

**Open:**
- [x] 19.11 Investor sign-off on the threshold values (Section 11.21) (manual): accepted by the investor on the strength of the backtest against NBER recessions since 1978 (Section 11.25: 7 of 9 criteria met after Stories 38 and 39)

**Built in:** `indicators_config.py`, `market_read.py`, `interpret.py`, `build_digest_content.py`, `post_release.py`, `email_template.py`, `page_template.py`, `ticker_verdicts.py`, `ticker_dashboard.py`; tests in `test_market_read`, `test_computed_digest`, `test_ticker_verdicts` and the updated interpret, digest, post_release, live_pull, page_template, ticker_valuation and ticker_dashboard tests. Verified live (read-only): 5 discount, 19 fair, 7 overpriced tickers, none unscored.

### Story 20 — History Absorbs FRED Revisions
**As** the investor, **I want** a stored reading to be updated when FRED revises it, **so that** the table, sparklines and computed read use the current figure and not the first-published one.

**Why:** FRED re-publishes several series for months after release; history ignored a same-date value that differed, so a revised month stayed at its first figure (observed live: building permits 1394 stored, 1403 published).

**Acceptance Criteria**
- [x] Each run fetches the last 12 observations per series (one FRED call per series, as before) and a stored reading whose date reappears with a different value is revised in place
- [x] The earlier value is kept as `previous_value` and the time as `revised_at`; `fetched_at` is unchanged, so a revision is not reported as a new reading
- [x] A date is never appended twice, never out of order, and a date not already stored is not added from the lookback window
- [x] A run with a revision and no new reading is saved by the live page check without an AI call or a repaint; a changed computed read retries the AI take under the existing cooldown
- [x] An empty FRED response is an error for that indicator, not a crash and not a change to history
- [x] This supersedes v1 Story 2's "historical values are never overwritten"; the v1 docs note it

**Tasks**
- [x] 20.1 `main.run_ingestion`: `fetch_recent_observations(limit=REVISION_LOOKBACK)` per series; `_absorb_revisions`; statuses `updated` / `revised` / `unchanged` with a `revised` count
- [x] 20.2 `fetch_fred.fetch_latest_observation` removed (nothing else used it)
- [x] 20.3 `live_pull.check_for_updates` persists a revised-only state without an AI call
- [x] 20.4 Tests in `test_ingestion.py` (`TestRevisions`), `test_live_pull.py`, `test_fetch_fred.py`
- [x] 20.5 Docs: v1 Story 2 criterion and design note, CLAUDE.md, README, Section 11.22
- [ ] ~~20.6 Edit Render's start command to `--timeout 300`~~ dropped by decision: Render runs it at 80 and works well, and `--timeout` does not cap a request under `gthread` (Section 11.22)

### Screener Stories 21-26 — Overview
Six stories deliver the Small and Mid-Cap Tech Screener, in order: **21** scores a symbol, **22** keeps the data fresh on a schedule, **23** shows it on a page, **24** lets the investor triage it (shortlist, dismiss, note), **25** makes the hard filters settings the investor can change, **26** shows each name's next earnings date, flags the names due for a review, and lets the nightly job refresh a name when it has reported, and **29** adds a Promote button that puts a shortlisted name on the Ticker Dashboard's Individual table. (Stories 27 and 28 are not screener stories: the Full Position marker and the page scripts.) Stories 21 to 26 and 29 are built. Each story's tasks are listed in it.

Where the details live: requirements in `investment_dashboard_requirements.md` Section 4.5; technical design in `v2_technical_design.md` Section 11.23; screen spec in `ux_design.md` Section 12.

**Build order and dependencies.** `scoring.py` (Story 21) is the single owner of the filters and the score; it takes a settings object whose defaults are the Story 21 constants. Stories 22 to 24 call it with the defaults (Story 22 uses the default market cap band); Story 25 alone added saved settings, validation and the panel, swapped the saved values in, and made the job read the saved market cap range. Story 23 renders empty Shortlisted and Dismissed tabs until Story 24 writes statuses.

---

### Story 21 — Small and Mid-Cap Tech Screener: Scoring
**As** the investor, **I want** each small or mid-cap tech stock scored on profitability, debt, cash flow and dilution from free data, **so that** the ranking is computed, explainable and cheap to produce.

**Why:** the public checklist (profitable, low debt, high return, little dilution) is computable from EDGAR and Finnhub. The data sources, the sample measurements and the gaps are in `v2_technical_design.md` Section 11.23. Hard filters keep out fragile companies; the score orders the rest.

**Status:** built. The thresholds are the agreed starting values; a 10% random sample (about 610 calls) stood in for the full hand-built list, and the full pass is left to the scheduled job (Story 22).

**Acceptance Criteria**

*Universe*
- [x] The universe is Finnhub's US symbol list (`/stock/symbol?exchange=US`), kept to common stocks on Nasdaq/NYSE; EDGAR's `company_tickers.json` supplies each symbol's CIK. A candidate is a symbol in that universe with a tech SIC code (EDGAR) and a market cap of $1.2B to $22.7B (Finnhub `profile2`); the SIC set and cap band are named constants
- [x] A symbol with no EDGAR CIK classifies as `no_cik` and one whose SIC is not tech as `non_tech` (`classify_symbol`; the stage is stored in `screener_universe`), never an error. Checking `no_cik` symbols again each night, because a new listing can appear in Finnhub's list before EDGAR maps its CIK, is Story 22

*Data*
- [x] Market cap, listing (IPO) date and company name come from Finnhub `profile2`; return on investment, debt/equity, net margin, revenue growth and EPS growth come from Finnhub `/stock/metric`; free cash flow (operating cash flow minus capex, last three fiscal years) and annualized share-count change (weighted-average basic shares over three fiscal years) come from EDGAR; no other source is used
- [x] "ROI" is Finnhub's `roiTTM` (return on investment), not a computed return on invested capital; the page, the settings and the docs call it ROI
- [x] A symbol with no 52-week range in Finnhub's response is still scored (`require_range=False`), and `render_range_bar` renders "n/a" for a missing range; using it on the page is Story 23
- [x] Annual figures are read from 10-K, 10-KT, 20-F and 40-F filings (and their amendments). A company reporting under IFRS (taxonomy `ifrs-full`, with no us-gaap cash flow or newer than it) is **flagged** "IFRS filer, not scored yet", not mis-scored
- [x] A symbol with no operating cash flow (or cash flow reported in another currency), capex missing for the latest year, fewer than two fiscal years of share counts, latest annual figures more than 18 months old, or a share count that changes 3x or more in a year in either direction (a likely split or reverse split) is **flagged** with every reason and kept out of the ranking, not scored from a guess; the reasons are stored with the raw figures that could be read. Showing them under "Needs a data check", even if the name would also fail a hard filter, is Story 23
- [x] Institutional and insider ownership are not screened (the page's note saying so is Story 23)

*Scoring*
- [x] Hard filters (all named constants, starting values agreed by the investor): net margin above 0, latest-year FCF above 0, debt/equity at or below 0.5, annual dilution at or below 5%, ROI at or above 5%, and not stale (below). Each filter's value is a default; Story 25 makes them settings. A 10%-sample check (30 symbols in the cap band) found ROI at 10% passed only 2 of 20 scored names and about 10 names across the whole universe; 5% gives about 30 before the stale rule and about 20 after it (3 and 2 of the sample's 20 scored names, so a rough estimate); the first scheduled run gives the real count, and loosening a filter in Story 25 is the lever if it is short of the top-30 target
- [x] A hard-filter figure that is missing (for example no ROI or no debt/equity) counts as failing that filter; the name is simply not shown, not flagged
- [x] The score is the mean percentile rank, among every name that passes every filter whatever its status (so dismissing a name never changes another name's score), of ROI, revenue growth, net margin, low dilution and low debt/equity, equal weights; any missing figure (possible when its filter is switched off) ranks worst on that measure; it is a transparent summary, not a forecast. A shortlisted or dismissed name that fails the current filters has no score ("—") and is not in the ranked population
- [x] A **stale** company is excluded: listed 10 or more years (the IPO date) with revenue growth below 10%. It is meant to drop long-listed names that neither grow nor get acquired. A company with no IPO date or no revenue growth figure is not treated as stale
- [x] Each result stores the raw numbers behind every filter (including the IPO date), not a pass/fail or a score, so the filters and the score are computed when the page is read; a row can be checked by hand against the filings
- [x] There is no takeover-target score

*Quality*
- [x] Unit tests cover each filter's boundary, a missing figure, missing or short data, the split guard, a missing capex tag, an IFRS filer, percentile ties, and a one-candidate or empty set; no network, EDGAR and Finnhub mocked
- [x] The technical design (`v2_technical_design.md` Section 11.23) describes the formulas and constants

**Tasks**
- [x] Size the list with a 10% random sample instead of a full hand-built list and record the pass counts per filter and in total: done, in `v2_technical_design.md` Section 11.23 (the sample's own all-filters counts and the scaled estimates)
- [x] `src/screener/edgar_client.py`: tickers file, submissions (SIC), company facts; `User-Agent` from `SEC_CONTACT`; 5 requests/sec; no retry on 429/403
- [x] Extend `src/web/finnhub_client.py`: a profile fetch (name, market cap, IPO date); `roiTTM` from `/stock/metric`; the US symbol list; and a way to read the metrics when the 52-week range is absent (`require_range=False`)
- [x] Make the `page_template` cell renderers the screener reuses public (no leading underscore): `render_range_bar`, `render_change_cell`, `render_pct_in_range_cell`, `render_market_cap_cell`, `render_pe_cell`, `render_peg_cell`, `format_market_cap`
- [x] `src/screener/scoring.py`: FCF, dilution, split, capex and IFRS flags, the hard filters, the stale rule and the percentile score, as pure functions taking a settings object whose defaults are the constants named at the top
- [x] `src/screener/store.py`: the `screener_universe` and `screener_candidates` keys
- [x] Unit tests for each acceptance criterion above
- [x] Record the final formulas, constants and the measured pass counts in `v2_technical_design.md` Section 11.23

**Out of scope (named, not backlogged):** a backtest of whether the score predicts anything; a takeover-target lens; ownership filters; AI commentary; computing true ROIC.

---

### Story 22 — Small and Mid-Cap Tech Screener: Scheduled Refresh
**As** the investor, **I want** the candidate data refreshed on a schedule without my involvement, **so that** new listings appear, names that grow into the market cap range are picked up, and old figures don't go stale.

**Status:** built. The investor has set `SEC_CONTACT` on GitHub and Render and chose to leave the nightly cron on, and the investor has checked the first run's result.

**Why:** one big initial pass, then each night only new symbols, and a periodic refresh of every symbol already known (every 90 days when the story was built, after the company reports from Story 26): a company can cross the market cap range at any time and fundamentals change when earnings land, but new listings are rare and nothing needs a daily refresh. Prices are not the job's business; the page fetches them live.

**Acceptance Criteria**
- [x] `python3 src/screener/job.py` runs the work order and budgets in the technical design (`v2_technical_design.md` Section 11.23), and `.github/workflows/screener.yml` runs it nightly at 05:30 UTC (00:30 US Eastern in winter and 01:30 in summer, when `/tickers` and `/screener` are idle) and on manual dispatch, with a `concurrency` group so two runs never overlap
- [x] The initial pass is staggered: it stops at `SCREENER_NIGHTLY_CALL_CAP`, progress is saved per symbol, and the next run resumes with the symbols still missing from `screener_universe`; it is complete when every symbol in Finnhub's Nasdaq/NYSE common-stock list has a stage in `screener_universe`
- [x] Each night the job re-reads Finnhub's symbol list and EDGAR's ticker file (one call each) and processes symbols not yet in `screener_universe` first. EDGAR writes a class share with a hyphen (`BRK-A`) where Finnhub uses a dot (`BRK.A`), so the lookup tries the dot form and then the hyphen form
- [x] The job also rechecks the `no_cik` symbols against the EDGAR file each night; a symbol that now has a CIK goes through the same path as a new symbol (a submissions call for its SIC, and a `profile2` call if it is tech)
- [x] About every 90 days (a candidate with a known last report date is refreshed after that report instead, Story 26), oldest first and within the same nightly cap, each tech symbol already known and still in Finnhub's list is refreshed (a candidate is due by its own `market_at`, a symbol with no record by the universe `checked_at`; a symbol that has left Finnhub's list keeps its last record untouched): one with no candidate record gets a `profile2` call (market cap), and one with a candidate record, whatever its status (including dismissed) and wherever its market cap now is, gets `profile2` (name, IPO date, market cap), `fetch_stock_metrics` and its EDGAR facts, rewriting its figures, its market cap in both `screener_universe` and the candidate, and its `market_at` and `scored_at`. Non-tech symbols are never rechecked
- [x] A tech symbol inside the market cap band that has no candidate record (just discovered, newly inside the band after a refresh, or lost) is fetched in full (profile, metrics and EDGAR facts) and becomes a candidate with its name, CIK, IPO date and per-year share counts
- [x] A failed refresh keeps the symbol's last stored values and dates, so the page can show them as old
- [x] No Finnhub call is retried after a 429, and no EDGAR call after a 429 or 403; either stops the run and the symbol is left for the next night. A Finnhub 403 is a plan restriction on one endpoint, not a rate limit, so it skips just that symbol
- [x] One symbol's failure (an API error, an unreadable response, or malformed EDGAR data) never stops the run, and error text in the log never carries the Finnhub API key; the run ends with counts (`new`, `no_cik_rechecked`, `refreshed`, `new_candidates`, `failed`, `stopped`, `finnhub_calls`), `last_run_at`, `universe_total` and `universe_checked` saved to `screener_state`, and printed without any note text
- [x] A refresh never touches `screener_status` or `screener_notes`, and never writes `screener_settings` (from Story 25 it reads the saved market cap range)
- [x] `SEC_CONTACT` and `SCREENER_NIGHTLY_CALL_CAP` are read from the environment, and the market cap band is the default constant until a range is saved (Story 25); the full suite passes with the environment variables unset, and the job refuses to call EDGAR without `SEC_CONTACT`
- [x] Tests cover the work order, the cap, resuming after a stopped run, the `no_cik` recheck (including a dotted class share found by its hyphen form), the periodic refresh (a tech symbol moving into the band and becoming a candidate, a candidate refreshed whatever its status, a candidate due by its own `market_at`, a non-tech symbol and a symbol that left Finnhub's list left alone, oldest first under the cap), a failed refresh keeping the stored record and dates, an unexpected error skipping one symbol, the cap hitting between two calls for one symbol, the log never carrying the API token, a complete rebuilt record (name, CIK, IPO date, per-year shares), `universe_total` and `universe_checked`, and that the job never references the status, notes or settings keys (the job runs one symbol at a time, so there is no completion order to test); no network
- [x] The first workflow run was checked by the investor (the counts line in the log and `screener_state` in Redis)

**Tasks**
- [x] `src/screener/job.py`: work order, nightly cap, `last_run_at`, `universe_total` and `universe_checked` in `screener_state`, the `no_cik` recheck with the dot-to-hyphen lookup, the periodic refresh, run counts
- [x] `.github/workflows/screener.yml`: cron `30 5 * * *`, manual dispatch, `concurrency` group
- [x] Add the `SEC_CONTACT` repo secret (the investor, done); confirm `FINNHUB_API_KEY` and the Upstash secrets are already set
- [x] Add `SEC_CONTACT` and `SCREENER_NIGHTLY_CALL_CAP` to the `CLAUDE.md` environment table
- [x] Unit tests for each acceptance criterion above
- [x] README: how to run the job by hand and how to read its counts
- [x] The investor checked the first run's result in Redis

**Out of scope:** a retry queue; alerting on a failed run beyond the Actions result; a nightly refresh of market data (it is quarterly by choice, see the stale-range note in the technical design).

---

### Story 23 — Small and Mid-Cap Tech Screener: Review Page
**As** the investor, **I want** a page listing the ranked candidates with the numbers behind each, **so that** I can decide which ones are worth researching.

**Status:** built. Depends on Stories 21 and 22 (it reads the job's `last_run_at`, `universe_total` and `universe_checked`); its Shortlisted and Dismissed lists are filled by Story 24 (row actions, notes, the leave-page prompt), and Story 25 added the Filters control and panel.

**Why:** the ranking is only useful if it can be read and checked by eye next to live prices, in the same layout as the Ticker Dashboard.

**Acceptance Criteria**
- [x] `GET /screener` renders instantly from Redis (the price cells show "Loading…" until a quote under 5 minutes old is available), then its script fetches live quotes for the New and Shortlisted rows it is showing, in batches of 25 symbols per `GET /api/screener/quotes?symbols=...` request, and patches only the Price, Change, 52-Week Range and % Off High cells of each batch as it lands, so sort order, open detail rows and unsaved notes are untouched; both routes sit behind the same sign-in; the quote route accepts only symbols that have a candidate record (including a shortlisted name outside the band); a third nav pill, "Small & Mid-Cap Screener", is added to both existing pages
- [x] The page shows when the job last ran ("Last nightly run 19 Oct 2026") and, while the initial pass is incomplete, its progress ("Initial screen in progress: 1,240 of 4,747 symbols checked", from `universe_checked` and `universe_total`); on the New tab a line above the tabs reads "{n} names shown · {m} hidden by your filters" (n is the New tab's row count); the Filters control that goes with it is Story 25
- [x] The table has the same columns as the Ticker Dashboard's `individual` group (Ticker, Price, Change, 52-Week Range, % in Range, Market Cap, P/E, PEG), rendered by the same cell functions, with a sortable Score column after Ticker and Next Earnings (Story 26) at the end, and nothing else (ROI, Debt/Equity, FCF, Dilution, Revenue growth and the dismissal date are in the detail row's "Key figures"); the three lists are links to `?tab=` rather than script-driven tabs, and the detail row and states are as specified in `ux_design.md` Section 12
- [x] The table is sorted by Score, highest first, by default (the Score is shown under the company name, not as a column), and the Ticker, Change, % in Range, Market Cap, P/E and PEG headers sort it; live quotes patching in never re-sort the table, so a row doesn't jump while it is being read; at most 200 rows are rendered per tab (the highest scores) and the page says how many were left out
- [x] Quotes are cached in the `screener_quotes` hash, one atomic write per symbol: a quote under 5 minutes old is reused without a Finnhub call, so reloading the page can't burn quota
- [x] `% in Range` is computed on the server from the price and the stored 52-week low and high, which are as old as the last refresh (up to a quarter), and is clamped to 0–100 when the price is outside that range; the quote route returns the computed value so the browser script only places it; the detail row shows "Figures refreshed {date}"
- [x] A failed fetch falls back to the last cached quote, shown with "as of {time}"; with none cached it shows "n/a". A 429 is never retried and pauses quote fetching for 60 seconds. If a whole batch fails (a network error, a 5xx, or an expired sign-in), its rows show "n/a" and the page says "Prices couldn't be loaded. Reload to try again." (or "Your session expired. Sign in again." with a link)
- [x] The Dismissed tab is never fetched, shows "—" in the price cells, and shows the dismissal date in the detail row (from the stored dismissal time); rows carry no status word because the tab already says it
- [x] The detail row shows free cash flow and weighted-average shares as three-year bar charts with the values printed on the bars (never color alone), plus the filter results, data age and filing links, all read from the candidate record (which holds `shares_by_year`, `cik`, name and IPO date)
- [x] A candidate with no 52-week range shows "n/a" in the range cell (and in % in Range) instead of failing the row
- [x] A failed read of the candidate data, the universe state, `screener_status`, `screener_notes` or `screener_settings` shows the Error state ("Couldn't load the screener data (storage error)"; the typed `KvStoreError` is logged by class only), never a table that looks like "no candidates" or one that shows dismissed names as New
- [x] A New tab that is empty because the filters hide everything says so ("{n} names are hidden by your filters. Open Filters to change them."), not "Nothing left to review"
- [x] Python tests cover the render for every state in the spec, escaping of company names and notes, sort order in the rendered markup including blanks last, the 200-row cap, a failed read of each key, the quote route (cache hit, miss, failure, bad symbol, batch size, and `% Off High` clamped at 0 for a price above the stored high), and the nav on all three pages; no network. The browser-script behavior (no re-sort when quotes patch in, tab and sort handling) is checked by the manual script in `ux_design.md` Section 12.13, since the suite has no JavaScript harness

**Tasks**
- [x] `src/web/screener_page.py`, `GET /screener` and `GET /api/screener/quotes` (25 symbols per request), reusing the public `page_template` cell renderers and `finnhub_client`'s quote call; `% in Range` is computed at render from the live price and the stored 52-week low and high
- [x] `page_template._render_nav` renders a third pill; test it on all three pages
- [x] Tabs, click-to-sort headers, detail row, collapsed "Needs a data check", and every state in `ux_design.md` Section 12.5 that does not depend on Story 24 or 25 (improved flag, undo toast, note states, filter panel)
- [x] CSS in `dashboard.css` (1280px page width, sticky ticker column on narrow windows)
- [x] Unit tests for each acceptance criterion above
- [x] Render fixture mockups of each built state into `docs/ux_mockups/` (the filter-panel mockup was hand-built then, and is rendered from the template now) and review against Section 12

**Result.** Verified: 727 offline tests pass. Live, read-only against the real Redis state: 37 New, 32 under "Needs a data check", 149 hidden and 37 passing (no names shortlisted or dismissed yet); the `/screener` and `/api/screener/quotes` routes answered 200 with real Finnhub quotes for two symbols (the quote cache write was patched out for that check), and an unknown symbol got 400. Not verified: the page's script (sorting, disclosure, Esc, batch patching, the failure messages) and the layout, because there is no browser here; `node --check` confirms the script parses. Run the browser-script checks in `ux_design.md` Section 12.13 item 10 before relying on it. Differences from the plan: the three lists are links with `aria-current` instead of ARIA tabs (no arrow-key handling needed, and `?tab=` already keeps the list across Back); the quote route returns each symbol's four price cells already rendered, as well as the numbers.

**Out of scope:** charts, a price-history view, export.

---

### Story 24 — Small and Mid-Cap Tech Screener: Triage (Shortlist, Dismiss, Notes)
**As** the investor, **I want** to shortlist promising candidates, dismiss the no-good ones, and keep notes while I research, **so that** the page becomes my working list and a decision stays made.

**Status:** built. Approved by the investor ("The stories look fine, approved"). Depends on Stories 21 and 23.

**Why:** the point of the page is to narrow dozens of names to a few, and to keep that work between visits.

**Acceptance Criteria**
- [x] `POST /api/screener/status` sets a symbol to `shortlisted`, `dismissed`, or `new` (clears it); `POST /api/screener/note` saves or clears a note; each is one atomic per-symbol hash write, validated as in the technical design (Section 11.23; symbols may contain letters, digits, `.` and `-`, so class shares like `MOG.A` work), 400 on a bad symbol or an over-long note ("That note is too long (max 2,000 characters).")
- [x] Dismiss is immediate and **undoable**: no confirm dialog, an "Undo" control for 10 seconds, and a Dismissed tab that restores any row at any time. A failed write puts the row back and says so (the 10-second Undo, the rollback and the focus are checked by the manual browser script only)
- [x] A shortlisted row has "Dismiss" (and "Promote", Story 29; it had "Move to New" until then); a dismissed row has "Restore" (the status route clears a status)
- [x] Dismissing a name records the score it had and whether it passed the filters (`score_at_dismissal`, `passed_at_dismissal`). On the Dismissed tab a name is flagged "▲ Improved since you dismissed it (score 62 → 78)" (or "▲ Now passes your filters (score 78)" if it did not pass when dismissed) when it now passes and either did not pass then or its score has risen by 10 points or more (`IMPROVED_SCORE_DELTA`), and a line above the table says how many are flagged. A name under "Needs a data check" counts as not passing, then or now. The status route computes the score at dismissal itself with `scoring.py`, from the current candidates and settings. The flag never moves the name out of Dismissed or changes its status
- [x] A dismissed symbol never reappears in New, whatever a rescore does; a shortlisted symbol that later fails a hard filter stays shortlisted and shows "No longer passes: Debt/Equity 0.8" on its row, and is never removed automatically
- [x] A note has a "Save note" button that is enabled only while the text differs from the saved note, with "Unsaved changes", "Saved" and "Not saved. Retry" messages; leaving the page with an unsaved note asks first (checked by the manual browser script only); two tabs editing different symbols can't affect each other
- [x] A row with a saved note shows "✎ Has a note" under the company name
- [x] Note text never reaches a log, including on the failure path of the note route
- [x] Tests cover each status transition, undo, a rescore leaving status and notes unchanged, a note at the length limit and over it, markup in a note rendering as text, a failed write, the improved flag (rose by exactly the delta, below it, now passes when it did not, still failing, no score recorded), and the note text being absent from log output when a write fails; Redis mocked. The browser behavior (the 10-second Undo, the Save note enabled state, the leave-page prompt, focus after each action, `U` ignored while typing) is checked by the manual script in `ux_design.md` Section 12.13

**Tasks**
- [x] `src/screener/page_store.py`: the `screener_status` and `screener_notes` hashes (and `store.load_candidate`); `scoring.dismissal_snapshot` and `improved_since_dismissal`
- [x] `POST /api/screener/status` and `/api/screener/note` with validation; the status route computes and stores `score_at_dismissal` and `passed_at_dismissal` with `scoring.py` (a failed read fails the dismiss)
- [x] Dismissed tab: the improved flag on each row and the count line above the table
- [x] Page script: optimistic Shortlist, Dismiss (with the Undo notice and `U`), Restore (Move to New was replaced by Promote in Story 29), Save note and its enabled state, the leave-page prompt, focus handling per `ux_design.md` Section 12.8 (the three lists are links, so there is no tab switching)
- [x] Unit tests for each acceptance criterion above
- [x] Run the manual check script in `ux_design.md` Section 12.13 in a browser and record the result there (the investor; there is no browser in the build environment) (checked by the investor in conversation on 23 October 2026)

**Result.** Verified: 761 offline tests pass. The new ones cover status transitions and validation, the server-computed score at dismissal, the improved-flag boundaries, a note at 2,000 characters and one over, markup in a note rendering as text, a failed read and a failed write, and the note text absent from log output when the write fails. Live, read-only: `/screener` rendered all three lists from the real Redis state with the new buttons, but nothing is shortlisted or dismissed yet, so only the New list had real rows and the improved flag, notes and "No longer passes" are checked against fixtures only; the POST routes were exercised only against mocks, because writing a status or note to real Redis would change the investor's data. Not verified: the page script (optimistic move and rollback, the 10-second Undo, `U`, focus, the Save note state, the leave-page prompt) and the layout, because there is no browser here; `node --check` confirms the script parses. The last box above is that browser check. Known limit: only the latest dismissal has an Undo; an earlier one is restored from the Dismissed list. Differences from the plan: a Move to New or Restore only raises the New count when the status response says the name belongs in New (`lands`), since a cleared name that fails a filter or needs a data check does not show there; Undo of a dismissal restores the status the row had before (New or Shortlisted); Restore and Move to New both post `new`.

**Out of scope:** tags, folders, multiple notes per symbol, sharing.

---

### Story 25 — Small and Mid-Cap Tech Screener: Filter Settings
**As** the investor, **I want** to change the screening filters from the page, **so that** I can loosen or tighten the list without waiting for a code change.

**Status:** built. Approved by the investor. Depends on Stories 21-24.

**Why:** the starting thresholds came from a 10% sample and the right values are a judgment call. Changing one should bring new names into the New list or take names out of it, and nothing I have already decided on should move.

**Acceptance Criteria**
- [x] A collapsible "Filters" panel on `/screener` shows every hard filter with its current value: the market cap range (always applied, with an editable minimum and maximum), and, each with an on/off switch, net margin, free cash flow, maximum debt/equity, maximum annual dilution, minimum ROI, and the stale rule (years listed and minimum revenue growth). A filter switched off is not applied
- [x] Defaults are the named constants from Story 21; a setting never saved uses its default, and "Reset to defaults" restores them
- [x] Settings are validated (numeric, within a sensible range, minimum below maximum) and saved to `screener_settings` in one multi-field write, so a failed save leaves the old settings entirely in place; an invalid value is rejected with a message beside the field and nothing is saved
- [x] The panel shows how many names the new settings would show before they are applied ("With these settings: 34 names (now 28)."), and "Apply" saves them and re-renders the list; the ranking score is recomputed among the names that pass
- [x] Changing settings **never** changes a shortlisted or dismissed symbol: a shortlisted name stays on the Shortlisted tab even if it now fails (its row shows which filter it fails, as in Story 24), and a dismissed name stays dismissed even if it now passes. Notes and statuses are not written by a settings change
- [x] A name hidden only because it fails the current settings is not dismissed and has no stored state; it returns by itself when the settings are loosened. The Filters summary on the New tab shows "{m} hidden by your filters"
- [x] Every filter except the market cap range applies instantly, because the stored candidate holds the raw numbers. Widening the market cap range beyond what has been fetched takes effect after the next nightly run, which fetches the tech symbols whose stored market cap now falls inside it; the panel says "{n} more names will be fetched tonight", where n counts tech symbols whose market cap in `screener_universe` is inside the new range and that have no candidate record; names that already have a record reappear at once and are not counted
- [x] The nightly job reads the saved market cap range; with none saved it uses the default
- [x] The data-quality flags (split or reverse split, missing capex, no operating cash flow, too little history, old figures, IFRS filer) are not settings; a flagged name stays in "Needs a data check"
- [x] Tests cover validation, defaults, a filter switched off, a failed multi-field save, a setting change leaving every status and note untouched, a shortlisted name failing the new settings, a dismissed name passing them, the hidden count, and the preview and "fetched tonight" counts; Redis mocked

**Tasks**
- [x] `src/screener/settings.py`: validation, and reading and writing `screener_settings` (the defaults stay in `scoring.ScreenSettings`, and the filters and score in `scoring.py`, which takes the settings)
- [x] `kv_store.hset_many_json`: several fields in one `HSET`
- [x] `POST /api/screener/settings` and `POST /api/screener/settings/preview` (no `GET`: the page renders the saved values and the defaults itself)
- [x] Filters panel in `screener_page.py` and its script (preview, Apply, Reset)
- [x] Job: read the saved market cap range; fetch tech symbols newly inside it
- [x] Unit tests for each acceptance criterion above
- [x] README: link the settings and their defaults to `v2_technical_design.md` Section 11.23 (the README does not copy them)

**Out of scope:** per-filter history of changes, saved presets, and changing the data-quality flags.

---
### Story 26 — Small and Mid-Cap Tech Screener: Earnings Dates and Review-Due Signal
**As** the investor, **I want** the page to show each name's next earnings date and flag the names whose figures have changed since I last reviewed them, **so that** I know when to run my periodic review, and the nightly job refreshes a name when it has reported, not on a fixed 90-day cycle.

**Status:** built (the first real quarterly cycle, November 2026, still has to confirm the 3-day margin). Approved by the investor, with its open items. Depends on Stories 22, 24 and 25.

**Why:** the shortlist and dismiss decisions go stale when a company reports. A fixed 90-day cycle refreshes too early or too late for most names and gives the investor no cue to review. The rationale and the measurement of what Finnhub's free earnings calendar returns are in `v2_technical_design.md` Section 11.23.

**Acceptance Criteria**
- [x] The job stores `{next, last, fetched_at}` for each candidate in a new hash `screener_earnings`, one atomic field per symbol. `next` is the earliest date Finnhub's earnings calendar lists in the next 120 days; `last` is the filing date of the company's latest 10-Q, 10-K, 10-KT, 20-F or 40-F from EDGAR (amendments do not count; Finnhub's free calendar lists no past reports; a foreign filer's 6-Ks do not count). Either may be empty. A candidate's dates are fetched when it has none stored or the stored ones are over 7 days old, oldest first, within the nightly call cap, and once per run per symbol
- [x] A candidate is refreshed (metrics and EDGAR facts, as in Story 22) when `last + 3 days` has passed and its `market_at` is before `last + 3 days`, oldest first, within the same cap. The 3 days leave time for Finnhub and EDGAR to publish the quarter. This replaces the 90-day rule for candidates; a candidate with no `last` date is still refreshed 90 days after its `market_at`, and a tech symbol with no candidate record keeps the 90-day market cap check
- [x] The dates ahead are projections until a company announces: the column header's tooltip says so, and no time of day is shown
- [x] Each status entry (shortlisted or dismissed) can carry `checked_at`, the date of the last review. The review itself is run by the investor asking Claude (the procedure is not code); it writes `checked_at` with the status. An entry with no `checked_at` uses its `at`
- [x] A shortlisted or dismissed row shows "Review due" (the words plus a marker, a tinted row, never colour alone) when its `last` earnings date is after its `checked_at` date; with no dates known, when `checked_at` is more than 100 days ago. A row with a current review shows nothing. The Shortlisted and Dismissed tab headers add the count, for example "Shortlisted (21) · 6 due"
- [x] The tables have a sortable "Next Earnings" column (the date, or "—" when unknown; its header tooltip says it is projected), and the detail row shows "Last checked {date}" and "Last reported {date}". On the New tab the date is shown and never flagged
- [x] If a row's stored dates were fetched over 10 days ago, or its next date is already past, the row shows the date with "(may be out of date)"; a malformed stored entry is treated as unknown dates
- [x] If `screener_earnings` cannot be read, the page still renders, without dates, with the note "Earnings dates couldn't be loaded; Review due uses the 100-day rule for now."; a failed read of `screener_status` still fails loudly as in Story 23
- [x] The job never reads or writes `screener_status` or `screener_notes`; of the page's keys it writes `screener_earnings` only. A 429 from the calendar call stops the run and is never retried, any other error skips that symbol and is logged by symbol only
- [x] Tests cover the date sources (the earliest listed date, none listed, the latest 10-Q or annual filing, a foreign filer's 6-Ks ignored), a refresh triggered once the 3-day margin has passed (inclusive) and not before it, a refresh that does not repeat once `market_at` is past the margin, the 90-day fallback with no date, the cap, a 429, the "Review due" rule for each case (date after `checked_at`, before it, no date, over 100 days, no `checked_at`), no flag on New, the tab count, a stale or unreadable dates hash, and the job leaving statuses and notes untouched; Finnhub and Redis mocked

**Tasks**
- [x] `finnhub_client.fetch_next_earnings_date(symbol, today)`, `edgar_client.fetch_latest_report_date(cik)` and the `screener_earnings` hash in `src/screener/store.py`
- [x] Job: fetch and store dates; replace the candidate 90-day rule with the earnings-date rule and its fallback; add the counts `dates_fetched`
- [x] `checked_at` on the status entry (`page_store.py`: `load_status` and `mark_checked`, which a re-check calls; the status route keeps it when it sets a status)
- [x] `screener_page.py`: the Next Earnings column (a column again from Story 29; it was in the detail row for a while), the Review due marker and row tint, the tab counts, the detail-row lines and the stale-date text
- [x] Unit tests for each acceptance criterion above
- [x] README: a short "Periodic review" section that points to the technical design
- [x] Update `investment_dashboard_requirements.md` Section 4.5, `v2_technical_design.md` Section 11.23 (hash, rule, margin), `ux_design.md` Section 12, Story 22's 90-day criterion, and the README (the schedule line); the mockups were re-rendered later
- [ ] After the first quarterly cycle (November 2026), compare the refreshed records with the new filings and record the result (the investor and Claude; it needs real filings)

**Decided by the investor:** no flag on New names (the date only); the 3-day margin to start, checked in November; the periodic review procedure described in the technical design, with a pointer in the README.

**Result.** Verified: 844 offline tests pass; `fetch_next_earnings_date` against the real Finnhub for FN, QLYS and GLBE (dates 2026-11-09, 2026-11-04, 2026-11-17) and an unknown symbol (none); `fetch_latest_report_date` against real EDGAR for QLYS, FN, DSGX, GLBE, KLIC and VICR (for example QLYS 2026-08-04, FN 2026-08-18). Differed from the plan: Finnhub's free calendar returns no past reports (checked with three windows), so `last` comes from EDGAR instead of the calendar. Not verified: the job's dates step against live Redis and EDGAR together (the owner starts the job, in CI), the page in a browser, and the 3-day margin against a real quarter. The new column and marker are not in the mockups.

**Out of scope:** emailing or pushing the signal, a button to mark a name reviewed from the page, choosing the review's shortlist or dismiss call in code, and dates for tech symbols that are not candidates.

---
### Story 27 — Full Position Marker (Ticker Dashboard)
**As** the investor, **I want** to tick a "Full Position" box on a row to say I already hold as much of that name as I want, and see the row greyed out, **so that** the names I am done buying stop competing for my attention.

**Status:** built on the Ticker Dashboard. The screener's Shortlisted tab had it too until Story 29 replaced it there with Promote. Depends on Stories 3 and 5.

**Why:** the Ticker Dashboard lists names the investor watches in order to buy; once the position is full, the row is noise until it is unticked. One mark per symbol, so a name in two groups is greyed in both.

**Acceptance Criteria**
- [x] Every Ticker Dashboard group table has a "Full Position" column with a checkbox per row, labelled "Full position in {SYMBOL}" for screen readers
- [x] Ticking the box greys out the whole row at once (a muted text colour and reduced contrast on every cell); unticking restores it. The checkbox state is the cue that carries the meaning, so the grey is never the only signal. The row's buttons, links, sort and detail row keep working while it is greyed
- [x] The mark is saved per symbol in a new Redis hash `full_position` (symbol to `{at}`): ticking is one atomic `HSET`, unticking one `HDEL`, via `POST /api/full-position` with `{symbol, full}`; symbols are validated as in Story 24, a bad symbol or a non-boolean is a 400, a storage failure a 503
- [x] The state is shared: a symbol in two Ticker Dashboard groups shows the same state in both after a reload
- [x] The click is optimistic. A failed save puts the box and the row back and says "Couldn't save the change; the box is back where it was."
- [x] The Ticker Dashboard's background refresh and group check keep the greyed state when they redraw a row (when the marks cannot be read at that moment, the boxes already showing are kept)
- [x] The state is read when each page renders. If the hash cannot be read the page still renders with every box unticked, logs the error class, and says "Full-position marks couldn't be loaded." (non-critical data); 
- [x] The mark changes nothing else: not a status, a note, a score, a filter result, the watchlist config, or any job; the screener job and the digest never read or write `full_position`
- [x] Tests cover the route (tick, untick, bad symbol, non-boolean, a failed write), the store (one field per write, a failed read), the column and greyed row on each Ticker Dashboard group and on the Shortlisted tab only, the checkbox label, the group check response and the unreadable-hash degradation, and no job, digest or storage module referencing the hash; Redis mocked

**Tasks**
- [x] `src/web/full_position.py`: load all marks (degrading on a failed read), set and clear one
- [x] `POST /api/full-position` in `app.py`
- [x] Ticker Dashboard: the column and the greyed row in `page_template.py`, kept by the group check response and its script
- [x] Unit tests for each acceptance criterion above
- [x] Update `v2_technical_design.md` (key, route), `ux_design.md` (6.1a and 12.16), the requirements doc (4.2 and 4.5) and `CLAUDE.md`; the README lists no keys or routes, so it needs no change
- [x] Render the mockups for the new column (done: all 22 mockups re-rendered)
- [x] Check in a browser: tick and untick, reload, and a failed save (the investor) (checked by the investor in conversation on 23 October 2026)

**Result.** Verified: 870 offline tests pass; both pages' scripts pass `node --check`; against real Redis (read-only) `/tickers` rendered 31 boxes (one per watchlist ticker, in five tables), the screener's Shortlisted tab 21, and New and Dismissed none. Not verified: a real tick and untick against Redis (a write to production), the click behaviour and the greyed look in a browser, and the mockups, which do not show the column.

**Out of scope:** position size or cost, alerts, a filter or sort by full position, hiding greyed rows, and the screener's New and Dismissed tabs.

---
### Story 28 — Page Scripts Move Out of Python Strings
**As** the investor, **I want** each page's JavaScript to live in its own file, **so that** an editor and a syntax check can read it, and a mistake such as a handler attached before its variable is set is easier to find.

**Status:** built. The investor asked for it in conversation and waived a separate approval. Depends on Stories 1, 3, 23, 24, 25, 26 and 27.

**Why:** the four page scripts were Python strings (two of them f-strings with doubled braces), so nothing checked their syntax, and a hoisting mistake in one shipped (the Full Position box on the Shortlisted tab did nothing). Rationale and the runner-up (a React front end) are in the conversation that proposed it; the stack is unchanged apart from where the scripts live.

**Acceptance Criteria**
- [x] The scripts are the files `src/web/static/js/digest.js`, `tickers.js`, `screener.js` and `screener_filters.js`, with no Python escaping (`{{`) in them, and no page contains an inline `<script>` block
- [x] Each page loads its scripts, and its stylesheet, with a version (the file's modification time) in the URL, so a browser that cached an earlier copy fetches the new one after a deploy
- [x] The pages behave as before: the scripts are the code that was inline, moved unchanged, and read everything they need from the page's own markup (no value is interpolated into a script)
- [x] The scripts are served by the app's static route and sit behind the same sign-in as every other route
- [x] Tests cover: every script file is valid JavaScript (`node --check`, skipped where Node is not installed), no script carries Python escaping, every script a page references is served with a JavaScript content type, the version is the file's modification time and degrades to no version when the file is missing, and the existing assertions on script content now read the files

**Tasks**
- [x] Extract the four scripts to `src/web/static/js/`; `page_template.script_tag` and `static_url`
- [x] Point the digest, ticker and screener pages at them; version the stylesheet link the same way
- [x] Move the tests that read script text from the page HTML to the files; add `tests/test_static_js.py`
- [x] Update the technical design and `CLAUDE.md`

**Result.** Verified: 881 offline tests pass; all four scripts pass `node --check`; against jsdom (a browser DOM emulator, run from a scratch directory and not part of the repo) with the scripts loaded from these files, ticking and unticking Full Position on the Shortlisted tab and on `/tickers` greys the row, posts the change, and reverts with the message when the save fails, and a ticker table sort click works. Not verified: the pages in a real browser, and the other handlers (Shortlist, Dismiss, notes, Filters) in jsdom. A DOM test harness is not in the repo; adding one is out of scope.

**Out of scope:** a framework or build step, TypeScript, minification, and any change to what the scripts do.

---
### Story 29 — Shortlist: Promote to Watchlist and Next Earnings
**As** the investor, **I want** a Promote button on shortlisted rows that adds the name to my Individual table, and the Next Earnings column back, **so that** a shortlisted name moves onto the watchlist in one click and I can see when it reports.

**Status:** built. Approved by the investor in conversation. Depends on Stories 24, 26 and 28; it replaces the screener part of Story 27 and the "Move to New" button of Story 24.

**Why:** the Shortlisted tab and the Individual table are different stages (the first is the screener's pipeline, the second the investor's own watchlist), so neither is merged into the other: Promote is the one crossing, and the shortlist only reads the watchlist to show what is already promoted.

**Acceptance Criteria**
- [x] A shortlisted row's buttons are "Promote" and "Dismiss"; "Move to New" is gone (a dismissed name still returns to New with Restore). The button's tooltip describes what it does ("Add {SYMBOL} to the Individual table on the Ticker Dashboard. The row turns grey while it is there, and normal again if you remove it from that table.")
- [x] `POST /api/screener/promote` with `{symbol}` adds a known candidate to the Ticker Dashboard's `individual` group with the same write as that page's add form, and nothing else: no status, note or other key. A bad symbol, a symbol with no candidate record or a config error is a 400 with a message; a storage failure a 503
- [x] The shortlist reads the `individual` group when the page renders: a shortlisted row whose symbol is in it is greyed (muted text, no colour) with a disabled "Promoted ✓" button; a row whose symbol is not in it is normal with the Promote button up. Removing the ticker from the Individual table makes the row normal on the next load. The New and Dismissed tabs never show a promoted state
- [x] Clicking Promote greys the row, disables its button and the other Promote buttons until the request settles (two quick promotes could overwrite each other's write to the group), moves focus to the row's Dismiss button and announces "{SYMBOL} promoted to the watchlist"; a failed save restores the button and the row and says "Couldn't add {SYMBOL} to the watchlist: {reason}." (the reason only when the server gave one)
- [x] If the group cannot be read the page still renders, with every Promote button up and the note "Couldn't read your watchlist; Promote buttons may be out of date."; a failed read of statuses, notes or settings still fails loudly as in Story 23
- [x] The Full Position column and its greying are gone from the screener (they stay on the Ticker Dashboard, Story 27); the Individual table is unchanged and the nightly job does not read it or fetch earnings dates for it
- [x] The Next Earnings column is back on all three tabs, sortable, with the projected-date tooltip, and no longer in the detail row (Story 26)
- [x] Tests cover the button states and tooltip, the greyed promoted row, the three tabs, an unreadable watchlist, the route (add, bad symbol, unknown candidate, config error, storage error, no status or note written), the page wiring, the script's promote handler and its failure path, the column set and the Next Earnings column

**Tasks**
- [x] `POST /api/screener/promote` and `app._individual_watchlist`; `screener_page.load_view` takes the watchlist
- [x] `screener_page.py`: remove the Full Position column and marks, add Promote and Promoted ✓, the Next Earnings column; `screener.js`: the promote handler; `dashboard.css`: the promoted grey
- [x] Tests; update the technical design, UX design (12.7, 12.9, 12.16), requirements and `CLAUDE.md`

**Result.** Verified: 902 offline tests pass; `node --check` passes; against the real Redis data the Shortlisted tab renders 21 rows at 10 columns with 21 Promote buttons; in jsdom (`tests/test_js_handlers.py`, opt-in), clicking Promote greys the row, disables the other Promote buttons while the request runs, moves focus to Dismiss, announces it and posts `{symbol}` only, and a 400, a 503 and a non-JSON failure each restore the button and show only the server's reason, if any; a disabled promoted button posts nothing; the Ticker Dashboard's Full Position box and sort still work. Not verified: the pages in a real browser, a real promotion writing to Redis (it would modify the production watchlist), and the greyed look.

**Out of scope:** a way back from Individual to the shortlist, removing a name from Individual from the screener, and a Promote button on the New or Dismissed tabs.

---
### Story 30 — Invested Total on the Individual Table
**As** the investor, **I want** to record the total dollars I have put into each ticker in my Individual table, **so that** with dollar-cost averaging I can see how much is in each name without keeping a separate sheet.

**Status:** built. Approved by the investor in conversation ("just Individual", "just a total dollar amount", a pen to edit). Depends on Stories 3, 5 and 27.

**Why:** the Full Position box says a position is done; this says how much is in it. One total per ticker, not a ledger of purchases: the simplest thing that answers the question, and the brokerage stays the source of truth.

**Acceptance Criteria**
- [x] The `individual` table, and no other group, has an "Invested" column between PEG and Full Position, on every row (loaded, pending and errored), showing the total as dollars ("$1,500", "$1,500.50") or "—" when none is recorded, with a pen button labelled "Edit invested amount for {SYMBOL}" and a tooltip
- [x] The pen turns the cell into a number box with Save and Cancel (Enter saves, Esc cancels, an empty box clears the amount); the box is disabled while it saves; on success the cell is redrawn from the server's reply and the pen takes focus; on failure the box stays open and the page says "Couldn't save the amount: {reason}." (the reason only when the server gave one)
- [x] `POST /api/invested` with `{symbol, amount}` saves one atomic per-symbol field in a new hash `invested` (`{amount, at}`, rounded to the cent) or, for a null amount, deletes it; the symbol is validated as in Story 24 and uppercased; an amount must be a number from 0 to 1,000,000,000 (not a boolean, string, NaN or infinity), else a 400 with "Enter an amount from 0 to 1,000,000,000."; a storage failure is a 503
- [x] The amounts are read when the page renders and with each group check. If they cannot be read the page still renders: the cells read "n/a", the pens are disabled, the page says "Invested amounts couldn't be loaded.", and a group refresh keeps the cells already showing
- [x] The amount is never logged, including on the failure path; no job, digest, storage or screener module reads or writes the hash (a test checks)
- [x] A group refresh is skipped while an amount editor is open (or saving) in that group
- [x] A row greyed by Full Position greys the cell too; adding a ticker keeps the column aligned until its group refreshes
- [x] A box the browser cannot parse ("1e", "-") is refused with "Enter an amount in dollars." and clears nothing (a number box reports such text as empty); removing a ticker from the `individual` group clears its amount (a failed clear is logged and does not fail the removal), so a ticker added back starts empty; any well-formed symbol is accepted by the route
- [x] Tests cover the store (read, unusable values, failed read, validation, write, clear), the route, the column on the Individual table only, the cell states, the unreadable case and the group check; the editor's success, cancel, clear, rejected amount, storage error and kept-cells paths run in jsdom (opt-in)

**Tasks**
- [x] `src/web/invested.py`; `POST /api/invested`; `render_invested_cell` and the column in `page_template.py`
- [x] The editor in `tickers.js`; styles in `dashboard.css`
- [x] Tests; the technical design, UX design (6.1b), requirements (4.2) and `CLAUDE.md`
- [x] Try it in a browser (the investor): edit, save, clear, cancel, reload (checked by the investor in conversation on 23 October 2026)

**Out of scope:** a ledger of purchases or dates, shares, average cost or gain and loss, a total across tickers, and the other groups.

---
### Story 31 — A Read for Each Indicator Group, Not One Overall Read
**As** the investor, **I want** the digest to give a separate read for leading, coincident and lagging indicators, each labelled with the time it speaks about, **so that** a prediction is never averaged with a confirmation of the past and I can see when the outlook turns before the data does.

**Status:** built. Approved by the investor in conversation (drop the overall score, three scores, clear time frames, an (i) beside each group label). Depends on Stories 17, 18 and 19.

**Why:** the single score averaged leading (weight 2), coincident (2) and lagging (1). A weakening leading group and an improving lagging group averaged to "neutral", hiding the most useful signal. The Fed Funds Rate was also left unscored, which made every read say "7 of 8"; it was scored as the policy stance for a while (Story 32 reverted that: a falling rate is not a sign of improvement). Rationale: `v2_technical_design.md` Section 11 (market read).

**Acceptance Criteria**
- [x] `compute_market_read` returns a read for each of the three groups (improving at or above +0.25, weakening at or below -0.25, else mixed; the average of the group's scored indicators, equally weighted) with its score, scored count and total; a group with fewer than two scored indicators has no read ("No read yet", never a guessed "neutral"); there is no overall read, score or count anywhere
- [x] A computed sentence says how the reads relate: all agreeing; leading weaker or stronger than coincident (an early warning, or an early improvement); lagging behind or still better than coincident, naming the 6 to 12 month lag; nothing when fewer than two groups have a read
- [x] The Fed Funds Rate was scored with `favorable_direction` "lower" here; Story 32 reverts it to context (a hard cut into a crisis scored "favorable") and adds a policy-stance verdict
- [x] The group reads are worded Improving / Mixed / Weakening (they describe direction against the indicators' own past 12 months; bullish and bearish imply a forecast for stocks); the (i) explanation says what the three words mean
- [x] The page shows three tiles, one per group, each with the group name and an (i) button, a badge with the read as a word, the time frame ("Outlook: where the economy is heading", "Now: how the economy is doing today", "Confirmation: the economy 6 to 12 months ago") and "{n} of {m} indicators scored", then the relationship sentence, then the AI's explanation; the "Based on N of M indicators" line is gone
- [x] The (i) is a button with `aria-expanded` and an explanation element beside it (and a tooltip): click or Enter opens it, clicking again, Esc or clicking elsewhere closes it; every group label in the read card and in the indicator table has one, and each table group shows its time frame
- [x] The email shows the same three tiles with their time frames and counts and the relationship sentence, prints each group's explanation under its table label (it cannot open popups), and its plain-text body lists the three reads
- [x] The AI is told each group's read and meaning and the relationship, must not state another read for any group or offer an overall one, and explains how the groups relate; the ticker valuation's macro backdrop carries the three reads
- [x] A stored explanation is shown only while the three computed reads still match (`computed_reads` on `last_ai_response`; an older take with the previous shape is treated as stale and rewritten at the next run); the weekly email's content fingerprint uses the three reads
- [x] Tests cover the group reads and thresholds, the minimum of two, the relationship sentences, the Fed Funds scoring (reverted in Story 32), the stored-take match and staleness, the fingerprint, the page tiles and info buttons, the email tiles and captions, the prompt, the macro backdrop and the popup script

**Tasks**
- [x] `market_read.py` (group reads, `relationship`, `group_reads`), `indicators_config.py` (Fed Funds), `build_digest_content.py`, `post_release.py`, `interpret.py` (prompt)
- [x] `email_template.py` (`CATEGORY_INFO`, tiles, captions, plain text), `page_template.py` and `digest.js` (tiles, (i) popups), `dashboard.css`
- [x] `ticker_dashboard._macro_context` and `ticker_valuation` (three reads in the backdrop; both removed by Story 34)
- [x] Tests; requirements 4.1, technical design (group reads), UX design (5.x), v1 stories note
- [x] Re-render the three digest mockups (`digest_normal`, `digest_computed_only`, `digest_no_read_yet`), which showed the single overall read (done: all 22 mockups re-rendered)
- [x] Look at the page and the email in a real browser and mail client (the investor): the tiles, the (i) popups and the dark theme (checked by the investor in conversation on 23 October 2026)

**Result.** Verified: 954 offline tests pass; against the real stored data the page shows three neutral reads (3, 2 and 3 indicators scored) and "All three groups agree: neutral."; the (i) popups run in jsdom (opt-in). Not verified: the real layout (including the popup on narrow screens), the dark theme, an actual mail client, and a live Gemini call with the new prompt. The first run after deploy sends the weekly digest once (the content fingerprint changed shape) and spends one Gemini call rewriting the stored explanation.

**Out of scope:** a single combined score of any kind, changing how an individual indicator is classified, and the tickers' own verdicts.

---
### Story 32 — Policy Stance Instead of a Scored Fed Funds Rate, and a Sturdier Minimum
**As** the investor, **I want** the digest to say how tight the Fed's policy is, judged against inflation, instead of scoring the fed funds rate as good or bad for the economy, **so that** a rate cut into a crisis is never read as "improving" and every verdict I read is accurate.

**Status:** built, with two open tasks below. Approved by the investor in conversation: a more meaningful verdict for the fed funds rate using CPI, the fed funds sign fix and the three-reading minimum, and an honest assessment of whether the other indicators can stand on their own. Depends on Story 31.

**Why:** with Improving / Mixed / Weakening describing the economy, scoring a falling fed funds rate "favorable" labels a crisis "improving" (a constructed hard cut scored "favorable"). A rate is policy, not health. Its meaningful reading is relative to inflation: the real rate. The same review found monthly series were scored from only two recent readings. The assessment of all eight indicators is in `v2_technical_design.md` Section 11 (market read).

**Acceptance Criteria**
- [x] The Fed Funds Rate has no favorable direction (context, never scored); the lagging group's count says so ("2 of 3 indicators scored")
- [x] A policy stance (restrictive / near neutral / accommodative) is computed in code from the stored fed funds and CPI history: the real rate is the latest fed funds rate minus the CPI's change over about six months (182 days, within 20), annualized, compared with a neutral real rate of 1.0%; a gap (rounded once, to what is shown) of +0.5 points or more is restrictive, -0.5 or less accommodative, else near neutral; with no fed funds reading or no CPI reading about six months back the stance is None with the reason. The constants are named and explained
- [x] The page, the email (HTML and text) and the AI prompt carry it as one line of context beside the three reads, never inside one and never as a tile, with its numbers and their dates (fed funds rate and its date, inflation and the month of CPI it runs to, the real rate, the gap to a neutral real rate) and the sentence that it describes what the Fed is doing to credit, not how the economy is doing; when it cannot be judged the line says why
- [x] A series needs three readings in its last 90 days (`MIN_RECENT_READINGS` 3, was 2) to be scored; fewer is "insufficient", never a guessed "mixed". A monthly series with a skipped release (as when a release is cancelled) is therefore unscored for about three months and its group shows a lower count; that is intended, the honest fallback
- [x] Tests cover the stance bands and their edges, falling prices, each way it cannot be judged, the six-month reading chosen within the tolerance, the carry-through from stored history, the line on the page, in the email and in the prompt, the Fed Funds rate as context in both directions, and the three-reading minimum

**Tasks**
- [x] `market_read.py` (`policy_stance`, constants, `MIN_RECENT_READINGS`), `indicators_config.py` (Fed Funds: no direction), `build_digest_content.py` (the view carries the stance), `interpret.py`, `email_template.py` (`policy_line`), `page_template.py`
- [x] Tests; technical design (policy stance and the indicator assessment), UX design, requirements
- [x] Verify the 1.0% neutral real rate against the FOMC's latest longer-run projection when FRED is back (the FRED series `FEDTARMDLR`) and update the constant if it has moved (done in the backtest, 22 October 2026: the FOMC median longer-run rate is 3.2%, so the implied neutral real rate is 1.2% against the 1.0% used; kept)
- [x] Run the backtest against NBER recessions (Story 33, built): done on 22 October 2026; the results are in Section 11.25

**Out of scope (candidate later stories, in this order):** a backtest of the indicator rules and group reads against NBER recessions since 1978; level states for the yield curve; a CPI gap-to-target and a core measure (and then a year-over-year inflation for the stance); payrolls against the break-even level; a 4-week average for claims and 3-month for permits; level awareness for the unemployment rate; more coincident and leading indicators.

---
### Story 33 — Backtest the Indicator Reads Against Recessions
**As** the investor, **I want** the digest's rules checked against the economy's actual history, **so that** when the page says Improving or Weakening I know whether that wording has ever meant something, and which thresholds are justified.

**Status:** built and run. Approved by the investor. Depends on Stories 31 and 32. The result is in the technical design, Section 11.25; whether to change any rule is the investor's decision (open below).

**Why:** every threshold in the reads (±0.5 standard deviations per indicator, ±0.25 per group, 90 days, the policy-stance band, the 1.0% neutral real rate) was chosen by judgment and has never been checked against history. One is already known to be weak: with groups of two or three indicators, ±0.25 is crossed by any single net indicator. The assessment in `v2_technical_design.md` ("Indicator assessment") is a judgment until this story measures it.

**Method (fixed before the run, so the result cannot tune the test)**
- **The anchor is outside our own rules:** the NBER recession dates (FRED `USREC`), not our coincident read, because reads from the same rules would be circular. The user's lead–lag idea is added as a second check: does a leading read precede a coincident one, and a coincident one a lagging one?
- **Point in time:** each month-end since 1978 uses only readings that would have been published by then (a release lag per series, written down), a 365-day window as in production, and the production functions themselves (`indicator_stats`, `compute_market_read`, `policy_stance`), never a copy of the logic.
- **Out of sample:** thresholds are explored on 1978–2000 and reported on 2001–2026.
- **A known bias, stated in the result:** FRED holds revised data, which flatters any backtest. Real-time vintages (ALFRED) are out of scope.

**Acceptance Criteria**
- [x] `src/backtest.py` (read-only; run by hand like `backfill.py`, never in CI or the default suite) fetches the eight series and `USREC` from FRED with the shared client (a FRED error stops the run with a typed error and writes nothing), computes the three group reads and the policy stance for every month-end from 1978, and writes a Markdown report to a path given on the command line
- [x] The report states, per indicator and per group: the share of NBER recession months read weakening (or unfavorable) and the share of expansion months read the same way (the false-alarm rate); the months of lead before each recession since 1978 at which the first weakening read appeared; and the share of recession months read Improving (the wrong sign)
- [x] The report states the lead–lag consistency: for leading to coincident and coincident to lagging, at lags of 0 to 12 months, how often a weakening (improving) read is followed by the same direction in the later group, against the rate expected by chance from how often the later group is weakening (improving) at all
- [x] The report states how the policy stance read through known episodes (for example the 2001, 2008 and 2020 easing, the 2022–2023 tightening) and whether Restrictive and Accommodative coincide with them
- [x] The report sweeps the thresholds one at a time (indicator signal 0.25 / 0.5 / 0.75 / 1.0 standard deviations; group threshold 0.25 / 0.5 / 0.67; recent window 60 / 90 / 120 days; policy band 0.25 / 0.5 / 0.75; neutral real rate 0.5 / 1.0 / 1.5) with the metrics above for 1978–2000 and for 2001–2026 separately
- [x] The pass criteria are fixed in the story before the run (see Open items) and the report says for each whether it was met; a criterion that fails is reported as failed
- [x] The neutral real rate is checked against the FOMC's latest longer-run projection (FRED `FEDTARMDLR`) and the result recorded
- [x] The result is recorded in `v2_technical_design.md` (a dated section: what was measured, what held, what did not, the revised-data caveat), and the "Indicator assessment" table is updated from judgment to measured; any threshold change is a separate decision of the investor, made with the report in hand
- [x] Tests (offline, fixtures only) cover: a month's window never contains a reading published after that month (the release lags), the recession labelling and lead-time calculation on a small synthetic series, the hit-rate, false-alarm and chance-adjusted metrics on known inputs, the sweep reproducing the production result at the production values, and a FRED failure writing no report

**Tasks**
- [x] `src/backtest.py` and `tests/test_backtest.py`
- [x] Run it (the investor or Claude, once FRED is back), record the result in the design, update the assessment table
- [x] Decide any threshold changes from the report (the investor), as their own change: decided; the unemployment move, the yield-curve rule and the persistence rule were made in Stories 38 and 39, and the thresholds were kept

**Open items for the investor**
| # | Question | Proposal |
|---|---|---|
| 1 | What counts as the reads being validated? | Fixed in advance. Coincident group weakening in at least 70% of NBER recession months and in at most 15% of expansion months. Leading group weakening at some point within the 18 months before at least five of the six recessions since 1978, with at most 25% of expansion months read weakening. Lagging group weakening in at least 60% of the months 6 to 12 after a recession starts. Policy stance Accommodative in the recession easings and Restrictive in the 2022–2023 tightening |
| 2 | Is revised data acceptable for the first pass? | Yes, stated in the result; real-time vintages (ALFRED) as a later story if the result is close |
| 3 | What if a criterion fails? | The wording and thresholds stay as they are only if the failure is documented on the page's explanation; otherwise they change. Your call with the report |

**Result.** Ran on 22 October 2026 against real FRED data (about 12 seconds): 3 of 9 pass criteria met (Section 11.25). The four policy-stance criteria were later replaced (Story 41), which together with Stories 38 and 39 brings the report to 10 of 12 (the two unmet are the 2001 and 2022-2023 stance episodes). The leading group "warned" before all six recessions, but 84% of expansion months also have a weakening read in the 18 months before them, so that is not evidence; the coincident group fell short of both criteria; the yield curve's direction reads favorable in most recession months; the policy-stance criteria for 2001 and 2022-2023 were mis-specified. Not verified: real-time vintages (out of scope), so the figures are flattered by revisions. Offline tests (`tests/test_backtest.py`) use fixtures only.

**Out of scope:** real-time vintages, tuning the thresholds automatically, other countries, and adding indicators (candidates are listed under Story 32).

### Story 34 — Verdicts in the Ticker Tables, No AI Section

**As** the investor, **I want** each ticker's and each group's verdict shown in the tables, with the reason on hover, **so that** I read the computed result where it applies and not in an AI paragraph that only rephrases it.

**Status:** built. Asked for and specified by the investor in conversation (a pill by the group label, a Verdict column, the words Fair / Overpriced / Discount, not sortable, the AI removed from the Ticker Dashboard only). Depends on Stories 14, 18 and 19; it supersedes the AI parts of 14, 15 and 18 and the "computed, no AI commentary" fallback of 19 for this page. The digest page and email keep their AI.

**Why:** the verdicts were already computed in code and the AI wrote prose around them, which added a Gemini call (shared 20-a-day quota), a cache, a throttle and a failure cooldown without adding information.

**Acceptance Criteria**
- [x] `/tickers` has no AI valuation section, route (`/api/tickers/valuation/check`), cache (`ticker_valuation_cache`), throttle or Gemini call; the page's verdicts are computed from `ticker_cache` on every load and group check
- [x] Each group's label has a pill (Discount, Fair or Overpriced; green, grey, red; the word is always on it). Hover or keyboard focus shows a plain-language summary of the group's reading; it does not show the median price or a ticker count
- [x] A group that cannot be judged (fewer than 3 tickers with a 52-week range) shows a grey "Not judged" pill whose tip says why
- [x] Every table has a Verdict column before the Invested and Full Position cells, with the same pill; hover or focus shows what the word means ("cheaper / in line / richer than its own past year and its peers") and the ticker's reason. It is not sortable (Ticker and % Off High remain the only sorts)
- [x] A ticker with nothing to score shows a grey "Not scored" pill with its tip; a loading or errored row shows a dash
- [x] A group check returns the group's table with its verdicts, and a newly added ticker's placeholder row has a Verdict cell so the columns line up
- [x] Verdict text is escaped
- [x] The verdict rule is unchanged (Story 19); the group summaries are fixed sentences chosen by the group's verdict, plus the tickers standing out as cheaper or richer

**Tasks**
- [x] `ticker_verdicts.py` (`by_ticker`, group `summary`, no `overview`; `merge_with_computed` removed), `ticker_dashboard.py` (`compute_page_verdicts`; valuation load/save/check/throttle removed), `page_template.py` (pills, column, footer line), `app.py` (route removed), `tickers.js`, `dashboard.css`; `ticker_valuation.py` and its tests deleted
- [x] Tests: pills, column placement, escaping, not-judged and not-scored states, group check, `by_ticker`, `compute_page_verdicts`, and that the valuation API and route are gone
- [x] Requirements 4.2, technical design (11.14, 11.20, 11.21 notes), UX design (Ticker Dashboard), README and CLAUDE.md updated
- [x] Re-render the ticker mockups (done: `tickers_error_and_saved` replaces `tickers_error_and_computed`)
- [x] Look at the pills, the hover tips and the new column in a real browser, including keyboard focus and a narrow window (the investor) (checked by the investor in conversation on 23 October 2026)
- [x] Delete the obsolete Redis key `ticker_valuation_cache` (done by Claude with the investor's yes on 23 October 2026; nothing reads it)

**Result.** Verified: the offline suite passes; the page, the group check route (scored cards only, a group with none still renders), pill ids and escaping, and the removal of the valuation API are tested; the page script runs in jsdom (opt-in). The tip is `position: fixed`, placed by the page script so the scrolling table block cannot clip it, and Escape hides it. Not verified: the real look, tip placement near window edges, keyboard and touch focus, and the narrow window (no browser here).

**Out of scope:** removing the digest's AI (the investor chose to keep it), making Verdict sortable, and new verdict inputs.

### Story 35 — % in Range Replaces % Off High

**As** the investor, **I want** a column showing where the price sits inside its 52-week range, **so that** one number reads the same as the range bar and as the verdicts, instead of a distance from the high.

**Status:** built. Asked for by the investor in conversation, for the Ticker Dashboard and the screener. Depends on Stories 3, 19 and 23; it changes the "% Off High" column and its sort from Stories 3 and 23.

**Acceptance Criteria**
- [x] Both pages show **% in Range** where **% Off High** was: `(price - low) / (high - low)` as a whole percent, 0% at the 52-week low and 100% at the high (0 and 100 are shown only at the ends), clamped to 0–100 when the price is outside the stored range, "n/a" when the range or price is missing or degenerate
- [x] It uses the same position the verdicts use (`ticker_verdicts.range_position`), so the column and the Verdict can never disagree
- [x] On the Ticker Dashboard the Ticker and % in Range headers sort (`data-sort-key="pctInRange"`, rows with no value last); on the screener the % in Range header sorts with the other sortable headers
- [x] The screener's quote route returns `pct_in_range` (the page script only places it); live quotes patch the cell in place and never re-sort
- [x] The verdict reasoning still quotes "% below its high" where it helps; the cards still carry `pct_off_high` for that, but no table column shows it

**Tasks**
- [x] `ticker_verdicts.range_position`, `page_template.pct_in_range` and `render_pct_in_range_cell`, `screener_page`, `app.py`, `tickers.js`, `screener.js`; `quotes.pct_off_high` removed; tests updated
- [x] Requirements 4.2, technical design 5.x and 11.23, UX design 6 and 12, CLAUDE.md
- [x] Re-render the mockups, which showed % Off High (done: all 22 re-rendered from the current templates)

**Result.** Verified: offline suite and the opt-in jsdom suite pass. Not verified: the look in a browser.

### Story 36 — A Saved Flag on a Ticker Row Whose Refresh Failed

**As** the investor, **I want** to see when a ticker's numbers are old because its live fetch failed, **so that** I don't read an old price or verdict as current.

**Status:** built. Asked for by the investor in conversation, after asking whether the verdicts use fresh data. Depends on Stories 3, 5 and 34. It follows the working agreement's rule that a non-critical failure shows the data may be stale; there is still no page-wide freshness badge.

**Acceptance Criteria**
- [x] A row whose live fetch failed and which is shown from its stored snapshot has a "Saved" flag (a word and a glyph, not colour alone) next to the ticker
- [x] Hovering or focusing the flag shows "The live update failed. These numbers (and the verdict) are from {date, time} UTC"; a snapshot with no recorded time says it was not recorded
- [x] A row that refreshed shows no flag; the first paint from the cache shows none (every row is a stored value until its group's check lands); an errored row (nothing stored) is unchanged
- [x] The flag is focusable and its tip is a real element, placed by the same script as the verdict tips

**Tasks**
- [x] `ticker_dashboard._card_from_snapshot(stale=True)` sets `stale_since`; `page_template.render_stale_flag`; CSS; tests
- [x] Stories 5, UX design (6.3, Q1), requirements 4.2, technical design 11.x updated
- [x] Look at it in a browser (the investor) (checked by the investor in conversation on 23 October 2026)

**Result.** Verified: offline tests for the card, the flag and its absence. Not verified: a real Finnhub failure (it was not forced against production) and the look in a browser.

### Story 37 — "Checking for Updates…" on the Screener

**As** the investor, **I want** the screener to show the same "Checking for updates…" cue as the other pages while its prices load, **so that** I know the price cells and % in Range may still change.

**Status:** built. Asked for by the investor in conversation, after the Ticker Dashboard's indicator was kept. Depends on Stories 23 and 35.

**Acceptance Criteria**
- [x] A tab with rows waiting for live prices (New, Shortlisted) shows "Checking for updates…" in the header; it clears when every quote batch has landed or failed
- [x] The Dismissed tab (no prices fetched), the never-run page and an empty tab show none
- [x] A batch that fails, is rejected, throws in its failure handler or does not answer within 60 seconds still ends its part of the check, so the cue cannot stay up for good; a header sort is announced to screen readers ("Sorted by Score, descending")

**Tasks**
- [x] `screener_page._page`, `screener.js` (batch counter), tests (Python and jsdom), UX design 12.5
- [x] Look at it in a browser (the investor) (checked by the investor in conversation on 23 October 2026)

### Story 38 — Reads Revised From the Backtest

**As** the investor, **I want** the group reads changed where the backtest showed them wrong, **so that** Weakening and Improving mean what they say more often and warn less falsely.

**Status:** built. Approved by the investor in conversation. Built after Story 39. Depends on Stories 31, 32, 33 and 39. The evidence and the experiments are in `docs/v2_technical_design.md` Section 11.25; every figure below came from scratch experiments on the same history the backtest uses, so the first task is to reproduce them with the production code and the second is to record them in the design.

**Why:** the backtest (Story 33) met 3 of 9 criteria: the coincident group caught 62% of recession months, the yield curve's direction read favorable in 59% of them (it steepens as the Fed cuts), and the leading group cried wolf in 30% of expansion months. Three changes together, tried on the whole history: unemployment (with its Sahm Rule) moved to Coincident (62% to 95% of recession months, 93% and 96% in the two periods); the yield curve scored as inverted at any point in the last 12 months (leading 72% to 97%); and a read that needs two consecutive months (coincident false alarms 18% to 11%, leading 30% to 23%). Together: coincident 91% / 11% and leading 95% / 23% of recession / expansion months.

**Acceptance Criteria**
- [x] `Unemployment Rate` is in the Coincident group (`indicators_config.py`); the page, the email and the AI prompt read from that config, so the group tiles, table sections, time-frame captions and (i) explanations follow it, and the explanations say Coincident now includes employment
- [x] The yield curve is scored from its level: **unfavorable** if any reading in the 12-month window is below zero, otherwise **neutral**, never favorable; its reason names the lowest reading and its date. The direction rule and the inversion-streak heuristic for this series are removed, not left beside it
- [x] A group's read changes to Improving or Weakening only when the read computed from the readings known 30 days earlier (by each reading's `fetched_at`: the day it became public in the backtest, the day we first stored it in production) agrees; otherwise it is Mixed. The earlier read uses the same function and counts only if it was made from as many scored indicators as today's; with no usable earlier read there is no change to the read. For about 30 days after a backfill every reading looks recent, so there is no earlier read and today's read stands The relationship sentence, the email and the weekly-send fingerprint use the final reads
- [x] With Lagging holding fewer than two scored indicators (CPI only until new ones are added), its tile says "No read yet" and says why (the existing no-read wording), and the relationship sentence ignores it
- [x] `src/backtest.py` runs the production implementation of all three changes (it replays them, it does not copy them) and its report states the new results; the numbers above must be reproduced by it before this story is done, and any criterion still failing is reported as failing
- [x] The weekly digest fingerprint changes shape once, so one email is sent after deploy (as in Story 31); the stored explanation with the old reads is treated as stale and rewritten
- [x] Failure paths: with no readings at all for the yield curve or unemployment the indicator is "insufficient" and does not break the group; a missing earlier read (history too short) leaves today's read unchanged
- [x] Tests (offline): the Unemployment group move in the table and tiles; the yield-curve state at the boundaries (a reading of exactly zero is not inverted; one inverted reading 11 months ago; none); the persistence rule with agreeing, disagreeing and missing earlier reads; Lagging with one scored indicator reads none; the fingerprint changes shape; the backtest reproduces the production reads at production values; the docs' stated results match the report

**Tasks**
- [x] `indicators_config.py`, `market_read.py` (yield-curve state, persistence), `heuristics.py` (inversion streak removed if unused), `build_digest_content.py`, `post_release.py`, `email_template.py` and `page_template.py` (explanations), `interpret.py` (prompt wording)
- [x] `backtest.py`: replay the production persistence; tests
- [x] Run the backtest and record the new result in the design (Section 11.25), update the assessment table, the requirements 4.1 and the README's description
- [x] Look at the digest page and the email (the investor) (checked by the investor in conversation on 23 October 2026)

**Result.** The production code replayed by `backtest.py` (22 October 2026): 7 of 9 criteria met; coincident 90% of recession months / 11% of expansion; leading 95% / 24%; lagging 62% of the months 6 to 12 after a start; the two failing criteria are the mis-specified policy-stance ones. Close to the scratch figures (91% / 11% and 95% / 23%). Not verified: the page and the email with the new groups; the first weekly send after deploy. The thresholds were chosen after seeing this history; both periods agree, but only real-time reads can confirm them.

**Open items for the investor**
| # | Question | Proposal |
|---|---|---|
| 1 | Lagging has one scored indicator (CPI) until new ones are added, so its tile reads "No read yet" | Accept that for now and add lagging indicators in the next story, each tested in the backtest first (average duration of unemployment `UEMPMEAN`, commercial and industrial loans `BUSLOANS`, inventory-to-sales ratio `ISRATIO`). Runner-up: build those first; rejected because it delays the fixes that the backtest supports most |
| 2 | The yield-curve rule is a level state, an exception to "direction, not level" | Accept it for this one series: its direction reads the wrong way in recessions (59% favorable) and its value as a signal is the inversion. Runner-up: drop the yield curve from Leading (false alarms 18%, detection 83%); rejected because detection is lower and the inversion is the best-known signal |
| 3 | Is two months the right persistence? | Yes for now: 3 months cut false alarms further but lost half the detection |

**Out of scope:** new indicators (lagging members, real income and sales for Coincident), a corrected policy-stance criterion set, storing the monthly reads and the history chart, and real-time vintages.

### Story 39 — Two New Lagging Indicators

**As** the investor, **I want** the Lagging group to hold indicators that actually confirm a recession after it has started, **so that** its tile can read again after unemployment moves to Coincident (Story 38) and CPI stops carrying the group.

**Status:** built. Approved by the investor ("Yes, go ahead"). Picked by the investor's instruction to backtest the candidates and keep the best one or two. Built before Story 38 so Lagging never shows "No read yet". Depends on Stories 31 and 33.

**Why:** the backtest (Story 33, scratch experiments on the same history, 1978 to 2026) tried six candidates against the NBER months. Median weeks unemployed (FRED `UEMPMED`) is the best on its own: unfavorable in 60% of recession months against 19% of expansion months, and in 83% of the months 6 to 12 after a recession starts. Commercial and industrial loans (`BUSLOANS`, as a percent change) is weak alone (31% against 14%) but pairs well with it. Together, with the Story 38 two-month rule: Lagging reads weakening in 50% of recession months, 12% of expansion months and 62% of the months 6 to 12 after a start (57% for 1978-2000 and 67% from 2001, so the 60% criterion is met on the whole history, near the line in the first period). Rejected: average weeks unemployed (the same survey as the median, so redundant), the inventory-to-sales ratio (weak and only since 1992 in our fetch, 43% / 26% and 0 to 19% after a start), consumer credit (weak alone; a good pair only by chance, so not trusted), core CPI (no separation, 17% against 11%).

**CPI:** scored "lower is better" it separates nothing (16% of recession months against 14% of expansion) and dilutes the group (adding it cuts the months-after share from 62% to 40%). It stays on the page because the policy stance needs it, but as context like the fed funds rate (no scored direction).

**Acceptance Criteria**
- [x] `indicators_config.py` has `unemployment_duration` (FRED `UEMPMED`, lagging, lower is favorable, level) and `commercial_loans` (FRED `BUSLOANS`, lagging, higher is favorable, percent change), each with its FRED release ID for the countdown; CPI's `favorable_direction` becomes None
- [x] The state, the table, the sparklines, the countdown, the email and the AI prompt follow the config: Lagging shows two scored indicators and two context rows (CPI, fed funds), and "{n} of {m} indicators scored" reads 2 of 4
- [x] The first scheduled run after deploy adds one reading for each new series; `python3 src/backfill.py` (a manual run by the investor, safe to repeat) fills the 12 months, and until then the indicator is "insufficient" and Lagging reads none, not an error
- [x] The release lags in `backtest.py` include both series, and the backtest's report lists them; the figures above are reproduced by it with the production code
- [x] Tests (offline): the config entries and their directions, CPI as context, the table sections, the backfill filling both, the group with two scored and two context rows, "insufficient" with short history
- [x] The assessment table in the design is updated from the measured results

**Tasks**
- [x] Config, backfill, release IDs, `backtest.py` lags, tests, design (11.25 and the assessment table), requirements 4.1, README (indicator list: now ten)
- [x] Run `python3 src/backfill.py` (the investor; it writes the production state) and look at the page (done: the backfill added 36 entries on 22 October 2026 with no errors; the page checked by the investor)

**Open items for the investor**
| # | Question | Proposal |
|---|---|---|
| 1 | CPI as context only | Yes: it measures nothing for the recession read, and the stance still uses it. Runner-up: keep it scored; rejected because it cuts Lagging's months-after share from 62% to 40% |
| 2 | Ten indicators, not eight | Yes; the page and email already follow the config |

**Result.** Verified: offline tests; the two release IDs (`50`, `22`) and the series metadata read from the FRED API; the backtest replays the new config. Not verified: the page and the email with the new rows (the backfill has not been run against production), and the figures above that include the two-month rule are reproduced by the backtest since Story 38 (Lagging 62% of the months 6 to 12 after a start). Re-run on 22 October 2026 with the new config (unemployment still in Lagging until Story 38, no persistence): Lagging reads weakening in 88% of recession months, 21% of expansion months and 83% of the months 6 to 12 after a start, so the Lagging criterion is met; 4 of 9 criteria in all.

**Out of scope:** more Coincident indicators (real income, sales), the corrected policy-stance criteria, and storing the monthly reads with the chart.

### Story 40 — Saved Monthly Reads and a "Reads over Time" Chart, Lined Up With the Recessions

**As** the investor, **I want** the three group reads saved every month and charted against the recessions, with each curve moved by the number of months that best matches it to the recession dates, **so that** I can see how Improving, Mixed and Weakening have actually behaved, and the record becomes a real-time test of the rules instead of a replay.

**Status:** built. Approved by the investor. Asked for in conversation ("save the data and show a graph on the page and continue to collect this data going forward"; then "the curves fitted to the correct periods ... try to fit them and calculate your own"). Depends on Stories 33, 38 and 39. Mockups: `docs/ux_mockups/digest_reads_history.html` (the real card, with the real replay as its data; the rest of the page is fixture data) and `digest_reads_history_states.html`; screen spec in `ux_design.md` 5.7.

**Why:** the backtest replays revised data, so its figures flatter the rules (Section 11.25). Reads saved as they happen are not revised, so after a year or two they are the honest test. Until then the replayed history gives the chart something to show, clearly marked as a replay. The groups also move at different times, so lines drawn on the same dates are hard to compare; the fitted view moves each one to where its dips line up with the recession dates.

**The fit (measured on the replay, 1978 to 2026).** For each group, take its weakness (minus its score) and find the shift k, from 18 months earlier to 24 months later, with the highest correlation of weakness at month t with the NBER recession flag at month t+k. Use the shift only if it beats no shift by 0.05 in correlation and the two halves of the history (1978-2000, 2001 on) each find a shift within 3 months of the other; otherwise do not shift that curve and say so. Result on today's replay: **Lagging 7 months** (6 and 8 in the two halves; correlation 0.42 against 0.31 with no shift), so it is drawn 7 months earlier; **Coincident** best at -1 month and **Leading** best at +2 months, neither beating no shift by more than 0.02, so neither is moved. The data does not support a sharp lead for the Leading group at monthly resolution (its correlation is flat from 0 to 6 months), although its lowest score falls about 13 months before a recession starts in five of the six (median; 2020 is the exception), a different measure that six events cannot pin down. The page shows these numbers rather than a bare shift.

**Design in one paragraph (recommendation and runner-up in the Open items):** a Redis hash `indicator_reads`, one field per month ("2026-10") with the three groups' read, score, scored and total, the policy stance, `source` ("live" or "replay") and `saved_at`; a hash `nber_recessions`, one field per month, 0 or 1. A month's live entry is the last Indicator Check run in that month (the current month is in progress and says so). The scheduled run writes it with one atomic field write, so a re-run overwrites only that month and a past month is never touched. A manual script, `src/seed_reads.py`, replays 1978 onward by calling `compute_market_read` through a shared replay function in `backtest.py` (extended to return the full group results, not only the words), reads the existing fields first and writes only the missing months in one multi-field write; a live write that later lands on a month the seed filled replaces it, which is the intended hand-over from replay to live. The digest page asks `GET /api/reads/history` after its first paint and draws the SVG from the answer, so the page's instant render does not wait for about 600 fields; the fit runs on that data every time, so it keeps up as the history grows.

**Acceptance Criteria**
- [x] After each Indicator Check run, the month's field in `indicator_reads` holds the final (post-persistence) group reads, scores, counts and the policy stance with `source: "live"`; the next run in the same month overwrites it; a run in a later month writes a new field and leaves the earlier one unchanged
- [x] A failed write is logged (the type of the error only) and does not fail the run, the email or the page; the next run writes it
- [x] `src/seed_reads.py` (manual, writes Redis, safe to repeat) writes a `source: "replay"` entry for each month from 1978 with no entry, using the production code through the shared replay function, and the `nber_recessions` flags from FRED `USREC`; a second run writes nothing; a FRED failure stops it with a typed error and writes nothing; it reads the existing fields before writing, so it cannot overwrite a live entry except in the instant between its read and its write, which is accepted for a one-time manual script
- [x] The Indicator Check refreshes `nber_recessions` for the latest 24 months once per run (one FRED call, one multi-field write); a FRED failure keeps the stored flags; a missing flag draws no shading rather than failing the chart
- [x] `GET /api/reads/history` is behind the sign-in like every other route (a test lists it with the others); it returns the card's HTML; with Redis unreadable it returns the card with "History is unavailable right now." and status 200; a signed-out session gets the same 401 as the other API routes and the page script shows the "Your session expired" wording
- [x] The chart shows each group's score from -1 to +1 as three lines that differ by dash pattern and are labelled at the right end with the group and the read of the latest saved month (the labels are re-fetched when the page's live check patches the tiles, so they cannot disagree with them for long); labels closer than 15px are stacked 15px apart; recession months are shaded and named in the legend; a dotted line marks where the saved record begins; the line colours come from CSS tokens with light and dark values
- [x] Every curve is drawn lined up with the recession dates (moved by its fitted shift); there is no "as it happened" view. Only Leading is shown at first; "Show" toggle buttons (`aria-pressed`) for Leading, Coincident and Lagging show or hide each line, its end label and its legend entry; a "Range" toggle switches between "10 years" (default) and "All since 1978", each a server-rendered chart swapped in the page; the choices survive the card reloading after a live check; a moved line's end label says how many months earlier it is drawn, and the fitted shifts, their gains and their reasons are in the design and the backtest report, not in a paragraph on the page
- [x] The fit is a pure function with the search range, the 0.05 gain and the 3-month agreement named as constants; with fewer than 10 years of history it returns no shift for every group and says why
- [x] A "Show the data" disclosure lists the latest 24 months (month, the three reads) as a table
- [x] A month with no entry is a gap in the line, not an interpolated point; with no seeded history the chart shows the saved months only and says "Earlier months have not been loaded yet."
- [x] A one-line note under the chart says that months before the first saved one are a replay of today's revised data and later months were saved as they happened, and gives that first month from the data (the long explanation of the fit and the thresholds was removed from the page at the investor's request)
- [x] The stored values are public economic data only and no log line carries them
- [x] The default suite stays offline and fast; nothing in it calls FRED or Redis

**Named tests** (all offline unless stated)
- `test_reads_history.TestSaveMonth`: `test_a_month_is_one_atomic_field_write_of_the_stored_shape`, `test_a_later_run_writes_the_same_field_and_a_later_month_a_different_one`, `test_month_of_is_the_year_and_month`, `test_a_redis_failure_is_raised_for_the_caller_to_decide`
- `test_reads_history.TestSaveMissing`: `test_only_months_not_already_stored_are_written`, `test_nothing_missing_writes_nothing`, `test_a_long_history_is_written_in_chunks`, `test_recession_flags_are_one_multi_field_write`
- `test_reads_history.TestFit`: `test_a_clear_lag_is_found_and_applied`, `test_a_group_already_in_step_gets_no_shift`, `test_a_flat_correlation_gets_no_shift`, `test_halves_that_disagree_get_no_shift`, `test_a_short_history_gets_no_shift_for_every_group`, `test_months_without_a_score_are_skipped_not_counted_as_zero`, `test_a_gain_exactly_at_the_threshold_is_enough`, `test_holes_in_the_history_do_not_move_later_months`, `test_a_group_with_no_scores_at_all_reports_it`
- `test_seed_reads.TestSeed`: `test_it_fills_only_missing_months_marked_as_replay`, `test_a_second_run_writes_nothing`, `test_it_never_replaces_a_live_entry`, `test_a_fred_failure_writes_nothing_and_exits_nonzero`, `test_a_storage_failure_exits_nonzero`
- `test_seed_reads.TestReplayMatchesProduction`: `test_the_replay_matches_compute_market_read`
- `test_reads_chart.TestChart`: `test_gaps_are_not_interpolated`, `test_a_full_history_is_one_unbroken_line`, `test_each_line_has_a_different_dash_pattern_and_an_end_label_with_the_read`, `test_labels_closer_than_the_gap_are_stacked_apart`, `test_the_toggles_use_aria_pressed_and_start_on_the_defaults`, `test_four_charts_are_rendered_and_only_the_default_is_visible`, `test_the_data_table_lists_the_latest_24_months_newest_first`, `test_the_current_live_month_is_marked_in_progress`, `test_missing_recession_flags_draw_no_shading_or_legend_entry`, `test_recession_months_are_shaded_and_named_in_the_legend`, `test_an_applied_shift_moves_only_that_line_and_says_so`, `test_every_path_starts_with_a_move_under_a_negative_or_positive_shift`, `test_a_group_drawn_later_still_starts_at_the_left_edge`, `test_a_group_drawn_earlier_ends_before_the_right_edge`, `test_the_as_it_happened_view_ignores_the_shift`, `test_the_note_names_the_first_live_month_and_the_replay`, `test_with_no_replay_it_says_earlier_months_are_not_loaded`, `test_nothing_saved_says_so`, `test_a_group_with_no_score_is_left_off_the_chart`, `test_the_other_states_are_plain_cards`, `test_every_chart_has_a_title_and_description`
- `test_record_reads.TestRecordReads`: `test_this_months_reads_are_saved_as_a_live_entry_and_the_flags_refreshed`, `test_a_save_failure_is_logged_and_does_not_stop_the_flags_or_the_run`, `test_a_fred_failure_keeps_the_stored_flags`, `test_an_unexpected_error_anywhere_still_does_not_fail_the_run`, `test_a_flag_write_failure_does_not_raise`, `test_with_no_indicators_nothing_is_saved`
- `test_app.TestReadsHistoryRoute`: `test_it_returns_the_card`, `test_redis_down_returns_the_unavailable_card_with_200`, `test_unreadable_recession_flags_also_give_the_unavailable_card`, `test_nothing_saved_yet_says_so`, `test_the_digest_page_has_a_loading_placeholder_for_it`; `TestDashboardAuth.test_api_routes_return_401_not_a_redirect_when_signed_out` lists the route
- `test_js_handlers` (opt-in): `historyCard` in `tests/js/handlers.js` (the default pane and group, the group and range toggles and `aria-pressed`, the 401 and failure messages); `test_backtest.TestWindow.test_production_reads_are_what_the_backtest_reproduces` pins the replay to the live code path

**Tasks**
- [x] `reads_history.py` (save a month, load all, load recessions, `fit_alignment`) over `kv_store`, atomic per-field writes
- [x] `backtest.py`: the shared replay function that returns full group results
- [x] The Indicator Check hook (`main.py` or `post_release.py`) and the `USREC` refresh
- [x] `src/seed_reads.py`
- [x] `page_template.render_reads_history`, the route in `app.py`, `digest.js` (fetch, toggles, refetch after the live check), `dashboard.css` (the line, band, grid and axis tokens, light and dark)
- [x] Requirements 4.1, a new section in the technical design (the keys, the fit, the measurements), README (the seed command), CLAUDE.md (the two keys, both atomic hashes, not blobs)
- [x] Measure the history request (the hash read and the render) before calling it done; the hot path is one `HGETALL` of about 600 small fields per digest visit
- [x] Run the seed (the investor; it writes production Redis) and look at the page (done: the seed wrote 585 replay months and 705 recession flags on 22 October 2026; the page checked by the investor)

**Result.** Verified: the offline suite (1029 tests) and the opt-in jsdom suite, which runs the real page script against the rendered card (the default pane, both toggles and `aria-pressed`, the 401 and failure messages); the fit and chart on a synthetic 585-month history took 37 ms and 8 ms and produced 71 KB of HTML; the fit on the real replay gave Lagging -7 months and no shift for the others (Section 11.25 and 11.26). Not verified: the seed against production Redis (the investor runs it), the look in a browser, dark mode and a phone width, the first live month, and the hash read on the Upstash REST API at about 600 fields. One correction made during the build: the first mockup drew the shifted Lagging line in the wrong direction (later, not earlier); the code and the regenerated mockups draw it earlier. The review then found that a shifted line's path began with `L`, which browsers do not draw; paths now always start with `M`, and a test pins that for a negative, a zero and a positive shift.

**Manual steps** (closed by the investor today, unless stated)
1. After deploy, run `python3 src/seed_reads.py` → "wrote 585 replay months" (the count is the months since 1978), and a second run writes 0.
2. Open the digest page → the card appears a moment after the tiles with only the Leading line (and its recession bands), and the dotted line at the first saved month.
3. Press "Coincident" and "Lagging" → their lines, labels and legend entries appear, Lagging drawn 7 months earlier; press "Leading" → it hides; press "All since 1978" → the longer chart appears and the pressed states change.
4. Open "Show the data" → the latest 24 months list.
5. Closed only after the next month starts: one new live month appears and the replay months are unchanged.

**Open items for the investor**
| # | Question | Proposal |
|---|---|---|
| 1 | Where to keep the history | A Redis hash with one field per month (atomic per-field writes, in line with `ticker_cache`). Runner-up: one JSON blob rewritten each run; rejected because the working agreement forbids read-modify-write of a shared blob |
| 2 | What the lines show | The score (continuous, -1 to +1), with the read words in the tiles and the table. Runner-up: a strip of coloured read words per month; rejected because it needs colour alone to carry the meaning |
| 3 | What is shown first | Only Leading over 10 years (the investor's choice); Coincident, Lagging and the full range are one click away. Always lined up with the recessions; the "as it happened" view was dropped |
| 4 | Seeding writes production Redis, with release-lag approximations | You run `seed_reads.py` once, like the backfill. Runner-up: show only saved months until a year exists; rejected because it leaves the chart nearly empty for a year, and the note says what the replay is |
| 5 | Leading shows no fitted lead | Keep the rule as written (do not shift what the data cannot place) and show the numbers; the typical low point about 13 months before a recession is in the note for the same reason |

**Out of scope:** charting individual indicators, a downloadable file of the history, scoring the saved reads automatically against NBER dates as they arrive (the backtest script can be re-run on them later), and the stock-market comparison.

### Story 41 — Policy Stance: A Zero-Rate Rule, and Validation Against an Independent Real Rate

**As** the investor, **I want** the policy stance checked against an independent measure of the real interest rate and fixed where it is demonstrably wrong, **so that** its verdict (restrictive, near neutral or accommodative) can be trusted as context beside the three reads, without bending it to fit a few episodes.

**Status:** built. Approved by the investor ("Approved, go ahead and build it"); agreed in conversation ("I like the decision based on data"). Depends on Stories 32, 33 and 38. Replaces the four policy-episode criteria of Story 33, which tested the wrong thing.

**Why:** the Story 33 report failed two of its four policy criteria (accommodative in at least half of the 2001 easing months; restrictive in at least half of the 2022-2023 tightening months). Those criteria assumed the stance is a verdict on what the Fed *did* in a month, when it describes the *level* of the real rate: in 2001 the real rate started near +3% and took until mid-2002 to turn accommodative; in 2022 inflation ran at 7 to 10% and the real rate stayed far below zero until January 2023. The stance itself was then tested in scratch against the Cleveland Fed's 1-year expected real interest rate (FRED `REAINTRATREARAT1YE`, 1982 to 2026), which does not depend on our rules or on NBER dates:

| Variant | Level correlation | 12-month change correlation | Stance flips a year | Months misread at near-zero rates | Reaches the right stance within 12 months in the 4 episodes |
|---|---|---|---|---|---|
| Current (six-month annualized CPI) | 0.85 | 0.66 | 1.4 | 17 | 4 of 4 |
| 12-month CPI | 0.85 | 0.57 | 1.0 | 7 | 3 of 4 |
| Three-month smoothing | 0.85 | 0.63 | 1.0 | 15 | 3 of 4 |
| Core CPI | 0.86 | 0.57 | 0.7 | 0 | 3 of 4 |
| Current plus a zero-rate rule | 0.85 | 0.66 | 1.1 | 0 | 4 of 4 |

Our real rate runs about 0.4 points below the reference on average (it uses realized inflation; the reference uses expected). The one defect is that with the fed funds rate below 0.5% (123 months) and inflation near zero, 17 months read other than Accommodative (December 2008 to May 2009, January to May 2015, February and March 2016, May to August 2020). The smoothing, 12-month and core variants track the reference's changes less well and read the 2022-2023 tightening late, so they are not adopted. A restrictive stance in an expansion is followed by a recession within 24 months about 1.4 times as often as an expansion month overall: a modest edge, which is why the stance stays context and is not scored.

**Acceptance Criteria**
- [x] `market_read.policy_stance` returns Accommodative whenever the latest fed funds rate is below `ZERO_RATE_LIMIT` (0.5%), with a `reason` that says so; the real rate and the gap are still computed and shown; at 0.5% and above the existing rule is unchanged
- [x] The page, the email and the AI prompt show the stance sentence as before, with the zero-rate reason where it applies (no new layout)
- [x] `backtest.py` replaces the four episode criteria with: (1) the stance is Accommodative in every month with fed funds below 0.5% (a regression guard, true by construction); (2) in each named episode (2001, 2007-2008 and 2020 easing, 2022-2023 tightening) the stance holds the expected level for 3 months in a row, starting within 12 months of the episode start (a hold added after review, because a one- or two-month flicker had passed the first version of this criterion); (3) the real rate correlates with FRED `REAINTRATREARAT1YE` at 0.8 or more in level and 0.5 or more in 12-month change over 1982 to 2026 (these two thresholds were chosen after seeing 0.85 and 0.66 and the report says so); each is reported as met or not met
- [x] The report also gives, as information and not as pass or fail: the mean difference from the reference, the stance flips a year, the share of expansion months that are restrictive and how much more often a recession follows within 24 months after one
- [x] A FRED failure (including the reference series) stops the run with a typed error and writes nothing, as before
- [x] The result is recorded in the technical design (a section for the stance validation), Story 33's report text is updated, and the unmet old criteria are listed as replaced and why
- [x] Tests (offline): the zero-rate rule just below and at the limit; the reason text; the reach, invariant and correlation calculations on small known series; the report lists the new criteria and not the old ones; a missing reference series stops the run

**Tasks**
- [x] `market_read.py` (the rule and its constant), `backtest.py` (load the reference, the three criteria, the information lines), tests
- [x] Re-run the backtest and record the result in Section 11.25 and the Story 33 Result; update the policy-stance paragraph of the design (11.21) and the requirements if they describe the stance
- [ ] Look at the page and the email the next time the fed funds rate is below 0.5% (the wording only shows then; today's rate is above it) (the investor)

**Result.** Re-run on 23 October 2026: **10 of 12 criteria met** (the five group criteria and five of the seven stance criteria). Correlation with the Cleveland Fed's expected real rate 0.85 (level, 536 months) and 0.66 (12-month changes, 524 months); 0 of 123 low-rate months misread (17 before the rule; true by construction). The 2007-2008 and 2020 easings are held from months 3 and 0. **The 2001 easing and the 2022-2023 tightening are not met**: the stance names the expected level in month 5 and month 10 but flickers back and settles in about month 16 and month 14, outside the 12-month window; they are reported as failed and not widened to fit. Information: 1.2 stance changes a year, 44% of expansion months restrictive, a recession follows within 24 months 1.25 times as often (1.4 on the 1982-onward scratch run). Not verified: the wording on the page and in the email at a near-zero rate (it only appears then; tested with fixtures), and a reference that is itself an estimate. Everything about the stance criteria except the five group ones was set after the earlier policy criteria failed and scratch results were seen, and the report says so.

**Open items for the investor**
| # | Question | Proposal |
|---|---|---|
| 1 | The zero-rate limit | 0.5%: above every near-zero month in 2008-2016 and 2020-2021, below the 2016-2017 tightening. Runner-up: 0.25%, which still misreads February and March 2016 (about 0.4%) |
| 2 | The two correlation thresholds | 0.8 and 0.5, labelled as chosen after the results. Runner-up: report the correlations with no pass line; rejected only because a criterion makes a regression visible |
| 3 | Other inflation measures | Not adopted (see the table); revisit if the stance is ever scored |

**Out of scope:** changing the neutral real rate or the 0.5-point band, scoring the stance inside a read, and fitting any rule to the 2022-2025 period.

### Story 42 — Polish: Fuller Verdict Reasons, Chart Zones, and a Tooltip Fix on Full-Position Rows

**As** the investor, **I want** the Individual stocks' verdict reasons to show every input they were judged on, the reads chart to show where the words change, and the verdict tooltip to work on a row marked Full Position, **so that** nothing looks missing or hidden.

**Status:** built. Asked for by the investor in conversation ("Let's do the small polish", plus the tooltip bug). Depends on Stories 19, 34, 36 and 40.

**Acceptance Criteria**
- [x] An Individual stock's verdict reason always states its PEG and its quality: "PEG 1.5, mid-pack" (or lower or higher than most peers); "PEG not available" with "(earnings are shrinking)" when EPS growth is negative; "PEG x, too few peers with a PEG to rank it"; "quality mid-pack", "weak quality: bottom third of peers" or "strong quality: top third of peers", each followed by the five figures it was ranked on (ROE, net margin, revenue growth, EPS growth, debt/equity, "n/a" for a missing one); "quality not rated, too few figures to rank" with the figures it had. Other groups' reasons are unchanged
- [x] The verdict, the score and the value-trap rule are unchanged by these lines (they only describe)
- [x] The reads chart draws faint dashed lines at +0.25 and -0.25 (where a group's word changes), a heavier line at -1, and names the three zones (Improving, Mixed, Weakening) in the left margin; a group whose score is past a line but still reads Mixed (held until last month's read agrees) is labelled "Mixed (held)" with the reason on hover
- [x] On a row marked Full Position (or a promoted shortlist row), the verdict tooltip and the Saved tooltip appear on hover and on focus as on any other row: the grey scale is applied to the cell's contents and never to the cell, because a CSS filter on a cell makes it the containing block of the fixed-position tip and clips it; the pill and the Saved flag are greyed individually
- [x] `CLAUDE.md` gives the suite's real running time (about 20 seconds)
- [x] Tests: the reason lines for each PEG and quality case and for non-Individual groups; the chart's thresholds, floor, zone names and margin; a static check that no greyed-row rule puts a filter on the cell itself

**Tasks**
- [x] `ticker_verdicts.py`, `reads_chart.py`, `dashboard.css`, tests, `ux_design.md` (6.1c, 5.7), mockups re-rendered
- [ ] Hover a verdict on a Full-Position row in a browser (the investor)

**Result.** Verified: the offline suite and the opt-in jsdom suite. The tooltip cause is a CSS rule, not script behaviour, so jsdom (which has no layout) cannot show it; the fix is pinned by the static check and by the reasoning above. Not verified: the hover itself in a browser (the investor), and the chart at a phone width with the wider left margin.

**Out of scope:** re-checking a group's pill after a remove (not wanted), and any change to how a verdict is decided.

---
## Cross-Cutting Non-Functional Criteria (apply to all stories above)
- [x] Every page and API route requires Google sign-in when `GOOGLE_CLIENT_ID` is set (Story 8); with it unset, as in local development, none does
- [x] Both pages are usable on a desktop/web browser (no mobile app)
- [x] A data-source outage (FRED, Finnhub) or missing data degrades gracefully (visible error/empty state) rather than crashing the page
