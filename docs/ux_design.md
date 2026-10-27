# UX Design — Investment Dashboard

Status: Draft for the investor's review
Covers: the two built web pages (Indicator Digest `/`, Ticker Dashboard `/tickers`), their shared shell, and the digest email only where it shares wording with the page; Section 12 specifies the Small & Mid-Cap Screener (`/screener`; the table, triage, notes and live prices are built)
Follows: `investment_dashboard_requirements.md` (Sections 2, 4.1-4.5), `v2_user_stories.md`
Mockups: `docs/ux_mockups/*.html` — rendered by the real page templates with **fixture data** (no live data, no network). Open them in a browser; they link the real stylesheet.

## 0. Mode, and what this document is

Modes used: **screen map + style guide + screen spec**, written against UI that already exists. Because the pages are built, the style guide below records the system **as built** (from `src/web/static/dashboard.css` and `page_template.py`) rather than proposing a new look, and the screen specs describe what a person sees and does today, followed by the problems found. Anything that changes how the product looks or behaves is a **decision or open question**, not a done change.

It does **not** cover: new features, the email's HTML layout (`email_template.py`), or any code change. Nothing in `src/` was edited for this document.

Settled decisions this document does not reopen (from the requirements and `CLAUDE.md`):
- One table per group, not per-ticker cards; no per-ticker news column.
- No persistent Live/Saved freshness badge or timestamp on the Indicator Digest Page.
- No top-discount row highlight on the ticker tables.
- On the Ticker Dashboard, sort is per-table, client-side, on **Ticker** and **% in Range** only (the Small & Mid-Cap Screener sorts more columns; see 12.7).
- Desktop/web browser first; no native mobile app.

## 1. Person, goal, and use

- **Person:** one investor (the owner), long-term buy-and-hold, not a trader. Signed in with one Google account on a hosted page; no other roles.
- **Goals, in the order they happen:**
  1. *Glance (daily, seconds):* "Is anything different or worth acting on?" — the macro read, and which tickers sit cheap in their range.
  2. *Buy day (Monday, minutes):* "Where do I put this week's money?" — which groups and tickers are discounted, and why.
  3. *Maintain (rare):* keep the watchlist current; understand an unexpected verdict.
- **Today's alternative:** a brokerage website plus a hand-updated Google Sheet (login, manual entry). The page is "done" when the glance takes under ten seconds and needs no login to a brokerage.
- **Success, observable:** on load, the numbers and the read are on screen immediately (from cache); anything newer appears in place without the page jumping; nothing is ever blank or an error where an older value exists.

## 2. Screen map

```text
                    (Google sign-in — hosted only; /login -> Google -> /auth/callback)
                                     │
                                     ▼
        ┌─────────────── shared shell: nav pills ────────────────┐
        │   [ Indicator Digest ]        [ Ticker Dashboard ]      │
        └───────┬─────────────────────────────────┬───────────────┘
                │                                 │
                ▼  "/"                            ▼  "/tickers"
   Indicator Digest                      Ticker Dashboard
   ├─ AI / computed read card            ├─ Market news
   ├─ Indicators by category (table)     └─ One table per group, a verdict pill by each
   └─ Next releases (countdown)             group label and a Verdict column  (+ add, remove)

   Background (no screen): /api/check, /api/tickers/groups/<g>/check,
   /api/market-news/check   -> patch sections in place
```

- **Start screen:** the Indicator Digest (`/`). First-time user (empty indicators): the page still renders, with no table rows and no read (see 5.1 *Empty*).
- **Moving between screens:** the nav pills only. There is no Back affordance of its own; the browser Back button works because navigation is plain links.
- **Global actions:** none beyond nav. There is no search, settings, help, or sign-out control on the page (sign-out is `/logout`, unlinked). See open question Q4.
- **Third screen:** the Small & Mid-Cap Screener (`/screener`), a third nav pill; specified in Section 12, built (Stories 23 to 26).
- **Not screens:** the email is a third surface for the digest; sparklines, range bars and badges are components (Section 3).

## 3. Style guide (as built)

**Direction.** Calm, light, card-on-slate dashboard: a pale slate page, white cards, a single blue accent, small uppercase labels. Dense where tables are long (ticker tables), generous where it is prose (the read card). Reference feel in the requirements: a clean monitoring page that replaces a spreadsheet.

**Type.** System UI stack (`-apple-system`, Segoe UI, Roboto, Helvetica, Arial).

| Role | Size / weight | Used for |
|---|---|---|
| Page title (h1) | 20px, 700, uppercase, +0.04em, accent blue | "Indicator Digest", "Ticker Dashboard" |
| Section label | 13px, 700, uppercase, +0.04em, `#334155` | Leading/Coincident/Lagging, group names, "Next Releases" |
| Body / prose | 15px, line-height 1.6 | the read summary |
| Table cell | 14px (indicator), 13px nowrap (ticker) | numbers and names |
| Table header | 11px, 700, uppercase, muted | column headers |
| Caption / meta | 12-13px, muted | footers, disclaimers, dates, "prior:" |

**Spacing.** 4px grid in practice: 8 (gaps, cell padding), 12, 16 (page gutter and card margin), 18-20 (card padding), 24 (page top), 48 (page bottom). Page width 720px (digest) and 900px (tickers), centered.

**Colour and theme.** Roles, light / dark:

| Role | Light | Dark | Notes |
|---|---|---|---|
| Page background | `#f1f5f9` | `#0f172a` | |
| Card / surface | `#ffffff` | `#1e293b` | |
| Border | `#e2e8f0` | `#334155` | |
| Text | `#1e293b` | `#e2e8f0` | |
| Muted text | `#64748b` | `#94a3b8` | |
| Accent | `#2563eb` | `#2563eb` | h1, active nav, hover |
| Good / up / bullish / discount | `#15803d` on `#dcfce7` | same (fixed) | see finding F1 |
| Warn / mid-range | `#f59e0b` | same | range bar mid only |
| Bad / down / bearish / overpriced | `#b91c1c` on `#fee2e2` | same (fixed) | see F1 |
| Neutral / fair | `#475569` on `#e2e8f0` | same (fixed) | |

Dark theme follows `prefers-color-scheme`; there is no manual toggle. The verdict colours are **fixed light-theme values** (not theme tokens), which is the root of F1.

**Meaning never by colour alone** (already the convention; keep it): change cells carry a ▲/▼ and a signed number; range bars print low/high beside the bar; verdict badges carry the words Bullish/Neutral/Bearish and Discount/Fair/Overpriced.

**Density.** Reading view (digest card): relaxed. Lists (indicator rows): comfortable, 10px vertical cell padding. Ticker tables: compact, 8px/6px padding, no wrapping; header cells may wrap to two lines.

