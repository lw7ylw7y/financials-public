"""The Small & Mid-Cap Screener page ("/screener"): the ranked
candidates in New, Shortlisted and Dismissed tabs, rendered from Redis
alone so it paints instantly. Live prices are not rendered here: the
page's script fetches them in batches from "/api/screener/quotes" and
patches only the price, change, range and % in range cells in place, so
sort order and open detail rows are never disturbed.

Scores and filter results are computed when the page is read, from the
job's raw candidate records and the current settings. A failed Redis
read raises `KvStoreError`; `render_error_page` is what the route shows
for it, never a table that could be mistaken for "no candidates".
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from html import escape

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SCREENER_DIR = os.path.join(os.path.dirname(_WEB_DIR), "screener")
for _path in (_SCREENER_DIR, _WEB_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import page_store  # noqa: E402
import quotes  # noqa: E402
import scoring  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402
from kv_store import KvStoreError  # noqa: E402
from page_template import (  # noqa: E402
    _render_nav,
    script_tag,
    static_url,
    render_change_cell,
    render_market_cap_cell,
    render_pct_in_range_cell,
    pct_in_range,
    render_pe_cell,
    render_peg_cell,
    format_market_cap,
    render_range_bar,
)

logger = logging.getLogger(__name__)

TABS = ("new", "shortlisted", "dismissed")
TAB_LABELS = {"new": "New", "shortlisted": "Shortlisted", "dismissed": "Dismissed"}
MAX_ROWS = 200
STALE_AFTER_DAYS = 2
# A reviewed name with no earnings dates is due for review after this long.
REVIEW_FALLBACK_DAYS = 100
# Earnings dates fetched longer ago than this are shown as possibly out of date.
DATES_STALE_DAYS = 10
FILTER_LABELS = {
    "market_cap": "Market cap",
    "net_margin": "Net margin",
    "free_cash_flow": "Free cash flow",
    "debt_equity": "Debt/equity",
    "dilution": "Dilution",
    "roi": "ROI",
    "not_stale": "Not stale",
}
EMPTY_TAB_TEXT = {
    "new": "Nothing left to review.",
    "shortlisted": "Nothing shortlisted yet.",
    "dismissed": "Nothing dismissed.",
}

# (data-sort key, header label, numeric); Price and 52-Week Range do not sort.
_SORTABLE_COLUMNS = {
    "symbol": ("Ticker", False),
    "score": ("Score", True),
    "change": ("Change", True),
    "pctInRange": ("% in Range", True),
    "marketCap": ("Market Cap", True),
    "pe": ("P/E", True),
    "peg": ("PEG", True),
    "nextEarnings": ("Next Earnings", True),
}


def _latest(by_year: dict) -> float | None:
    return by_year[max(by_year)] if by_year else None


def checked_on(status: dict) -> date:
    """The date a shortlisted or dismissed name was last reviewed: its
    `checked_at`, else the day it got its status."""
    return datetime.fromisoformat(status.get("checked_at") or status["at"]).date()


def review_due(status: dict, dates: dict | None, today: date) -> bool:
    """True when the name has reported since it was last reviewed, or,
    with no `last` report date known, when the review is more than
    `REVIEW_FALLBACK_DAYS` old."""
    checked = checked_on(status)
    last = (dates or {}).get("last")
    if last:
        return date.fromisoformat(last) > checked
    return (today - checked).days > REVIEW_FALLBACK_DAYS


def _usable_dates(entry: dict | None) -> dict | None:
    """`entry` if every date in it parses, else `None`: one malformed
    stored entry is treated as unknown dates instead of failing the page."""
    try:
        if entry:
            datetime.fromisoformat(entry["fetched_at"])
            for key in ("next", "last"):
                if entry.get(key):
                    date.fromisoformat(entry[key])
    except (KeyError, TypeError, ValueError):
        return None
    return entry


def _row(symbol: str, record: dict, score: float | None, result: dict, status: dict | None, note: dict | None,
         dates: dict | None, today: date, dates_known: bool, promoted: bool = False) -> dict:
    metrics = record.get("metrics") or {}
    reviewed = status if status and status.get("status") in ("shortlisted", "dismissed") else None
    fetched = datetime.fromisoformat(dates["fetched_at"]) if dates else None
    return {
        "symbol": symbol,
        "name": record.get("name") or "",
        "record": record,
        "score": score,
        "roi": metrics.get("roi"),
        "debt_equity": metrics.get("debt_to_equity"),
        "fcf": _latest(record.get("fcf_by_year") or {}),
        "checks": result["checks"],
        "flags": record.get("flags") or [],
        "note": (note or {}).get("text") or "",
        "dismissed_at": (status or {}).get("at") if (status or {}).get("status") == "dismissed" else None,
        "improvement": None,
        "promoted": promoted,
        "next_earnings": (dates or {}).get("next"),
        "last_earnings": (dates or {}).get("last"),
        "dates_stale": bool(dates) and ((today - fetched.date()).days > DATES_STALE_DAYS
                                         or bool(dates.get("next")) and date.fromisoformat(dates["next"]) < today),
        "checked_on": checked_on(reviewed).isoformat() if reviewed else None,
        "review_due": bool(reviewed) and review_due(reviewed, dates if dates_known else None, today),
        "failing": _failing_filters(record, result["checks"]),
    }


def _failing_filters(record: dict, checks: dict) -> list[str]:
    """"Debt/Equity 0.8" for each filter the record fails, with its value."""
    metrics = record.get("metrics") or {}
    fcf = _latest(record.get("fcf_by_year") or {})
    values = {
        "market_cap": None if record.get("market_cap") is None else format_market_cap(record["market_cap"]),
        "net_margin": None if metrics.get("net_margin") is None else f"{metrics['net_margin']:.1f}%",
        "free_cash_flow": None if fcf is None else _fmt_money_m(fcf),
        "debt_equity": None if metrics.get("debt_to_equity") is None else f"{metrics['debt_to_equity']:.1f}",
        "dilution": None if record.get("dilution_pct_per_year") is None else f"{record['dilution_pct_per_year']:+.1f}%/yr",
        "roi": None if metrics.get("roi") is None else f"{metrics['roi']:.0f}%",
        "not_stale": "",
    }
    return [f"{FILTER_LABELS[name]} {values[name] if values[name] is not None else 'n/a'}".strip()
            for name, ok in checks.items() if not ok]


def _improvement_text(status: dict, score_now: float | None) -> str:
    if not status.get("passed_at_dismissal"):
        return f"&#9650; Now passes your filters (score {score_now:.0f})"
    return (f"&#9650; Improved since you dismissed it "
            f"(score {status['score_at_dismissal']:.0f} &rarr; {score_now:.0f})")


def _sort_key(row: dict):
    return (row["score"] is None, -(row["score"] or 0), row["symbol"])


def list_for(result: dict) -> str:
    """Where a name with no status shows: "new", "data_check" (flagged),
    "hidden" (in the band but failing a filter) or "out_of_band" (not
    shown anywhere). `result` is `scoring.evaluate`'s."""
    if not result["checks"]["market_cap"]:
        return "out_of_band"
    if result["flagged"]:
        return "data_check"
    return "new" if result["passes"] else "hidden"


def count_new(candidates: dict[str, dict], statuses: dict[str, dict], screen: scoring.ScreenSettings, today) -> int:
    """How many names the New tab would list under `screen`: those with
    no shortlisted or dismissed status that pass every filter."""
    return sum(
        1
        for symbol, record in candidates.items()
        if (statuses.get(symbol) or {}).get("status") not in ("shortlisted", "dismissed")
        and list_for(scoring.evaluate(record, screen, today)) == "new"
    )


def load_view(now: datetime | None = None, watchlist: frozenset = frozenset(), watchlist_known: bool = True) -> dict:
    """Everything the page shows, from Redis. Raises `KvStoreError` if any
    of the candidates, the job's state, the statuses, the notes or the
    settings cannot be read. `watchlist` is the symbols in the Ticker
    Dashboard's `individual` group (the caller reads it); a shortlisted
    row for one of them shows as promoted. `watchlist_known` is False
    when that group could not be read."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    candidates = store.load_candidates()
    state = store.load_state()
    statuses = page_store.load_statuses()
    notes = page_store.load_notes()
    form = settings.load_form()
    screen = settings.to_settings(form)

    try:
        earnings, dates_known = store.load_earnings(), True
    except KvStoreError as e:
        logger.error("screener page: earnings dates unreadable: %s", type(e).__name__)
        earnings, dates_known = {}, False

    scores = scoring.score_candidates(candidates, screen, today)
    rows = {tab: [] for tab in TABS}
    data_check = []
    hidden = 0
    for symbol, record in candidates.items():
        status = statuses.get(symbol)
        result = scoring.evaluate(record, screen, today)
        row = _row(symbol, record, scores.get(symbol), result, status, notes.get(symbol),
                   _usable_dates(earnings.get(symbol)), today, dates_known, symbol in watchlist)
        if status and status.get("status") in ("shortlisted", "dismissed"):
            if status["status"] == "dismissed" and scoring.improved_since_dismissal(status, result["passes"], row["score"]):
                row["improvement"] = _improvement_text(status, row["score"])
            rows[status["status"]].append(row)
        else:
            landing = list_for(result)
            if landing == "new":
                rows["new"].append(row)
            elif landing == "data_check":
                data_check.append(row)
            elif landing == "hidden":
                hidden += 1
    for tab_rows in rows.values():
        tab_rows.sort(key=_sort_key)
    data_check.sort(key=lambda r: r["symbol"])

    last_run = datetime.fromisoformat(state["last_run_at"]) if state.get("last_run_at") else None
    return {
        "state": state,
        "last_run": last_run,
        "run_is_stale": last_run is not None and (now - last_run).days >= STALE_AFTER_DAYS,
        "rows": rows,
        "data_check": data_check,
        "hidden": hidden,
        "improved": sum(1 for r in rows["dismissed"] if r["improvement"]),
        "due": {tab: sum(1 for r in rows[tab] if r["review_due"]) for tab in TABS},
        "dates_known": dates_known,
        "watchlist_known": watchlist_known,
        "passing": len(scores),
        "form": form,
        "now": now,
    }


def _fmt_date(value: datetime) -> str:
    return f"{value.day} {value:%b %Y}"


def _fmt_money_m(value: float) -> str:
    return f"-${-value:,.0f}M" if value < 0 else f"${value:,.0f}M"


def render_quote_cells(symbol: str, record: dict, quote: dict | None, now: datetime) -> str:
    """The four cells that live quotes fill: Price, Change, 52-Week Range
    and % in Range. A quote older than the cache window is shown with its
    age; no quote at all is "n/a"."""
    if quote is None:
        return '<td class="num muted">n/a</td><td class="num muted">n/a</td><td class="muted">n/a</td><td class="num muted">n/a</td>'
    price = quote["price"]
    high = record.get("week52_high")
    as_of = ""
    if not quotes.is_fresh(quote, now):
        quoted = datetime.fromisoformat(quote["quoted_at"])
        as_of = f'<span class="asof">as of {quoted:%H:%M} UTC</span>'
    return (
        f'<td class="num">${price:,.2f}{as_of}</td>'
        f'{render_change_cell(quote.get("change"), quote.get("change_percent"))}'
        f'<td class="range-bar-cell">{render_range_bar(symbol, record.get("week52_low"), high, price)}</td>'
        f'{render_pct_in_range_cell(pct_in_range(price, record.get("week52_low"), high))}'
    )


def _attr(value) -> str:
    return "" if value is None else escape(str(value), quote=True)


def _bars(series: dict[str, float], fmt) -> str:
    """Bars for fiscal years, oldest first, the value printed on each bar
    so the chart never relies on shape or color alone."""
    if not series:
        return '<p class="muted">n/a</p>'
    years = sorted(series)
    values = [series[y] for y in years]
    top, bottom = max(0.0, max(values)), min(0.0, min(values))
    span = (top - bottom) or 1.0
    height, width, gap = 70, 56, 10
    base = height * top / span
    parts = []
    for i, (year, value) in enumerate(zip(years, values)):
        x = i * (width + gap)
        bar = abs(value) / span * height
        y = base - bar if value >= 0 else base
        label_y = max(y - 3, 10) if value >= 0 else y + bar + 11
        parts.append(
            f'<rect x="{x}" y="{y:.1f}" width="{width}" height="{max(bar, 1):.1f}" fill="currentColor" opacity="0.35"/>'
            f'<text x="{x + width / 2}" y="{label_y:.1f}" text-anchor="middle" font-size="11" fill="currentColor">{escape(fmt(value))}</text>'
            f'<text x="{x + width / 2}" y="{height + 28}" text-anchor="middle" font-size="10" fill="currentColor">FY{escape(year[2:4])}</text>'
        )
    total = len(years) * (width + gap)
    summary = ", ".join(f"FY{y[2:4]} {fmt(series[y])}" for y in years)
    return (
        f'<svg class="bars" width="{total}" height="{height + 34}" viewBox="0 0 {total} {height + 34}" '
        f'role="img" aria-label="{escape(summary, quote=True)}">{"".join(parts)}</svg>'
    )


def _render_key_figures(row: dict) -> str:
    """The figures that are not table columns: return on investment,
    debt/equity, free cash flow, dilution, revenue growth and, on the
    Dismissed tab, when it was dismissed."""
    record = row["record"]

    def line(label: str, value: float | None, text: str) -> str:
        return f"<li>{label} <strong>{text if value is not None else 'n/a'}</strong></li>"

    dilution, growth = record.get("dilution_pct_per_year"), record.get("revenue_growth")
    items = [
        line("ROI", row["roi"], f"{row['roi']:.0f}%" if row["roi"] is not None else ""),
        line("Debt/equity", row["debt_equity"], f"{row['debt_equity']:.1f}" if row["debt_equity"] is not None else ""),
        line("FCF", row["fcf"], _fmt_money_m(row["fcf"]) if row["fcf"] is not None else ""),
        line("Dilution", dilution, f"{dilution:+.1f}%/yr" if dilution is not None else ""),
        line("Revenue growth", growth, f"{growth:+.0f}%" if growth is not None else ""),
    ]
    if row["dismissed_at"]:
        items.append(f"<li>Dismissed <strong>{_fmt_date(datetime.fromisoformat(row['dismissed_at']))}</strong></li>")
    return f"<ul>{''.join(items)}</ul>"


def _render_detail(row: dict, column_count: int) -> str:
    record = row["record"]
    symbol = row["symbol"]
    filters = "".join(
        f'<li>{"&#10003;" if ok else "&#10007;"} {escape(FILTER_LABELS.get(name, name))}</li>'
        for name, ok in row["checks"].items()
    )
    flags = "".join(f"<li>{escape(flag)}</li>" for flag in row["flags"])
    flag_block = f'<h4>Needs a data check</h4><ul>{flags}</ul>' if flags else ""
    refreshed = record.get("market_at")
    refreshed_text = _fmt_date(datetime.fromisoformat(refreshed)) if refreshed else "n/a"
    ipo = escape(record["ipo_date"]) if record.get("ipo_date") else "n/a"
    filings = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&amp;CIK={int(record['cik'])}&amp;type=10-K"
        if record.get("cik")
        else None
    )
    filing_link = (
        f'<a href="{filings}" target="_blank" rel="noopener noreferrer">10-K filings <span aria-hidden="true">&#8599;</span><span class="sr-only"> (opens in a new tab)</span></a> &middot; '
        if filings
        else ""
    )
    quote_link = (
        f'<a href="https://finance.yahoo.com/quote/{escape(symbol, quote=True)}" target="_blank" rel="noopener noreferrer">Quote '
        f'<span aria-hidden="true">&#8599;</span><span class="sr-only"> (opens in a new tab)</span></a>'
    )
    return f"""
              <tr class="detail-row" id="detail-{escape(symbol, quote=True)}" hidden>
                <td colspan="{column_count}">
                  <div class="detail-grid">
                    <div><h4>Key figures</h4>{_render_key_figures(row)}</div>
                    <div><h4>Free cash flow</h4>{_bars(record.get("fcf_by_year") or {}, _fmt_money_m)}</div>
                    <div><h4>Shares (weighted)</h4>{_bars(record.get("shares_by_year") or {}, lambda v: f"{v:,.1f}M")}</div>
                    <div>
                      <h4>Filters</h4><ul>{filters}</ul>{flag_block}
                      <p class="muted">Figures refreshed {refreshed_text} &middot; Listed {ipo}</p>{_render_review_lines(row)}
                      <p>{filing_link}{quote_link}</p>
                    </div>
                  </div>
                  <div class="note-block">
                    <label for="note-{escape(symbol, quote=True)}">Note</label>
                    <textarea id="note-{escape(symbol, quote=True)}" class="note-field" data-symbol="{escape(symbol, quote=True)}"
                      placeholder="Notes for your research (not shared)">{escape(row["note"])}</textarea>
                    <p><button class="btn" type="button" data-action="save-note" disabled>Save note</button>
                      <span class="note-state" role="status"></span></p>
                  </div>
                </td>
              </tr>"""


def _render_review_lines(row: dict) -> str:
    """When the figures were last reviewed and when the company last
    reported; a name with no status has been reviewed never."""
    parts = []
    if row["checked_on"]:
        parts.append(f"Last checked {_fmt_date(date.fromisoformat(row['checked_on']))}")
    if row["last_earnings"]:
        parts.append(f"Last reported {_fmt_date(date.fromisoformat(row['last_earnings']))}")
    return f'<p class="muted">{" &middot; ".join(parts)}</p>' if parts else ""


PROMOTE_TOOLTIP = ("Add {symbol} to the Individual table on the Ticker Dashboard. The row turns grey "
                   "while it is there, and normal again if you remove it from that table.")
PROMOTED_TOOLTIP = "{symbol} is in the Individual table on the Ticker Dashboard. Remove it there to promote it again."


def _render_promote_button(name: str, promoted: bool) -> str:
    if promoted:
        return (f'<button type="button" class="btn" data-action="promote" disabled aria-label="{name} is promoted" '
                f'title="{PROMOTED_TOOLTIP.format(symbol=name)}">Promoted &#10003;</button>')
    return (f'<button type="button" class="btn" data-action="promote" aria-label="Promote {name}" '
            f'title="{PROMOTE_TOOLTIP.format(symbol=name)}" '
            f'data-promoted-title="{PROMOTED_TOOLTIP.format(symbol=name)}">Promote</button>')


def _render_actions(symbol: str, tab: str, promoted: bool = False) -> str:
    """Shortlist is the primary action; Dismiss is quieter. The status
    route clears a status, so Restore sets New. On a shortlisted row,
    Promote adds the symbol to the Ticker Dashboard's `individual`
    group; once it is there the button reads Promoted and is disabled."""
    name = escape(symbol)
    def button(action: str, label: str, css: str = "btn") -> str:
        return f'<button type="button" class="{css}" data-action="{action}" aria-label="{label} {name}">{label}</button>'
    if tab == "new":
        buttons = button("shortlisted", "Shortlist", "btn primary") + button("dismissed", "Dismiss")
    elif tab == "shortlisted":
        buttons = _render_promote_button(name, promoted) + button("dismissed", "Dismiss")
    else:
        buttons = button("new", "Restore")
    return f'<td class="actions-cell">{buttons}</td>'


def _render_row(row: dict, tab: str, column_count: int) -> str:
    record = row["record"]
    symbol = escape(row["symbol"])
    sort_attrs = {
        "symbol": row["symbol"],
        "score": row["score"],
        "pctInRange": None,
        "change": None,
        "marketCap": record.get("market_cap"),
        "pe": record.get("pe_ratio"),
        "peg": record.get("peg_ratio"),
        "nextEarnings": datetime.fromisoformat(row["next_earnings"]).timestamp() if row["next_earnings"] else None,
    }
    attrs = "".join(f' data-{key.lower()}="{_attr(value)}"' for key, value in sort_attrs.items())
    quote_row = ' data-quote-row="1"' if tab != "dismissed" else ""
    due_attr = ' data-review-due="1"' if row["review_due"] else ""
    promoted_attr = ' data-promoted="1"' if row["promoted"] and tab == "shortlisted" else ""
    if tab == "dismissed":
        quote_cells = '<td class="num muted">&mdash;</td>' * 4
    else:
        quote_cells = '<td class="num muted">Loading&hellip;</td><td></td><td></td><td></td>'
    note = f'<span class="co note-flag"{"" if row["note"] else " hidden"}>&#9998; Has a note</span>'
    flags = f'<span class="why">{escape(" · ".join(row["flags"]))}</span>' if row["flags"] else ""
    if tab == "shortlisted" and row["failing"]:
        flags += f'<span class="why">No longer passes: {escape(" · ".join(row["failing"]))}</span>'
    if row["improvement"]:
        flags += f'<span class="improved-flag">{row["improvement"]}</span>'
    if row["review_due"]:
        flags += '<span class="due-flag"><span aria-hidden="true">&#9201;</span> Review due</span>'
    if row["next_earnings"]:
        stale = '<span class="co">(may be out of date)</span>' if row["dates_stale"] else ""
        next_earnings = f'<td class="num">{_fmt_date(date.fromisoformat(row["next_earnings"]))}{stale}</td>'
    else:
        next_earnings = '<td class="num muted">&mdash;</td>'
    score_cell = f'<td class="num">{"n/a" if row["score"] is None else format(row["score"], ".0f")}</td>'
    return f"""
              <tr class="screener-row" data-symbol-row="{escape(row['symbol'], quote=True)}"{attrs}{quote_row}{due_attr}{promoted_attr}>
                <td class="ticker-cell"><button class="disclose" type="button" aria-expanded="false" aria-controls="detail-{escape(row['symbol'], quote=True)}"><span aria-hidden="true">&#9656;</span><span class="sr-only">{symbol} details</span></button>{symbol}
                  <span class="co company-name" title="{escape(row['name'], quote=True)}">{escape(row['name'])}</span>{note}{flags}</td>
                {score_cell}
                {quote_cells}
                {render_market_cap_cell(record.get('market_cap'))}
                {render_pe_cell(record.get('pe_ratio'))}
                {render_peg_cell(record.get('peg_ratio'))}
                {next_earnings}
                {_render_actions(row['symbol'], tab, row['promoted'])}
              </tr>{_render_detail(row, column_count)}"""


def _render_header(tab: str) -> str:
    """Price and 52-Week Range are plain headers; every other column
    sorts, from a button inside the header so the keyboard reaches it."""
    def sortable(key: str) -> str:
        label, numeric = _SORTABLE_COLUMNS[key]
        css = "num sortable" if numeric else "sortable"
        hint = ' title="Projected until the company announces"' if key == "nextEarnings" else ""
        return (f'<th class="{css}" data-sort-key="{key}" aria-sort="none"{hint}>'
                f'<button type="button" class="sort-button">{label}</button></th>')

    order = ["symbol", "score", None, "change", None, "pctInRange", "marketCap", "pe", "peg", "nextEarnings"]
    plain = iter(['<th class="num">Price</th>', "<th>52-Week Range</th>"])
    cells = [sortable(key) if key else next(plain) for key in order]
    return "".join(cells) + "<th></th>"


def _render_tabs(view: dict | None, active: str) -> str:
    """Links, not script-driven tabs: the active list is in the URL so
    Back returns to it, and a link needs no arrow-key handling."""
    links = []
    for tab in TABS:
        count = "&mdash;" if view is None else len(view["rows"][tab])
        due = 0 if view is None or tab == "new" else view["due"][tab]
        due_text = f' &middot; <span class="tab-due-count">{due}</span> due' if due else ""
        current = ' aria-current="page"' if tab == active else ""
        links.append(f'<a href="/screener?tab={tab}" data-tab="{tab}"{current}>{TAB_LABELS[tab]} '
                     f'(<span class="tab-count">{count}</span>)<span class="tab-due">{due_text}</span></a>')
    return f'<nav class="screener-tabs" aria-label="Candidate lists">{"".join(links)}</nav>'


def _render_data_line(view: dict) -> str:
    state = view["state"]
    if not state:
        return ""
    last = view["last_run"]
    if view["run_is_stale"]:
        text = f"The nightly run hasn&#x27;t completed since {last.day} {last:%b}. Data may be out of date."
    elif last:
        text = (f"Last nightly run {_fmt_date(last)} &middot; {view['passing']} pass all filters "
                "&middot; ownership % is not screened")
    else:
        text = "No scores yet"
    progress = ""
    if not state.get("initial_pass_done") and state.get("universe_total"):
        progress = (f'<p class="page-sub" role="status">Initial screen in progress: '
                    f'{state.get("universe_checked", 0):,} of {state["universe_total"]:,} symbols checked.</p>')
    watchlist = "" if view["watchlist_known"] else (
        '<p class="page-sub" role="status">Couldn&#x27;t read your watchlist; Promote buttons may be out of date.</p>')
    dates = "" if view["dates_known"] else (
        '<p class="page-sub" role="status">Earnings dates couldn&#x27;t be loaded; Review due uses the '
        f'{REVIEW_FALLBACK_DAYS}-day rule for now.</p>')
    return f'<p class="page-sub">{text}</p>{progress}{dates}{watchlist}'


def _render_improved_line(view: dict, tab: str) -> str:
    if tab != "dismissed" or not view["improved"]:
        return ""
    n = view["improved"]
    text = "1 dismissed name has improved since you dismissed it." if n == 1 else f"{n} dismissed names have improved since you dismissed them."
    return f'<p class="improved-line" id="improved-line">{text}</p>'


def _render_table(view: dict, tab: str) -> str:
    all_rows = view["rows"][tab]
    if not all_rows:
        if tab == "new" and view["hidden"]:
            return f'<p class="empty">{view["hidden"]} names are hidden by your filters. Open Filters to change them.</p>'
        return f'<p class="empty">{EMPTY_TAB_TEXT[tab]}</p>'
    shown = all_rows[:MAX_ROWS]
    column_count = 11
    cap_note = (f'<p class="muted">Showing the {MAX_ROWS} highest scores of {len(all_rows)}. '
                "Tighten your filters or dismiss names to see the rest.</p>") if len(all_rows) > MAX_ROWS else ""
    body = "".join(_render_row(row, tab, column_count) for row in shown)
    return f"""
    <div class="category-block">
      <table class="indicator-table ticker-table screener-table" data-tab="{tab}">
        <thead><tr>{_render_header(tab)}</tr></thead>
        <tbody>{body}
        </tbody>
      </table>
    </div>{cap_note}"""


# (field, label, text before the number, text after); the stale rule has
# its own row.
_FILTER_ROWS = (
    ("net_margin_min", "Net margin", "above", "%"),
    ("fcf_min_m", "Free cash flow", "above", "$M (latest fiscal year)"),
    ("max_debt_equity", "Debt / equity", "at most", ""),
    ("max_dilution_pct", "Annual dilution", "at most", "%"),
    ("min_roi_pct", "Return on investment (ROI)", "at least", "%"),
)


def _number_input(field: str, form: dict, label: str) -> str:
    return (f'<input type="number" step="any" class="filter-number" data-field="{field}" data-part="value" '
            f'value="{form[field]["value"]:.10g}" aria-label="{escape(label)}" aria-describedby="err-{field}">'
            f'<span class="field-error" id="err-{field}" role="alert"></span>')


def _switch(field: str, form: dict, label: str) -> str:
    checked = " checked" if form[field]["on"] else ""
    return f'<label><input type="checkbox" data-field="{field}" data-part="on"{checked}> {label}</label>'


def _render_filters_panel(form: dict) -> str:
    rows = [
        f'<div class="filter-row" role="group" aria-label="Market cap">Market cap (always on) &nbsp; from '
        f'{_number_input("market_cap_min_m", form, "Market cap minimum, $M")} to '
        f'{_number_input("market_cap_max_m", form, "Market cap maximum, $M")} $M</div>'
    ]
    for field, label, before, after in _FILTER_ROWS:
        rows.append(
            f'<div class="filter-row" role="group" aria-label="{label}">{_switch(field, form, label)} &nbsp; {before} '
            f'{_number_input(field, form, f"{label}, {before}")} {after}</div>'
        )
    rows.append(
        f'<div class="filter-row" role="group" aria-label="Not stale">{_switch("stale_years", form, "Not stale")} &nbsp; '
        f'exclude listed at least {_number_input("stale_years", form, "Years listed")} years with revenue growth below '
        f'{_number_input("stale_min_growth_pct", form, "Revenue growth, percent")} %</div>'
    )
    defaults = escape(json.dumps(settings.default_form()), quote=True)
    return f"""
    <div id="filters-panel" class="card filters-panel" data-defaults="{defaults}" hidden>
      {"".join(rows)}
      <p id="filters-preview" class="note-state" role="status" aria-live="polite"></p>
      <div class="filter-actions"><button type="button" class="btn primary" id="filters-apply" disabled>Apply</button>
        <button type="button" class="btn" id="filters-reset">Reset to defaults</button>
        <span class="muted">Shortlisted and dismissed names are not affected.</span></div>
    </div>"""


def _render_filters_bar(view: dict, tab: str) -> str:
    counts = ""
    if tab == "new":
        counts = (f' <span class="muted"><span id="shown-count">{len(view["rows"]["new"])}</span> names shown &middot; '
                  f'{view["hidden"]} hidden by your filters</span>')
    return (f'<p class="filters-bar"><button type="button" class="btn" id="filters-toggle" aria-expanded="false" '
            f'aria-controls="filters-panel">Filters &#9656;</button>{counts}</p>{_render_filters_panel(view["form"])}')


def _render_data_check(view: dict, tab: str) -> str:
    if tab != "new" or not view["data_check"]:
        return ""
    items = "".join(
        f'<tr><td>{escape(r["symbol"])}<span class="co">{escape(r["name"])}</span></td>'
        f'<td>{escape(" · ".join(r["flags"]))}</td></tr>'
        for r in view["data_check"]
    )
    return (f'<details class="data-check"><summary>Needs a data check ({len(view["data_check"])})</summary>'
            f'<table class="indicator-table"><tbody>{items}</tbody></table></details>')







def _page(body: str, script: str = "", checking: bool = False) -> str:
    # Only a page with rows waiting for live prices has anything to check.
    checking = ('\n      <div class="header-meta"><span class="checking-indicator muted" id="checking-indicator">'
                'Checking for updates&hellip;</span></div>') if checking else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Small &amp; Mid-Cap Screener</title>
  <link rel="stylesheet" href="{static_url('dashboard.css')}">
</head>
<body>
  <main class="page page-screener">
    {_render_nav("/screener")}
    <header class="page-header">
      <h1>Small &amp; Mid-Cap Screener</h1>{checking}
    </header>
    {body}
  </main>{script}
</body>
</html>"""


def render_screener_page(view: dict, tab: str = "new") -> str:
    tab = tab if tab in TABS else "new"
    if not view["state"]:
        body = ('<p class="empty">The screener hasn&#x27;t run yet. See the README, Automation, '
                "to run the first pass.</p>")
        return _page(f"{_render_tabs(view, tab)}{body}")
    body = (
        f"{_render_data_line(view)}{_render_filters_bar(view, tab)}{_render_tabs(view, tab)}"
        f'<p id="prices-note" class="muted" role="status"></p>'
        f"{_render_improved_line(view, tab)}{_render_table(view, tab)}{_render_data_check(view, tab)}"
        '<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>'
        '<p id="announce" class="sr-only" role="status" aria-live="polite"></p>'
    )
    return _page(body, script_tag("screener.js") + script_tag("screener_filters.js"),
                 checking=tab != "dismissed" and bool(view["rows"][tab]))


def render_error_page(tab: str = "new") -> str:
    body = (f'<p class="page-sub">Scores unavailable</p>{_render_tabs(None, tab if tab in TABS else "new")}'
            '<p class="empty" role="alert">Couldn&#x27;t load the screener data (storage error). Reload to try again.</p>')
    return _page(body)