**Hierarchy.** Each page has one lead card at the top (the read; the Ticker Dashboard's is the market news), then data blocks, then a quiet footer. The nav pill for the current page is filled accent; the other is outlined.

**Components.** Nav pills; card; verdict badge (rounded, uppercase 12px); read card (left 4px accent border + tinted background); indicator table with 90×24 inline-SVG sparkline; ticker table with 90×10 range bar (green→amber→red gradient, white marker); countdown card with "Next up" chip; inline add-ticker form (text input + "Add"); remove "×" button; "Checking for updates…" italic muted pulse.

**Motion.** One animation: the "Checking for updates…" pulse (1.2s opacity). No transitions. See F9 for reduced motion.

## 4. Shared behaviour (both pages)

**Load pattern.** Every page renders instantly from stored data, then checks for newer data in the background and patches only the sections that changed. While a check is running a muted italic "Checking for updates…" shows in the header and disappears when the check ends, whichever way it ends.

**What a person must be able to rely on**
1. A value on screen is never replaced by a blank or an error because a refresh failed; the earlier value stays.
2. A refresh never moves what they are reading (patches are in place, same sizes).
3. Sort order and typed text in one group are not disturbed by another group's refresh (a group's own refresh does reset that group's sort).

**State vocabulary used across screens**

| State | Wording on screen | Where |
|---|---|---|
| Fetching a row's first data | "Loading…" in the row | ticker row |
| Row failed and nothing cached | "Unable to load data." | ticker row |
| Value genuinely absent | "n/a" (muted) | any numeric cell |
| Section not yet generated | "Loading market news…" / "No AI interpretation on file yet." | cards |
| Feed empty | "Market news unavailable." | news card |
| Computed without commentary | "Computed from the indicator data; AI commentary is unavailable right now." | read card |
| Too little history | each group badge "No read yet"; with none at all: "Not enough history on file yet to compute a read." | read card |
| Ticker with nothing to score | grey "Not scored" pill; tip "Not enough data yet to compare this ticker with its own year or its peers." | Verdict column |
| Group too small to judge | grey "Not judged" pill; tip "Too few tickers with a 52-week range to compare: a group needs at least 3." | group label |

## 5. Screen spec — Indicator Digest (`/`)

### 5.1 Goal, scope, place
- **Goal:** "Tell me, in one look, whether the economy's direction changed and when the next numbers land."
- **In:** read card, indicator table by category with trend, next-release countdown, background refresh.
- **Out:** per-indicator drill-down, history beyond the 12-month sparkline, settings.
- **Reached from:** direct URL, nav. **Leads to:** Ticker Dashboard via nav. **Way back:** browser Back.

### 5.2 Task flow
1. Open the page → read card and tables are there at once.
2. Read the three group badges (Improving / Mixed / Weakening), each with its time frame and "{n} of {m} indicators scored", then the sentence on how they relate, the policy-stance line and the one-paragraph explanation; open an (i) to see what a group means.
3. Scan the table: value, trend line, date, prior value; read category by category (Leading first).
4. Glance at "Next up" to know when to look again.
5. If a background check finds new data, the three sections update in place; if not, nothing changes.

### 5.3 States

| State | When | What is seen | Can do |
|---|---|---|---|
| Normal | data and a matching AI take | three group tiles (badge, time frame, "{n} of {m} indicators scored") + relationship sentence + explanation; tables; countdown | read; navigate |
| Checking | first seconds after load | "Checking for updates…" top right | nothing needed |
| Computed only | every model failed, or the stored take is for a different read | badge + "Computed from the indicator data; AI commentary is unavailable right now." | read |
| No read yet | a group has fewer than 2 indicators with enough history (e.g. after a wipe) | that group's tile shows a grey "No read yet" badge and its count (e.g. "0 of 3 indicators scored"); the other groups keep their reads; no relationship sentence with fewer than two reads | wait; recovery is `backfill.py` |
| Empty | no indicator has any history | page frame, "No AI interpretation on file yet.", no tables, no countdown | nothing — see Q2 |
| Value missing | no prior reading | "prior: n/a" | read |
| Very long | an indicator name or the explanation wraps | wraps; page grows | read |

Mockups: `ux_mockups/digest_normal.html`, `digest_computed_only.html`, `digest_no_read_yet.html`, `digest_empty.html`.

### 5.4 Wireframe (normal)

```text
[ Indicator Digest ] [ Ticker Dashboard ]                     (nav pills; current = filled)
INDICATOR DIGEST                                  Checking for updates…
┌──────────────────────────────────────────────────────────────────────────┐
│ LEADING ⓘ        COINCIDENT ⓘ     LAGGING ⓘ                               │
│ [IMPROVING]      [MIXED]          [WEAKENING]                              │
│ Outlook: where   Now: how the     Confirmation: the                        │
│ the economy is   economy is       economy 6 to 12                          │
│ heading          doing today      months ago                               │
│ 3 of 3 scored    2 of 2 scored    3 of 3 scored                            │
│ The outlook is stronger than the present: leading indicators are          │
│ improving before current conditions have.                                  │
│ Jobless claims are low and falling, but the yield spread is compressing…  │
│ This is automated commentary based on indicator trends, not advice.       │
└──────────────────────────────────────────────────────────────────────────┘
LEADING
┌──────────────────────────────────────────────────────────────────────────┐
│ Initial Jobless Claims   ╱╲_╱‾   199000   2026-09-26   prior: 198000      │
│ 10yr-2yr Treasury Spread ‾╲_╲    0.42     2026-10-12   prior: 0.45        │
│ Building Permits         _╱‾╲╱   1403     2026-08-01   prior: 1380        │
└──────────────────────────────────────────────────────────────────────────┘
COINCIDENT … LAGGING …
┌ NEXT RELEASES ───────────────────────────────────────────────────────────┐
│ [Next up] CPI — in 2 day(s) (2026-10-15)                                  │
│ Building Permits                                  in 7 day(s) · 2026-10-20│
└──────────────────────────────────────────────────────────────────────────┘
Automated macro indicator digest · data from FRED · checks for live updates in the background
```

Primary action: none — it is a reading screen. The badge is the thing read first, the table second, the countdown last.

The read card has three tiles, one per group, each with the group name and an ⓘ button, its improving / mixed / weakening badge (never colour alone: the word is the badge; the words describe direction against the indicators' own past year, not a forecast for stocks), the time frame it speaks about and "{n} of {m} indicators scored". Below them one computed sentence says how the three relate, then one muted line for the policy stance (below), then the AI's explanation. The policy stance line reads: "Policy stance: Restrictive. The fed funds rate is 4.50% (as of 19 Oct 2026) and recent inflation is 2.5% (CPI to Sep 2026, six-month annualized), so the real rate is 2.0%, 1.0 points above a neutral real rate of about 1.0%. This describes what the Fed is doing to credit, not how the economy is doing." (Accommodative and Near neutral read the same way, "at" replaces "0.0 points above"; with the fed funds rate below 0.5% it adds "It reads Accommodative because the fed funds rate is near zero, whatever recent inflation was." and, if inflation cannot be worked out, drops the inflation clause; when it cannot be judged: "Policy stance: not available yet ({reason})."). It is context, not a fourth tile, and it carries no colour. There is deliberately no overall read: the groups look at different times and are not averaged. The same group names in the table carry the same ⓘ and a one-line time frame. The ⓘ is a button: click or Enter opens a short explanation under it, clicking it again, Esc or clicking elsewhere closes it (the explanation is also its tooltip); its label reads "About {group} indicators". In the email, which cannot open popups, each group label has its explanation printed under it.

### 5.5 Interaction spec

The (i) beside each group label (read card and table): click or Enter on the button opens its explanation (focus stays on the button; `aria-expanded` turns true; label "About {group} indicators"); clicking it again, Esc or clicking elsewhere closes it (Esc returns focus to the button); only one is open at a time; text inside an open explanation can be selected without closing it; on a narrow screen the last tile's explanation opens toward the left so it stays on screen. The mockups for the digest still show the single overall read and have not been re-rendered.

| Element | Action | Result | Keyboard | Announced as |
|---|---|---|---|---|
| Nav pill "Ticker Dashboard" | click | go to `/tickers` | Tab to it, Enter | link "Ticker Dashboard" (should also say current page on the active pill: F7) |
| Page | load | cached render, then background check; sections patch in place | — | nothing today (F4) |
| Table rows, sparkline | none | read-only | — | sparkline reads "trend line" (F8) |

There is nothing to cancel, undo, or confirm on this screen.

### 5.6 Content

| Where | Text |
|---|---|
| Title | Indicator Digest |
| Header meta while checking | Checking for updates… |
| Categories | Leading, Coincident, Lagging |
| Group tile | {GROUP} + (i) · badge (Improving / Mixed / Weakening / No read yet) · time frame (Outlook: where the economy is heading / Now: how the economy is doing today / Confirmation: the economy 6 to 12 months ago) · {n} of {m} indicators scored |
| Relationship | one or two computed sentences (all three agree; the outlook weaker or stronger than the present; the lagging data not caught up or still better; the groups that have a read agree or differ) |
| Plain-text email | {Group} ({time frame}): {Badge}, {n} of {m} indicators scored · one line per group |
| Disclaimer | This is automated commentary based on indicator trends, not personalized financial advice. |
| Countdown | Next Releases · Next up · in {n} day(s) · {date} |
| Footer | Automated macro indicator digest · data from FRED · checks for live updates in the background |

Tone: plain, numeric, no exclamation or hype. Wording to fix: see F11 ("day(s)").

### 5.7 Reads over time (Story 40)

**Goal.** "Show me how the three reads have moved against the recessions, with each one lined up to where it belongs, so I can judge whether Weakening and Improving mean anything." **Where.** A card on the Indicator Digest page between the read tiles and the indicator tables; it loads a moment after the tiles because its data comes from a separate request.

**Content.** The title "Reads over time"; two toggle groups, "Show" (Leading, Coincident, Lagging; only Leading is pressed at first) and "Range" ("10 years", the default, and "All since 1978"); the chart; a legend; a one-line note on which months were replayed and which saved; a "Show the data" disclosure with the latest 24 months as a table (month, leading, coincident, lagging read).

**Chart.** The x axis is months; the y axis is each group's score from -1 (every indicator unfavorable) to +1 (every one favorable), with 0 drawn heavier, a faint dashed line at +0.25 and -0.25 (where a group's word changes, before the month-earlier check), a heavy line at -1 (every scored indicator unfavorable), and the three zones named in the left margin (Improving above +0.25, Mixed between, Weakening below -0.25). Three lines differ by dash pattern (leading solid, coincident dashed, lagging dotted) as well as colour, and each is labelled at its right end with the group name and its latest saved read in words; labels closer than 15px are stacked 15px apart, and a moved line's label says how many months earlier it is drawn. Recession months (NBER) are shaded and named in the legend. A dotted vertical line marks where the saved record begins; everything left of it is a replay of today's revised data. A month with no entry is a gap in the line. Colours are tokens (`--line-leading`, `--line-coincident`, `--line-lagging`, `--band`, `--grid`, `--axis`) with light and dark values.

**Lined up with recessions.** Every curve is moved by the shift, calculated from the saved history, that best matches its dips to the shaded months (Story 40 describes the fit and its two safeguards; the numbers are in the design and the backtest report, not on the page); there is no view on the real dates. A group with no reliable shift stays where it is. On today's replay only Lagging moves (7 months earlier), and its end label says so. A hidden group's line, end label and legend entry are hidden together; the choice is kept when the card reloads. A group whose score is past +0.25 or -0.25 but still reads Mixed is held by the month-earlier rule: its end label reads "Mixed (held)" and its tooltip explains.

**States** (mockup `digest_reads_history_states.html`)

| State | When | What is seen |
|---|---|---|
| Loading | the page has painted, the request has not returned | the card with "Loading history…" |
| Normal | history readable | chart, legend, note, data table |
| Saved months only | the replay has not been seeded | a short chart and "Earlier months have not been loaded yet." |
| Unavailable | Redis unreadable or the request failed | the card with "History is unavailable right now." and nothing else on the page changes |
| Session expired | the request returns 401 | the card with "Your session expired. Sign in again." |
| No recession dates | `nber_recessions` empty | the chart without shading and without the legend entry |

**Interaction.** The toggles are buttons with `aria-pressed`, reachable with Tab and acting on Enter or Space; a group button shows or hides that group, the range button swaps a server-rendered chart. The disclosure opens with Enter or Space. There is no hover-only information: the data table carries what the lines show.

**Accessibility.** The SVG has a title and a description (the title names the view); meaning is carried by dash pattern, end labels and the table, never colour alone. Text is at least 11px. Not verified: dark theme and narrow windows (the chart scales with the page width and its end labels need a check on a phone).

Mockups: `ux_mockups/digest_reads_history.html` (the real card on the rendered digest page; its data is the real replay of the reads, with the last month marked as the first saved one) and `digest_reads_history_states.html` (loading, unavailable, a few saved months, session expired). The rest of the page is fixture data.

## 6. Screen spec — Ticker Dashboard (`/tickers`)

### 6.1 Goal, scope, place
- **Goal:** "Show me, for this week's buy, which of my tickers sit cheap in their own range and why, and let me keep the list current."
- **In:** market news, one table per group with a verdict pill by its label and a Verdict column (6.1c), sort, add and remove ticker, a Full Position checkbox per row (6.1a), background refresh per group.
- **Out:** adding/renaming/removing a whole group (direct Redis edit; backlog), per-ticker news, alerts, charts, multi-currency.
- **Reached from:** nav. **Leads to:** Indicator Digest via nav; news headlines open in a new tab.

### 6.1a Full Position (Story 27)
A "Full Position" column, left of the remove button, holds a checkbox per row, labelled "Full position in {SYMBOL}". Ticking it greys the whole row at once (muted text, no colour) and unticking restores it; the box stays at full contrast so it can be unticked, and the checkbox state, not the grey, carries the meaning. The mark is saved per symbol and is this page's own (the screener does not use it). A failed save puts the box and the row back and says "Couldn't save the change; the box is back where it was." (a line under the page title; the box is disabled while its save is in flight, so a fast second click cannot race it). The greyed text uses the page's muted text colour, so it reads like other secondary text in light and dark themes. If the marks cannot be loaded the page shows every box unticked with "Full-position marks couldn't be loaded." Shown in `tickers_normal.html`.

### 6.1b Invested (Story 30)
The `individual` table alone has an "Invested" column between PEG and Full Position: the total dollars put into the ticker ($1,500, or $1,500.50 when there are cents), or "—" when none is recorded, followed by a pen (✎, tooltip "Edit the amount invested in {SYMBOL}", label "Edit invested amount for {SYMBOL}"). Clicking the pen turns the cell into a number box with Save and Cancel; Enter saves, Esc cancels, and an empty box clears the amount. The box is disabled while it saves, then the cell is redrawn from the server's reply and the pen takes focus; a failure keeps the box open and says "Couldn't save the amount: {reason}." under the page title ("Enter an amount from 0 to 1,000,000,000." for a bad amount, "storage error" when Redis fails). Text the browser cannot read as a number ("1e", "-") is refused with "Enter an amount in dollars." and clears nothing; only a truly blank box clears the amount. Removing a ticker from the group clears its amount, so a ticker added back starts with "—". If the amounts cannot be loaded the cells read "n/a", the pens are disabled and the page says "Invested amounts couldn't be loaded." (so a blank view is never saved over a real total). A greyed (Full Position) row greys this cell too. A background refresh of a group is skipped while an amount editor is open in it (or its save is in flight), so the editor and what you typed are never redrawn under you; that group's prices update on the next load. Shown in `tickers_normal.html` (the pen, the Invested column on the Individual table).

### 6.1c Verdicts (Story 34)
Each group label has a pill (Discount green, Fair grey, Overpriced red; the word is always on it). Hovering or focusing it shows a plain-language summary of how the group reads against its own past year, for example "Most of this group is trading near the high end of its own 52-week ranges, richer than it has been over the past year", plus the tickers standing out as cheaper or richer; no median price and no ticker count. Every table has a **Verdict** column before the Invested and Full Position cells with the same pill per ticker; its tip says what the word means ("Cheaper than / In line with / Richer than its own past year and its peers") and the numbers behind it. The column is not sortable. A grey "Not scored" or "Not judged" pill replaces the verdict when there is nothing to compare, and a loading or errored row shows a dash. The tip is a real element shown on hover and on keyboard focus (the pill is focusable); on a touch screen, tapping the pill focuses it. For an Individual stock the tip always names its PEG and its quality with the figures they rest on (ROE, net margin, revenue growth, EPS growth, debt/equity), including "PEG not available (earnings are shrinking)" and "quality mid-pack"; a row marked Full Position greys its contents but keeps the tip working.

### 6.2 Task flow
1. Open → news and every group's table render from cache at once, verdicts included; each group then refreshes on its own.
2. Read each group's pill, then scan the Verdict column for Discount: candidates for this week. Hover a pill for the reason.
3. In the table see price, change, where the price sits in its range (bar), and % in range.
4. Optionally sort a table by Ticker or % in Range to rank candidates.
5. Maintain: type a symbol under a group and Add; click × and confirm to remove.

Common wrong turn: expecting group management (new group) — there is no control and no message saying so (Q2).

### 6.3 States

| State | When | What is seen | Can do |
|---|---|---|---|
| Normal | cache present | all sections populated | sort, add, remove |
| Loading row | ticker has no cached snapshot yet | symbol + "Loading…" + × | remove |
| Row error | live fetch failed and nothing cached | symbol + "Unable to load data." + × | remove |
| Saved row | live fetch failed, cache exists | the old numbers and a "Saved" flag by the ticker; hover or focus shows the date and time they are from (and that the verdict uses them) | read |
| News loading / empty | first load / no headlines | "Loading market news…" / "Market news unavailable." | — |
| Empty watchlist | no groups at all | header and footer only: **no group, no add form, no message** | nothing (F6) |
| Very many tickers | large group | long table; one group refresh may take several seconds | scroll; sort |
| Narrow window | < 700px | tables scroll horizontally inside their block | scroll |

Mockups: `tickers_normal.html`, `tickers_loading.html`, `tickers_error_and_saved.html` (an errored row, a loading row and a "Saved" row), `tickers_empty.html`.

### 6.4 Wireframes

Normal (fund group and individual group):

```text
[ Indicator Digest ] [ Ticker Dashboard ]
TICKER DASHBOARD                                   Checking for updates…
┌ MARKET NEWS ─────────────────────────────────────────────────────────────┐
│ • Fed officials signal patience on further rate moves · Reuters           │
└──────────────────────────────────────────────────────────────────────────┘
STOCKS [Overpriced]      ← hover: "Most of this group is trading near the high end…"
 Ticker▲   Price    Change          52-Week Range      % in Range  Verdict
 SPY      $762.60  +3.10 ▲0.41%   ▓▓▒▒░░●  $560 $766     0.5%     [Overpriced]  ×
 IVW      $118.20  -0.40 ▼0.34%   ▓▒▒░░░●  $90  $120     1.5%     [Fair]        ×
 [ Add ticker…            ] [Add]
INDIVIDUAL     (extra columns: Market Cap · P/E · PEG · Invested, only for this group; every group has Full Position, 6.1a)
 NVDA ...                                                   $4.60T 28.5 0.50   ×
 AMD    Loading…                                                              ×
```

Mark the one primary action: none is dominant; **Add** is the only button. Reading order: news → tables (pill, then Verdict column).

### 6.5 Interaction spec

| Element | Action | Result | Keyboard | Announced as |
|---|---|---|---|---|
| Header "Ticker" / "% in Range" | click | sort that table asc, click again desc; missing values always last; arrow ▲/▼ shows direction | **not reachable today (F2)** | should be a button with `aria-sort` |
| Add field + Add | type symbol, submit | symbol uppercased and posted; a "Loading…" row appears at the bottom of that group; that group re-checks; field clears | type, Enter | should announce "{SYMBOL} added to {group}" (F4) |
| Add, invalid or duplicate | submit | browser `alert(error text)`; field keeps its text | Enter | alert dialog |
| × on a row | click | native confirm "Remove {SYM} from {group}?"; on OK the row disappears immediately; on failure it is re-inserted and an alert says why | Tab to ×, Enter/Space | button "Remove {SYM}" |
| × then Cancel | — | nothing changes | Esc/Cancel in dialog | dialog |
| News headline | click | opens in a new tab | Enter | link |
| Group refresh landing | automatic | that group's block is replaced (its sort resets) | — | nothing (F4) |

**Focus.** After a remove, the focused × is deleted and focus falls to the page (F3). After Add, focus stays in the (now empty) field, which is right.
**Undo.** Remove has a confirm but no undo; re-adding the symbol is the recovery. Add has no undo (remove it).
**Shortcuts.** None; not needed for this volume.

### 6.6 Content

| Where | Text |
|---|---|
| Title | Ticker Dashboard |
| Group headings | derived from config keys: "Stocks", "Bonds", "International", "Sector", "Individual" |
| Columns | Ticker · Price · Change · 52-Week Range · % in Range (· Market Cap · P/E · PEG for Individual) · Verdict (· Invested for Individual) · Full Position (6.1a, 6.1b) |
| Row states | Loading… · Unable to load data. · n/a |
| Add | placeholder "Add ticker…", button "Add"; max length 10 |
| Remove | tooltip "Remove {SYM} from {group}", confirm "Remove {SYM} from {group}?" |
| Errors | `alert()` with the server's message, or "Failed to add {SYM}." / "Failed to remove {SYM}." |
| Verdicts | pills Discount · Fair · Overpriced · Not scored · Not judged; tips as in 6.1c; footer line "Verdicts compare each ticker with its own 52-week range and its group; they are not an estimate of what a ticker is worth, and not personalized financial advice." |
| Footer | Price, change, and 52-week range from Finnhub · free tier may lag by up to ~20 minutes |

## 7. Accessibility and platform notes

- **Keyboard-only path, today:** nav links, Add fields and buttons, and × buttons are reachable; **sorting is not** (F2).
- **Colour:** meaning is never by colour alone (Section 3). One exception to check: group badges rely on the word plus colour, which is fine; the range bar's mid-point has no label, which is acceptable because low/high are printed.
- **Smallest window:** not measured (needs a browser). By construction the ticker tables scroll sideways inside their block rather than the page, . **There is no `<meta name="viewport">`** (F5), so a phone shows the desktop width, zoomed out.
- **Text scaling:** sizes are in px, so browser *zoom* works but a text-only size preference does not scale the 11-13px text. Prefer `rem` (Q5).
- **Themes:** light and dark by system preference; **high contrast / forced colours not handled** (F10); the dark theme has the contrast failures in F1.
- **Reduced motion:** the pulse is not gated (F9).
- **Platform conventions:** browser-native `confirm`/`alert` dialogs for remove and errors — acceptable for a single user, but they block, cannot be styled, and are unreliable in some embedded browsers (Q3).

## 8. Findings in the built UI

Severity per the review rubric. **Basis:** read from the templates and CSS and contrast-computed from the colour values; **not yet seen in a real browser or screen reader** (no browser is available in this environment). Items marked ◆ should be confirmed by eye first.

| # | Severity | Finding | Evidence |
|---|---|---|---|
| F1 ◆ | **Blocker for dark mode** | Read card badges use fixed **light** tinted backgrounds set inline, while text inherits the theme's text colour. In dark theme that is `#e2e8f0` on `#dcfce7`/`#fee2e2`/`#e2e8f0`: **1.1 / 1.0 / 1.0 : 1** — unreadable. The group labels use a fixed `#334155` (1.7 : 1 on the dark page), and up/down colours `#15803d`/`#b91c1c` on the dark card are 2.9 / 2.3 : 1. | `directional_style` backgrounds in `email_template.py`; `.category-label` colour in `dashboard.css`; contrast computed from those values |
| F2 | Should fix | Sort headers are `<th>` elements with a click handler: no focus, no key access, no `aria-sort`. A keyboard or screen-reader user cannot sort. | `page_template.py` sortable `th`; no `tabindex`/button |
| F3 | Should fix | Remove: focus is lost when the row is deleted; the × target is tiny (14px glyph, 2px padding); the blocking native `confirm`/`alert` is the only feedback. | `remove-ticker` CSS and script |
| F4 | Should fix | Background updates are silent to assistive tech: no `aria-live` on "Checking for updates…" or on patched sections; Add gives no confirmation message. | no `role="status"`/`aria-live` anywhere |
| F5 | Should fix | No viewport meta tag, so phones render at desktop width. The page is now hosted and reachable from a phone, though the requirement is desktop-first. | `<head>` in both templates |
| F6 | Should fix | Empty watchlist is a dead end: no group exists, so there is no add form and no message; the app's own recovery instruction ("re-add tickers in the editor") cannot be followed. | `_render_ticker_groups` returns nothing for `{}` |
| F7 | Should fix | Indicator tables have no header row, caption or accessible name; group/category labels are `<p>`, not headings; the active nav pill has no `aria-current="page"`. | `_render_table_section`, `_render_nav` |
| F8 | Nit | Sparkline `aria-label` is "trend line" — it says nothing. Better: "12-month trend, rising from 4.0 to 4.2". | `_render_sparkline_svg` |
| F9 | Nit | The pulse animation ignores `prefers-reduced-motion`. | `dashboard.css` |
| F10 | Nit | No forced-colors support; verdict colours and the range-bar gradient disappear or clash in Windows high-contrast mode, leaving only text (which still carries the meaning). | no `@media (forced-colors)` |
| F11 | Nit | Muted text on the page background is 4.3 : 1 (13px), under 4.5; "day(s)" reads as unfinished. | `--muted` on `--bg`; countdown wording |

**Looks good:** instant cached render with in-place patching; per-group independent refresh; never-colour-alone for change and range; clear row-level Loading / error wording; the read card's honest "No read yet" and "computed" labels; verdict pills with the reason on hover; consistent card/spacing system.

## 9. Decisions

| Decision | Recommendation | Runner-up, and why rejected |
|---|---|---|
| Fix dark-theme contrast (F1) | Make verdict backgrounds and text theme tokens (light and dark pairs) and give `.category-label` a token | Force the light theme only: simplest, but ignores the system setting the page already half-supports |
| Make sort keyboard-accessible (F2) | Render the two sort headers as `<button>` inside `<th>` with `aria-sort` | Keep `<th>` and add `tabindex=0`+key handler: works, but a native button gives focus, Enter and Space for free |
| Replace `confirm`/`alert` for remove and errors | Keep `confirm` for the destructive step; replace `alert` with an inline, announced message under the group | Custom modal for both: more code and focus management for one confirmation a month |
| Remove undo | Keep confirm-only; no undo toast | Undo toast: nicer, but a symbol is trivially re-added and the editor is rare |
| Mobile | Add the viewport meta now so the hosted page is usable on a phone, and keep the desktop-first scope | Full responsive redesign: out of scope per the requirements (no mobile app, desktop first) |
| Empty watchlist | Show a message under the title: "Your watchlist is empty. Groups are created in the configuration store; add tickers once a group exists." plus the group name guidance | Build group creation in the UI: it is backlogged on purpose (Section 5 of the requirements) |
| Text units | Move font sizes to `rem` when next touching the stylesheet | Leave px: works with zoom, fails text-only scaling |

## 10. Open questions for the investor

- **Q1 — Staleness (decided).** No page-wide freshness badge (an earlier decision, recorded in `CLAUDE.md`). A row whose refresh failed carries a "Saved" flag with the saved date and time on hover (Story 36); a row that refreshed shows nothing.
- **Q2 — Dead ends.** The two empty states (no indicator history, no groups) tell the person nothing. Is the one-line explanation in Section 9 the right amount, or should recovery instructions stay out of the UI?
- **Q3 — Dialogs.** Are you content with native `confirm`/`alert`, given they block and cannot be styled?
- **Q4 — Sign-out and help.** Do you want a visible sign-out link and a short "what these verdicts mean" explanation on the Ticker Dashboard? Today `/logout` is unlinked and the method (rank in own 52-week range, quality rank) is only in the docs.
- **Q5 — Text size.** Do you read these pages with the browser's text size raised? If so the `px` → `rem` change moves up.
- **Q6 — Verdict wording.** "Discount / Fair / Overpriced" sit beside the macro read's "Improving / Mixed / Weakening". Keep two vocabularies, or align them?

## 11. How to check it

Run against the live local app (`python3 src/web/app.py`, sign-in unset) or the mockups in `docs/ux_mockups/`.

1. **Instant render.** Load `/` and `/tickers` with the network throttled; confirm content appears before "Checking for updates…" clears. *Expected:* cached numbers visible immediately; the indicator disappears when the check ends.
2. **Failure keeps the old value.** Block `/api/tickers/groups/*` in dev tools and reload. *Expected:* rows keep their numbers; no error text where a value existed.
3. **Keyboard.** Tab through `/tickers`. *Expected today:* nav, Add fields, Add buttons, × buttons; the sort headers are skipped (F2).
4. **Dark theme.** Set the OS to dark. *Expected today:* the read card text is unreadable (F1). After the fix: body text at least 4.5 : 1 on every card.
5. **Sort.** Click "% in Range" twice. *Expected:* ascending then descending; ▲/▼ shown; rows with no value stay last.
6. **Remove.** Click × → Cancel; then × → OK. *Expected:* nothing; then the row disappears at once and is gone after reload. Force a failure (stop Redis access); *expected:* the row returns and a message explains.
7. **Empty watchlist.** Use `tickers_empty.html` or an empty `ticker_config`. *Expected today:* no message (F6).

Screenshots the review still needs from a real browser:
- [ ] `/` normal, computed-only, no-read-yet, light and dark
- [ ] `/tickers` normal, light and dark, at 1200px and 360px
- [ ] a row error, a loading row, and a failed remove
- [ ] Windows high-contrast and 200% text size

States generated here as fixture mockups: digest normal / computed-only / no-read-yet / empty, and the digest with the reads-over-time card; tickers normal / loading / error and saved / empty. **Not generated, and why:** dark theme and high contrast (the mockups follow the OS preference, so they need a real browser to flip), live failure of a refresh (needs the running app), and anything screen-reader specific.

## 12. Screen spec — Small & Mid-Cap Screener (`/screener`) — built (Stories 23 to 26)

Stories 23-26. Built.

Status: the table, detail row, lists, live prices, triage actions and notes (Stories 23 and 24), the Filters panel (Story 25) and the earnings dates and Review due marker (Story 26, 12.15) are agreed and built. Follows the screen map (Section 2) and the style guide as built (Section 3). Mockups: `docs/ux_mockups/screener_*.html` (fixture data; list in 12.13). Anything that is a question is in 12.12.

**12.1 Goal and context.** The investor reviews each candidate, researches it elsewhere, and decides keep or discard. *Goal:* "Narrow a few dozen scored names down to the handful worth a closer look, and not see a rejected one again." *Today:* a spreadsheet with no memory of what was rejected. *Success:* all of the day's New candidates triaged in a sitting, with every decision still there next month.

**12.2 Scope.** In: table, tabs, sort, detail row, shortlist, dismiss with undo, notes, filter settings (12.14). Out: charts, export, any way back from the Ticker Dashboard to the shortlist. Promote (12.16) adds a shortlisted name to the Ticker Dashboard watchlist. Must not undo: no color-only meaning, no persistent freshness badge on the digest page (this page's data-age line is its own and is required here because scores change only by job).

**12.3 Place in the app.** Third nav pill beside Indicator Digest and Ticker Dashboard. Leads to external filings (opens in a new tab). Way back: nav or the browser Back button; the active tab is kept in the URL (`?tab=shortlisted`) so Back returns to it.

**12.4 Task flow.** (1) Open `/screener`; the New tab is showing. (2) Scan score and the key numbers. (3) Open a row's detail (the arrow at the start of the row) to see free cash flow and share count as three-year bar charts, all filter results, the filing links and the note field. (4) Research outside the app. (5) Write a note; Shortlist or Dismiss. (6) Repeat down the list. (7) The Shortlisted tab is the working list that remains. *Common wrong turn:* dismissing by mistake; Undo and the Dismissed tab are the recovery.

**12.5 States.**

| State | When | Sees | Can do |
|---|---|---|---|
| Never run | `screener_state` absent | "The screener hasn't run yet. See the README, Automation, to run the first pass." | nothing |
| Initial pass running | `initial_pass_done` false | progress line plus whatever is scored so far | everything below |
| Normal | data present | table for the active tab; price cells show "Loading…" until each batch of quotes lands (a quote under 5 minutes old is used without a fetch); "Checking for updates…" shows top right until every batch has landed, failed or run past 60 seconds, and not at all on the Dismissed tab, which fetches no prices | all actions |
| Quote failed | a row's quote fetch failed | the last cached quote with "as of {time}"; with none cached, "n/a" | as normal |
| Dismissed tab | always | "—" in the price cells; no live data is fetched; Market Cap, P/E and the other figures are refreshed after the company reports like every other row, and the detail row shows the date | restore |
| Dismissed and improved | a dismissed name now passes the filters and either did not before or its score rose by 10 or more | a line above the table "2 dismissed names have improved since you dismissed them." and, under the company name, "▲ Improved since you dismissed it (score 62 → 78)"; the name stays in Dismissed | open the detail, Restore |
| Tab empty because of your filters | the New tab has no rows but names are hidden by the filters | "{n} names are hidden by your filters. Open Filters to change them." | open Filters |
| Tab empty | tab has no rows | New: "Nothing left to review." Shortlisted: "Nothing shortlisted yet. Use Shortlist on a row you want to research." Dismissed: "Nothing dismissed." | switch tab |
| Stale | the job's `last_run_at` is more than 2 days old | line turns "The nightly run hasn't completed since 14 Oct. Data may be out of date." | as normal |
| Data check | any flagged symbols | a collapsed "Needs a data check (N)" under the table, rows with every reason (several are joined with " · ") | open, Dismiss, Shortlist |
| Error | a Redis read of the candidates, the universe state, the statuses, the notes or the settings failed | "Couldn't load the screener data (storage error). Reload to try again." The tab counts show "—" and no table is drawn | reload |
| Prices failed | a whole quote batch failed (network, 5xx, or an expired sign-in) | rows in the batch show "n/a"; a line reads "Prices couldn't be loaded. Reload to try again." (or "Your session expired. Sign in again." with a link) | reload, sign in |
| Note too long | the note field reaches 2,000 characters | a counter "1,980 / 2,000" appears from 1,900; past the limit "That note is too long (max 2,000 characters)." and Save note stays disabled | edit |
| Editing a note | note text differs from the saved text | "Unsaved changes" beside the field and the Save note button enabled; the button is disabled when the text matches what is saved | Save note |
| Saving a note | after Save note | "Saving…", then "Saved" (button disabled again) or "Not saved. Retry" | retry |
| Very many rows | over 200 in a tab | the 200 highest scores are drawn, "Showing the 200 highest scores of 340. Tighten your filters or dismiss names to see the rest." | filters, dismiss |
| Narrow window | under 720px | table scrolls horizontally inside its card; symbol column sticks | scroll |

**12.6 Wireframe (normal, New tab).**

```text
 INDICATOR DIGEST   TICKER DASHBOARD   [SMALL & MID-CAP SCREENER]

 Small & Mid-Cap Screener
 Last nightly run 19 Oct 2026 · 40 pass all filters · ownership % is not screened

 [ Filters ▸ ]  28 names shown · 12 hidden by your filters          (the count appears on the New tab only)
 [ New (28) ]  Shortlisted (6)  Dismissed (7)

 ▸ Ticker  Score  Price   Change         52-Week Range     % in Range  Mkt Cap  P/E   PEG   Next Earnings  Actions
 ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 ▸ MITK   87     $10.52  ▲ +0.4 (3.9%)  $8.1 ▓▓▓▓▒░ $14.9   -29.4%      $4.8B    24.1  1.8    Nov 5 2026     [Shortlist] [Dismiss]
   Mitek Systems
 ▸ CLFD   81     $36.90  ▼ -0.2 (0.5%)  $29 ▓▓▒░░░ $51      -27.6%      $5.2B    n/a   n/a    Nov 12 2026    [Shortlist] [Dismiss]
  ...
 ▸ Needs a data check (3)

 Opened row (▾):
  MITK  Mitek Systems · 10-K filings ↗ · Quote ↗
  Key figures        ROI 18% · Debt/equity 0.1 · FCF $54M · Dilution +0.8%/yr · Revenue growth +12%
  Free cash flow     bar chart: FY23 $31M · FY24 $30M · FY25 $54M (values printed on the bars)
  Shares (weighted)  bar chart: FY23 41.2M · FY24 41.6M · FY25 41.8M
  Filters            ✓ Net margin  ✓ FCF  ✓ Debt/equity  ✓ Dilution  ✓ ROI  ✓ Not stale
  Note  [__________________________________________]  [Save note]  Saved

 Dismissed tab: same columns; price cells show "—"; the only action is [Restore]; the dismissal date is in the detail row.
 A row that has a saved note shows "✎ Has a note" under the company name, so notes are findable without opening every row.
```

Primary action per row: **Shortlist**. Dismiss is a quieter secondary button.

**12.7 Visual notes.** The table has only the Ticker Dashboard `individual` table's data columns (plus Next Earnings and the actions); Score is its own column after Ticker and every other figure is in the detail row's Key figures, so the table fits the 1280px page. The ticker column is capped at about 100px: a long company name is cut with an ellipsis (the full name is its tooltip) and flags wrap. Lead with the table: no lead card, since there is no prose here. Reading order: ticker with its score, price and range, then the market figures; the columns match the Ticker Dashboard's `individual` table so the two read the same. Compact list density like the ticker tables; below about 900px the table scrolls inside its card. The tab already says which status a row has, so rows carry no status word; the Dismissed tab shows the dismissal date in the detail row. Departures from the style guide and the other pages: the page is 1280px wide; the Ticker, Change, % in Range, Market Cap, P/E and PEG headers sort (the Ticker Dashboard sorts only Ticker and % Off High), and the default order is by Score; the Dismiss button is neutral, not the red `×` used for removing a ticker, because it is reversible.

**12.8 Interaction spec.**

| Element | Action | Result | Keyboard | Announced as |
|---|---|---|---|---|
| List link (New, Shortlisted, Dismissed) | click | loads that status's rows at `?tab=` | Tab to it, Enter | "New (28), current page" |
| Column header (Ticker, Score, Change, % in Range, Market Cap, P/E, PEG, Next Earnings) | click anywhere on the header cell, arrow included, or Enter/Space on its button | sorts that column ascending, again for descending; the arrow beside the label shows the direction (▲ ascending, ▼ descending, ⇅ not sorted); blanks last. The default order is Score, highest first, with no header marked. Live quotes patching in never re-sort the table | Enter/Space on header button | "Sorted by Score, descending" |
| Row disclosure `▸` | click | opens or closes the detail row | Enter/Space | "MITK details, expanded" |
| Shortlist | click | row moves to Shortlisted; the New count drops | Enter/Space | "MITK shortlisted" |
| Dismiss | click | row leaves; "Dismissed MITK. Undo" appears for 10 s | Enter/Space | "MITK dismissed. Undo available." |
| Promote (Shortlisted tab) | click | adds the symbol to the Ticker Dashboard's Individual table; the row greys at once and the button reads Promoted ✓ (disabled); a failed save puts both back and says why | Enter/Space | "MITK promoted to the watchlist" |
| Undo | click | row returns to its place | Enter on the live toast, or `U` | "MITK restored" |
| Restore (Dismissed tab) | click | row returns to New | Enter/Space | "MITK restored to New" |
| Note field | type | enables Save note; shows "Unsaved changes" | Type | "Unsaved changes" |
| Save note | click | saves; shows Saved and disables the button again, or "Not saved. Retry" | Enter/Space | "Note saved" / "Note not saved" |
| Filing links | click | open in a new tab | Enter | "10-K filings, opens in a new tab" |

*Focus:* after Shortlist or Dismiss, focus moves to the first action button of the next row on that tab (Shortlist on New, Promote on Shortlisted, Restore on Dismissed), or of the previous row if it was last, or to the list links if the list is now empty; after Undo, to the restored row's first action button. `Esc` closes an open detail row. *Undo and cancel:* a status change is always reversible; there is no "delete" anywhere on the page. *Shortcuts:* none, except `U` for undo while the toast is showing and no text field has focus (so typing a note never triggers it). Changing tabs or leaving the page with an unsaved note asks first ("You have an unsaved note. Leave this page?").

**12.9 Content (final wording).**

| Where | Text |
|---|---|
| Page title | Small & Mid-Cap Screener |
| Data line | Last nightly run {date} · {n} pass all filters (counted across all three tabs) · ownership % is not screened. With no data: "No scores yet". On an error: "Scores unavailable" |
| Filters summary (above the tabs, on every tab) | Filters ▸ (opens the panel, 12.14). On the New tab only it adds: {n} names shown · {m} hidden by your filters (n is the New tab's row count) |
| Improved flag | ▲ Improved since you dismissed it (score {then} → {now}) · if it did not pass when dismissed: ▲ Now passes your filters (score {now}) · count line above the table: {n} dismissed names have improved since you dismissed them. ("1 dismissed name has improved since you dismissed it." for one; no line for none.) A name under "Needs a data check" counts as not passing. |
| Data age (detail row) | Figures refreshed {date} · Quote fetched {time}. On a shortlisted or dismissed row: Last checked {date} · Last reported {date} |
| Next earnings | {date}, or — when unknown. A date shows (may be out of date) after it was fetched over 10 days ago or when it is already past. The column header's tooltip says it is projected until the company announces |
| Review due | ⏱ Review due (under the company name, with a tinted row) · tab links: Shortlisted ({n}) · {k} due · if the dates cannot be loaded: Earnings dates couldn't be loaded; Review due uses the 100-day rule for now. |
| Progress | Initial screen in progress: {done} of {total} symbols checked. |
| List links | New ({n}) · Shortlisted ({n}) · Dismissed ({n}) |
| Buttons | Shortlist · Dismiss · Restore · Promote · Promoted ✓ · Save note · Undo |
| Promote tooltip | Add {SYMBOL} to the Individual table on the Ticker Dashboard. The row turns grey while it is there, and normal again if you remove it from that table. (Promoted ✓: {SYMBOL} is in the Individual table on the Ticker Dashboard. Remove it there to promote it again.) · screen-reader labels: Promote {SYMBOL} · {SYMBOL} is promoted · announcement after a promotion: {SYMBOL} promoted to the watchlist · focus moves to the row's Dismiss button · errors: Couldn't add {SYMBOL} to the watchlist: {reason} · Couldn't read your watchlist; Promote buttons may be out of date. |
| Dismiss toast | Dismissed {SYMBOL}. Undo |
| Fails now | No longer passes: {filter} {value} (for example "Debt/Equity 0.8") |
| Flag reasons | Possible stock split (shares rose {x}x in one year, {year}) · Possible reverse split (shares fell to {x}x in one year, {year}) · Capex not reported · Fewer than two years of share data · No operating cash flow reported · Cash flow reported in {currency}, not scored yet · Latest annual figures are more than 18 months old · IFRS filer, not scored yet (a name with several reasons shows all of them, joined with " · ") |
| Blank value | n/a |
| Note placeholder | Notes for your research (not shared) |
| Save errors | Not saved. Retry · Couldn't save the change; the row is back where it was. · That note is too long (max 2,000 characters). |
| Filter errors | Enter a number between {min} and {max}. (beside the field) · The minimum must be below the maximum. · Couldn't save the filters. Nothing was changed. |
| Prices | Prices couldn't be loaded. Reload to try again. · Your session expired. Sign in again. · n/a · as of {time} |
| Hidden by filters | {n} names are hidden by your filters. Open Filters to change them. |

**12.10 Accessibility and platform.** Keyboard-only path: nav, list links, headers, then row by row (disclosure, Shortlist, Dismiss). Meaning not by color: a filter result is ✓ or ✗ plus its name; a status is a word. The current list link is bold and underlined, not only filled, and carries `aria-current`. Undo toast is an `aria-live="polite"` region. Smallest window: table scrolls inside its card. Light and dark follow the existing tokens; the mockups use only the existing text, card and accent tokens (no new fixed colors). Reduced motion: no animation is added. The existing verdict-color finding (F1 in `ux_design.md`) is not repeated here because no new fixed colors are introduced.

**12.11 Decisions.**

| Decision | Recommendation | Runner-up, and why rejected |
|---|---|---|
| Status model | New / Shortlisted / Dismissed as three lists, each a link to `?tab=` (the built page marks the current one with `aria-current`, not ARIA tabs) | One list with a status filter: counts and "where did it go" are less clear. Script-driven ARIA tabs: they would need arrow-key handling and a panel per tab, and the URL already keeps the list across Back |
| Dismiss | immediate with Undo plus a Dismissed tab | Confirm dialog as on `/tickers`: slows the main loop of triaging dozens of rows, and Undo makes it unnecessary |
| Detail | an expandable row | A separate detail page: loses the list and sort position |
| Notes | explicit Save note button, enabled only when the text has changed | Autosave on blur: no extra click, but a note can save by accident and there is no clear "I'm done" moment; the investor preferred the button |
| Live refresh | only price, change, range and % in range, patched into the cells in place | Re-render the whole table like `/tickers`: it would reset the sort and could drop an unsaved note |
| Storage | status and notes in their own hashes | Fields on the candidate record: a rescore could overwrite a decision |

**12.12 Risks and open questions.**
- Decided: "Needs a data check" rows are shown, collapsed under the table, and can be shortlisted or dismissed.
- Decided: price and change are fetched when the page opens (the 52-week range is the stored one, as old as the last refresh, up to a quarter; % in range is computed from the live price and the stored range), in batches of 25 so a long list fills in progressively, patched in place, and cached for 5 minutes so a reload costs nothing. The nightly job supplies the rest. Dismissed rows get no live data.
- Decided: the thresholds are settings on the page (Story 25, Section 12.14), not code constants only.
- Decided: IFRS filers appear under "Needs a data check" with the reason "IFRS filer, not scored yet".
- Decided: the return column is ROI (Finnhub's `roiTTM`), not ROIC.
- Risk: a Finnhub outage with no cached quote leaves the price cells at "n/a"; the stored data still shows. Risk: if the first scheduled run finds under ~15 or over ~150 names at the default filters (the 10% sample suggests about 20 to 30), the layout needs revisiting.
- Risk: screen-reader behavior of the undo toast needs a real run.

**12.13 How to check it.** (1) With fixture data of 5 candidates, open `/screener`: New shows 5 rows sorted by score. (2) Click Dismiss on row 1: it leaves, the toast shows, Undo restores it in place. (3) Dismiss again, wait, open Dismissed: it is there; Restore returns it to New. (4) Shortlist two; the Shortlisted tab shows 2. (5) Type a note: Save note enables and "Unsaved changes" shows; click it: "Saved", the button disables, and after a reload the note is there and the row shows "✎ Has a note". (6) Change the fixture score of a dismissed symbol and rerun the render: it stays dismissed. (7) Make a shortlisted symbol fail a filter: it stays, with "No longer passes". (8) Disconnect Redis: the error state shows, not an empty table. (9) Keyboard only, tab through all of it. (10) Browser-script checks (the suite has no JavaScript harness): with a stored 52-week high below the live price, confirm the patched % in Range cell shows 100%; click a column header to sort, click again to reverse it, and confirm blanks sort last; switch tabs and confirm `?tab=` changes and Back returns to the previous tab; block the quote route and confirm the rows show "n/a" with "Prices couldn't be loaded. Reload to try again.", then expire the session and confirm "Your session expired. Sign in again."; with a cached quote older than 5 minutes and the route blocked, confirm "as of {time}"; let quotes patch in while sorted by Score and confirm no row moves; Dismiss a row and wait 10 seconds, the Undo notice disappears and the row stays gone; type a note and press `U`, nothing is undone; edit a note then click another tab or reload, the leave-page prompt appears; after Shortlist, Dismiss, Undo and Move to New, focus lands as 12.8 says; Move to New on a Shortlisted row returns it to the New tab. *Mockups generated (fixture data, `docs/ux_mockups/`):* `screener_normal`, `_loading` (first paint and initial-pass progress), `_detail_open`, `_note_editing`, `_quote_failed`, `_prices_failed`, `_shortlisted`, `_dismissed`, `_undo_toast`, `_data_check_open`, `_filters_panel`, `_stale`, `_empty_filtered`, `_never_run`, `_error`. *Not generated, and why:* the empty Shortlisted and Dismissed tabs and the 200-row cap (same layout as the normal page with one line of text), the narrow window, dark theme, high contrast and large text (they need a real browser, since the mockups follow the OS setting), and the screen-reader behavior of the list links, toast and filter panel (needs a real run). The built states were regenerated from `screener_page.py` with fixture data; `_filters_panel` is the same page with the Filters panel open.

**12.14 Filter settings (Story 25).** *Goal:* "Loosen or tighten the list and see what changes, without touching the names I've already decided on."

A "Filters" button above the tabs opens a panel; the table stays visible below it.

```text
 Filters  ▾                                              28 names shown · 12 hidden by your filters
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │     Market cap (always on) from [1200 ] $M   to [22700 ] $M                             │
 │ [x] Net margin            above [ 0 ] %                                                │
 │ [x] Free cash flow        above [ 0 ] $M (latest fiscal year)                          │
 │ [x] Debt / equity         at most [ 0.5 ]                                              │
 │ [x] Annual dilution       at most [ 5 ] %                                              │
 │ [x] Return on investment  at least [ 5 ] % (ROI)                                             │
 │ [x] Not stale             exclude listed at least [ 10 ] years with revenue growth       │
 │                           below [ 10 ] %                                               │
 │                                                                                        │
 │ With these settings: 34 names (now 28).  14 more names will be fetched tonight.        │
 │ [ Apply ]   [ Reset to defaults ]   Shortlisted and dismissed names are not affected.  │
 └──────────────────────────────────────────────────────────────────────────────────────┘
```

- **Interaction:** editing a value updates the preview count; Apply saves and re-renders the list (Apply is disabled until something changes, and an invalid field shows its message and disables it); unticking a filter greys its fields and switches it off; Reset to defaults asks nothing (it only changes the form, and Apply makes it real).
- **States:** the preview is "Counting…" while it loads and "Couldn't count. Apply will still work." if it fails; a rejected value shows its message beside the field and disables Apply; a failed save says "Couldn't save the filters. Nothing was changed."; a saved change is announced "Filters applied. 34 names shown."
- **Keyboard and screen reader:** the panel is a disclosure (`aria-expanded`), each row is a labelled group, and the preview is an `aria-live="polite"` region.
- **Mockups:** all rendered from the current template with fixture data, including the Filters button and the open panel.
- **Decision:** one panel on the page, not a separate settings screen, so the effect is visible next to the list (rejected: a settings page, because you could not see what a change did).

**12.15 Earnings dates and Review due (Story 26).** *Goal:* "Tell me when a name I decided on has reported, so I know to run the review." A sortable "Next Earnings" column shows each name's next report date on every tab. On the Shortlisted and Dismissed tabs a row whose company has filed a quarterly or annual report since its last review shows "⏱ Review due" and a tinted row (words and a marker, never colour alone), and the tab link counts them. The New tab shows the date and never flags. Closing the loop is the review itself (the investor asks Claude to re-check the list), which stamps each reviewed name "checked"; there is no button on the page. Changing a status by hand keeps the old stamp, because the figures were not re-read, so a name last reviewed before its company reported shows "Review due" whichever tab it moves to. Shown in `screener_shortlisted.html` (the column and the marker).

**12.16 Promote (Story 29).** On the Shortlisted tab alone, "Move to New" is replaced by "Promote" (the tooltip carries the long description). It adds the symbol to the Ticker Dashboard's `individual` group; while the symbol is in that group the row is greyed with a disabled "Promoted ✓" button, and removing it there makes the row normal again. The Full Position box of 6.1a is the Ticker Dashboard's only. Shown in `screener_shortlisted.html`.
