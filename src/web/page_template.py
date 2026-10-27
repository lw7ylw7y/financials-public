"""HTML rendering for both v2 pages: the Indicator Digest Page and the
Ticker Dashboard.

A browser page, not an email, so this doesn't inherit email_template.py's
Outlook-safe inline-style-table constraints or its CID-image sparklines —
trend lines here are plain inline <svg> (see _render_sparkline_svg),
since a browser (unlike most email clients) renders SVG natively. It
does reuse email_template's copy/color constants (disclaimer text,
category labels, directional badge colors) so the two surfaces never
drift out of sync on wording or meaning, even though the markup itself
is page-specific.
"""

import re
from datetime import datetime, timezone
import os
import sys
from html import escape

import full_position
import reads_chart
import invested
import ticker_verdicts

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_WEB_DIR)
for _subdir in ("fred", "storage", "digest", "mailer"):
    sys.path.insert(0, os.path.join(_SRC_DIR, _subdir))

from email_template import (
    CATEGORY_INFO,
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    DIRECTIONAL_STYLE,
    DISCLAIMER,
    directional_style,
    group_basis,
    policy_line,
    summary_or_note,
)

# Reuses the indicator digest's own improving/weakening/mixed palette
# rather than inventing a second green/red/gray scale -- "discount" is
# the same "good" read as "improving", "overpriced" the same "bad" read
# as "weakening", "fair" the same neutral gray.
VALUATION_STYLE = {
    "discount": DIRECTIONAL_STYLE["improving"],
    "fair": DIRECTIONAL_STYLE["mixed"],
    "overpriced": DIRECTIONAL_STYLE["weakening"],
}
VALUATION_HEADINGS = {"discount": "Discount", "fair": "Fair", "overpriced": "Overpriced"}
# Mirrors src/mailer/sparkline.py's palette so the email and web trend
# lines read as the same feature, even though the email renders its
# version as a matplotlib PNG (email clients strip <svg>) and this one
# is a plain inline <svg> (fine in a browser, no such workaround needed).
SPARKLINE_WIDTH = 90
SPARKLINE_HEIGHT = 24
SPARKLINE_LINE_COLOR = "#2563eb"
SPARKLINE_FILL_COLOR = "#2563eb"
SPARKLINE_UP_COLOR = "#15803d"
SPARKLINE_DOWN_COLOR = "#b91c1c"
SPARKLINE_FLAT_COLOR = "#64748b"

# Status scale for the 52-week range bar: good (near the low, cheap) ->
# warning (mid-range) -> critical (near the high, expensive). Reuses the
# same green/red already established above for up/down, plus one amber
# step for the middle -- not a new, unrelated palette.
RANGE_GOOD_COLOR = SPARKLINE_UP_COLOR
RANGE_WARNING_COLOR = "#f59e0b"
RANGE_CRITICAL_COLOR = SPARKLINE_DOWN_COLOR
RANGE_BAR_WIDTH = 90
RANGE_BAR_HEIGHT = 10

NAV_LINKS = [
    ("/", "Indicator Digest"),
    ("/tickers", "Ticker Dashboard"),
    ("/screener", "Small & Mid-Cap Screener"),
]


def _render_sparkline_svg(values: list[float]) -> str:
    """Minimal inline-SVG trend line for a table row, mirroring
    mailer.sparkline.render_sparkline's look (line + light fill +
    a green/red/gray endpoint dot for up/down/flat vs. the prior
    value). A single-point history renders as just the dot.
    """
    w, h = SPARKLINE_WIDTH, SPARKLINE_HEIGHT
    pad = 3
    if len(values) < 2:
        cx, cy = w - pad, h / 2
        return (
            f'<svg class="sparkline" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="trend unavailable">'
            f'<circle cx="{cx}" cy="{cy}" r="2.4" fill="{SPARKLINE_FLAT_COLOR}"/></svg>'
        )

    lo, hi = min(values), max(values)
    value_range = hi - lo
    span = value_range if value_range else 1

    def x_at(i: int) -> float:
        return pad + (w - 2 * pad) * i / (len(values) - 1)

    def y_at(v: float) -> float:
        return pad + (h - 2 * pad) * (1 - (v - lo) / span)

    points = [(x_at(i), y_at(v)) for i, v in enumerate(values)]
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    fill_points = f"{points[0][0]:.1f},{h - pad:.1f} " + line_points + f" {points[-1][0]:.1f},{h - pad:.1f}"

    if values[-1] > values[-2]:
        endpoint_color = SPARKLINE_UP_COLOR
    elif values[-1] < values[-2]:
        endpoint_color = SPARKLINE_DOWN_COLOR
    else:
        endpoint_color = SPARKLINE_FLAT_COLOR
    end_x, end_y = points[-1]

    return (
        f'<svg class="sparkline" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="trend line">'
        f'<polygon points="{fill_points}" fill="{SPARKLINE_FILL_COLOR}" opacity="0.12"/>'
        f'<polyline points="{line_points}" fill="none" stroke="{SPARKLINE_LINE_COLOR}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="2.4" fill="{endpoint_color}"/>'
        f"</svg>"
    )

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def static_url(name: str) -> str:
    """`/static/<name>` with the file's modification time as a version, so
    a browser that cached an earlier copy fetches the new one after a
    deploy instead of running new HTML against old script."""
    try:
        return f"/static/{name}?v={int(os.path.getmtime(os.path.join(_STATIC_DIR, name)))}"
    except OSError:
        return f"/static/{name}"


def script_tag(name: str) -> str:
    """A `<script src>` for `static/js/<name>`. Page scripts are files,
    not strings in this module, so an editor and `node --check` can read
    them; they read everything they need from the page's own markup."""
    return f'<script src="{static_url("js/" + name)}"></script>'


def _render_nav(active_path: str) -> str:
    """Shared nav so either v2 page links to the other -- clicking
    between the Indicator Digest Page and the Ticker Dashboard doesn't
    require typing a URL."""
    links = []
    for path, label in NAV_LINKS:
        css_class = "active" if path == active_path else ""
        links.append(f'<a href="{path}" class="{css_class}">{escape(label)}</a>')
    return f'<nav class="site-nav">{"".join(links)}</nav>'


def _render_group_label(category: str, where: str) -> str:
    """A group's name with a small (i) that opens its explanation. The
    explanation is a real element next to the button (not only a `title`)
    so touch and keyboard users reach it; `where` keeps the two uses of a
    group on one page apart."""
    info_id = f"info-{category}-{where}"
    label = CATEGORY_LABELS[category]
    return (
        f'<span class="group-label">{label.upper()}'
        f'<button type="button" class="info-button" aria-expanded="false" aria-controls="{info_id}" '
        f'aria-label="About {label.lower()} indicators" title="{escape(CATEGORY_INFO[category]["info"], quote=True)}">&#9432;</button>'
        f'<span id="{info_id}" class="info-popup" role="note" hidden>'
        f'<strong>{escape(CATEGORY_INFO[category]["frame"])}.</strong> {escape(CATEGORY_INFO[category]["info"])}</span></span>'
    )


def _render_ai_section(ai_result: dict | None) -> str:
    if ai_result is None:
        return """
        <section class="card">
          <p class="muted">No AI interpretation on file yet.</p>
        </section>"""

    tiles = []
    for category in CATEGORY_ORDER:
        group = ai_result["groups"][category]
        style = directional_style(group["read"])
        tiles.append(f"""
          <div class="read-group" style="background:{style['bg']};border-top:3px solid {style['accent']};">
            <p class="category-label">{_render_group_label(category, "read")}</p>
            <span class="directional-badge" style="color:{style['text']};">{style['label']}</span>
            <p class="read-frame">{escape(CATEGORY_INFO[category]['frame'])}</p>
            <p class="muted read-count">{escape(group_basis(group))}</p>
          </div>""")
    relationship = (
        f'<p class="read-relationship">{escape(ai_result["relationship"])}</p>' if ai_result["relationship"] else ""
    )
    return f"""
        <section class="card">
          <div class="read-groups">{''.join(tiles)}
          </div>
          {relationship}
          <p class="read-policy muted">{escape(policy_line(ai_result["policy"]))}</p>
          <p class="ai-summary">{escape(summary_or_note(ai_result))}</p>
          <p class="disclaimer">{escape(DISCLAIMER)}</p>
        </section>"""


def _render_table_section(table: dict) -> str:
    sections = []
    for category in CATEGORY_ORDER:
        rows = table.get(category, [])
        if not rows:
            continue

        row_html = []
        for row in rows:
            prior = f"{row['prior_value']:g}" if row["prior_value"] is not None else "n/a"
            sparkline = _render_sparkline_svg(row["sparkline_values"])
            row_html.append(f"""
              <tr>
                <td>{escape(row['name'])}</td>
                <td class="sparkline-cell">{sparkline}</td>
                <td class="num">{row['latest_value']:g}</td>
                <td class="num muted">{escape(row['latest_date'])}</td>
                <td class="num muted">prior: {prior}</td>
              </tr>""")

        sections.append(f"""
        <div class="category-block">
          <p class="category-label">{_render_group_label(category, "table")}</p>
          <p class="muted group-frame">{escape(CATEGORY_INFO[category]['frame'])}</p>
          <table class="indicator-table">
            {''.join(row_html)}
          </table>
        </div>""")
    return "".join(sections)


def _render_countdown_section(countdown: dict) -> str:
    if not countdown["entries"]:
        return ""

    soonest = countdown["soonest"]
    other_rows = []
    for entry in countdown["entries"]:
        if entry["key"] == soonest["key"]:
            continue
        other_rows.append(f"""
          <tr>
            <td>{escape(entry['name'])}</td>
            <td class="num muted">in {entry['days_until']} day(s) &middot; {escape(entry['next_release_date'])}</td>
          </tr>""")

    return f"""
        <section class="card countdown">
          <p class="category-label">Next Releases</p>
          <p>
            <span class="next-up-badge">Next up</span>
            <strong>{escape(soonest['name'])}</strong>
            &mdash; in {soonest['days_until']} day(s) ({escape(soonest['next_release_date'])})
          </p>
          {f'<table class="indicator-table">{"".join(other_rows)}</table>' if other_rows else ''}
        </section>"""


def render_indicator_digest_page(data: dict) -> str:
    """`data` per live_pull.get_initial_page_data: table, countdown,
    ai_result — always built from stored data, so this renders
    instantly. The page's own script then calls /api/check in the
    background; if that finds at least one indicator with a genuinely
    new value, it patches #table-section / #countdown-section /
    #ai-section in place. If nothing's new, the check costs a FRED call
    but never an AI call, and the page is left exactly as rendered here
    — no point re-rendering (or re-billing Gemini) for a no-op. A
    "Checking for updates..." indicator is shown for the duration of
    that call and removed once it settles (updated, no-op, or failed
    alike), so the reader always knows whether a check is actually in
    flight.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Indicator Digest</title>
  <link rel="stylesheet" href="{static_url('dashboard.css')}">
</head>
<body>
  <main class="page">
    {_render_nav("/")}
    <header class="page-header">
      <h1>Indicator Digest</h1>
      <div class="header-meta">
        <span class="checking-indicator muted" id="checking-indicator">Checking for updates&hellip;</span>
      </div>
    </header>

    <div id="ai-section">{_render_ai_section(data['ai_result'])}</div>
    <div id="history-section">{reads_chart.render_loading()}</div>
    <div id="table-section">{_render_table_section(data['table'])}</div>
    <div id="countdown-section">{_render_countdown_section(data['countdown'])}</div>

    <footer class="page-footer">
      <p class="muted">Automated macro indicator digest &middot; data from FRED &middot; checks for live updates in the background</p>
    </footer>
  </main>
  {script_tag("digest.js")}
</body>
</html>"""


def _group_header(group_name: str) -> str:
    """Section header derived straight from the config key, e.g.
    "sector" -> "Sector" -- never a fixed lookup, so a new or renamed
    group in config/tickers.json appears correctly with no code change."""
    return group_name.replace("_", " ").replace("-", " ").title()


def render_range_bar(symbol: str, low: float | None, high: float | None, price: float | None) -> str:
    """52-week range as a green (near the low, cheap) -> amber ->
    red (near the high, expensive) status gradient, with a marker at
    the current price's position -- a continuous read of "where in its
    range does this sit", not just the raw numbers. A missing low, high
    or price (Finnhub has no 52-week range for some symbols) renders
    "n/a". Never color-alone:
    the low/high are printed as text below the bar, and the exact price
    is its own table column, so the read survives without color too.
    """
    if low is None or high is None or price is None:
        return '<div class="range-cell muted">n/a</div>'

    w, h = RANGE_BAR_WIDTH, RANGE_BAR_HEIGHT
    span = high - low
    pct = 0.5 if span <= 0 else max(0.0, min(1.0, (price - low) / span))
    marker_x = pct * w
    gradient_id = f"range-grad-{escape(symbol)}"

    return f"""
            <div class="range-cell">
              <svg class="range-bar" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img"
                   aria-label="52-week range ${low:,.2f} to ${high:,.2f}, current price ${price:,.2f}">
                <defs>
                  <linearGradient id="{gradient_id}" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stop-color="{RANGE_GOOD_COLOR}"/>
                    <stop offset="50%" stop-color="{RANGE_WARNING_COLOR}"/>
                    <stop offset="100%" stop-color="{RANGE_CRITICAL_COLOR}"/>
                  </linearGradient>
                </defs>
                <rect x="0" y="{h / 2 - 3:.1f}" width="{w}" height="6" rx="3" fill="url(#{gradient_id})"/>
                <circle cx="{marker_x:.1f}" cy="{h / 2:.1f}" r="3.5" fill="#fff" stroke="#0f172a" stroke-width="1.3"/>
              </svg>
              <div class="range-labels muted">
                <span>${low:,.2f}</span><span>${high:,.2f}</span>
              </div>
            </div>"""


def render_change_cell(change: float | None, change_percent: float | None) -> str:
    """Today's price move vs. the previous close -- same never-color-
    alone convention as the moving-average cells: a signed arrow +
    percentage alongside the color, plus the absolute $ change. "n/a"
    if Finnhub's quote response didn't carry these fields.
    """
    if change is None or change_percent is None:
        return '<td class="num muted">n/a</td>'

    if change > 0:
        css_class, arrow, color = "up", "&#9650;", SPARKLINE_UP_COLOR
    elif change < 0:
        css_class, arrow, color = "down", "&#9660;", SPARKLINE_DOWN_COLOR
    else:
        css_class, arrow, color = "flat", "", SPARKLINE_FLAT_COLOR

    return (
        f'<td class="num">{change:+,.2f} '
        f'<span class="ma-delta {css_class}" style="color:{color};">{arrow}{abs(change_percent):.2f}%</span></td>'
    )


def pct_in_range(price: float | None, low: float | None, high: float | None) -> float | None:
    """Where the price sits in its 52-week range, 0 at the low and 100 at
    the high; the same position the verdicts use."""
    position = ticker_verdicts.range_position(price, low, high)
    return None if position is None else position * 100


def render_pct_in_range_cell(pct: float | None) -> str:
    """Where the current price sits in its 52-week range, as a plain
    number -- a precise complement to the range bar's visual read, which
    already carries the color signal, so this cell deliberately doesn't
    repeat it.
    """
    if pct is None:
        return '<td class="num muted">n/a</td>'
    shown = 0 if pct <= 0 else 100 if pct >= 100 else min(99, max(1, round(pct)))  # 0% and 100% only at the ends
    return f'<td class="num">{shown}%</td>'


def format_market_cap(market_cap: float) -> str:
    """`market_cap` is Finnhub's `marketCapitalization`, in millions of
    USD -- convert to dollars, then pick the largest suffix (T/B/M)
    that keeps the number readable at a glance rather than printing a
    raw multi-digit millions figure."""
    value = market_cap * 1_000_000
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    return f"${value / 1_000_000:.2f}M"


def render_market_cap_cell(market_cap: float | None) -> str:
    if market_cap is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{format_market_cap(market_cap)}</td>'


def render_pe_cell(pe_ratio: float | None) -> str:
    """Trailing P/E as a plain number -- "n/a" when there's nothing to
    show, not an error: Finnhub has none for a money-losing or
    thinly-covered company (see `finnhub_client.fetch_stock_metrics`).
    """
    if pe_ratio is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{pe_ratio:.1f}</td>'


def render_peg_cell(peg_ratio: float | None) -> str:
    """PEG (P/E to growth) as a plain number -- "n/a" when Finnhub has
    none, common for a company with no analyst growth estimate (see
    `finnhub_client.fetch_stock_metrics`).
    """
    if peg_ratio is None:
        return '<td class="num muted">n/a</td>'
    return f'<td class="num">{peg_ratio:.2f}</td>'


def _render_remove_ticker_button(symbol: str, group_name: str) -> str:
    """A small "x" on every row (pending/errored/live alike -- removal
    doesn't depend on a successful fetch) that posts to
    /api/tickers/remove. Rendered as the row's own trailing cell rather
    than next to the ticker symbol, so it doesn't crowd the column
    readers scan first. Event-delegated in the page's own script
    rather than bound per-button, since a row's whole group block gets
    replaced wholesale whenever that group's own check response lands."""
    return (
        f'<button type="button" class="remove-ticker" data-group="{escape(group_name)}" '
        f'data-symbol="{escape(symbol)}" title="Remove {escape(symbol)} from {escape(group_name)}" '
        f'aria-label="Remove {escape(symbol)}">&times;</button>'
    )


_INDIVIDUAL_GROUP = "individual"  # the only group whose rows show Market
# Cap/P/E/PEG -- Finnhub only computes those for individual companies,
# never a fund (confirmed live across every ETF group, and there's no
# fallback source for a fund's P/E/PEG/market cap), so those three
# columns are dropped entirely for every group but this one rather
# than showing all-"n/a" data.

_TICKER_DATA_COLUMN_COUNT = 7  # Price, Change, 52-Week Range, % in Range, Market Cap, P/E, PEG
_TICKER_DATA_COLUMN_COUNT_FUND = 4  # Price, Change, 52-Week Range, % in Range


def render_full_position_cell(symbol: str, full: bool) -> str:
    """The Full Position checkbox cell, shared by the Ticker Dashboard
    and the screener's Shortlisted tab. Its row is greyed out by the
    row's own `data-full-position` attribute, which the page script
    toggles with the box; the box itself stays at full contrast."""
    checked = " checked" if full else ""
    return (
        f'<td class="full-cell"><input type="checkbox" class="full-position" data-symbol="{escape(symbol, quote=True)}" '
        f'aria-label="Full position in {escape(symbol, quote=True)}"{checked}></td>'
    )


def format_invested(amount: float) -> str:
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def render_invested_cell(symbol: str, amount: float | None, editable: bool = True) -> str:
    """The Invested cell of an `individual` row: the total or a dash, and
    a pen that opens the editor (disabled when the amounts could not be
    loaded, so a blank view is never saved over a real total)."""
    symbol_attr = escape(symbol, quote=True)
    if not editable:
        shown = '<span class="muted">n/a</span>'
    elif amount is None:
        shown = '<span class="muted">&mdash;</span>'
    else:
        shown = f'<span class="invested-amount" data-amount="{amount:.2f}">{format_invested(amount)}</span>'
    disabled = "" if editable else " disabled"
    pen = (f'<button type="button" class="invested-edit" data-symbol="{symbol_attr}" title="Edit the amount invested in {symbol_attr}" '
           f'aria-label="Edit invested amount for {symbol_attr}"{disabled}>&#9998;</button>')
    return f'<td class="num invested-cell">{shown} {pen}</td>'


VERDICT_MEANING = {
    "discount": "Cheaper than its own past year and than its peers.",
    "fair": "In line with its own past year and its peers.",
    "overpriced": "Richer than its own past year and than its peers.",
}
NOT_SCORED_TIP = "Not enough data yet to compare this ticker with its own year or its peers."
NOT_JUDGED_TIP = "Too few tickers with a 52-week range to compare: a group needs at least 3."


def render_verdict_pill(verdict: str | None, tip: str, tip_id: str, label: str | None = None) -> str:
    """A colour-coded pill (Discount green, Fair grey, Overpriced red; the word
    is always on it) that shows `tip` on hover or keyboard focus. `verdict`
    None is the grey "Not scored" / "Not judged" pill. The tip is a real
    element, not only a `title`, so focus and touch reach it, and
    `aria-describedby` points a screen reader at it. `tip_id` must be unique
    on the page; the page script places the tip (fixed, so a scrolling
    table block cannot clip it) and Escape hides it."""
    if verdict is None:
        style, text = "background:#e2e8f0;color:#64748b;", label or "Not scored"
    else:
        colors = VALUATION_STYLE[verdict]
        style, text = f"background:{colors['bg']};color:{colors['text']};", VALUATION_HEADINGS[verdict]
    return (
        f'<span class="verdict-wrap" tabindex="0" aria-describedby="{escape(tip_id, quote=True)}">'
        f'<span class="verdict-pill" style="{style}">{escape(text)}</span>'
        f'<span class="verdict-tip" id="{escape(tip_id, quote=True)}" role="tooltip">{escape(tip)}</span></span>'
    )


def _verdict_tip_id(group: str, symbol: str = "") -> str:
    return "verdict-tip-" + re.sub(r"[^A-Za-z0-9_-]", "_", f"{group}-{symbol}")


def _render_verdict_cell(card: dict, verdicts: dict, has_data: bool) -> str:
    if not has_data:
        return '<td class="verdict-cell muted">&mdash;</td>'
    entry = verdicts["tickers"].get((card["group"], card["symbol"]))
    if entry is None:
        return f'<td class="verdict-cell">{render_verdict_pill(None, NOT_SCORED_TIP, _verdict_tip_id(card["group"], card["symbol"]))}</td>'
    tip = f"{VERDICT_MEANING[entry['verdict']]} {entry['reasoning']}"
    return f'<td class="verdict-cell">{render_verdict_pill(entry["verdict"], tip, _verdict_tip_id(card["group"], card["symbol"]))}</td>'


def _render_group_verdict(group_name: str, verdicts: dict) -> str:
    entry = verdicts["groups"].get(group_name)
    if entry is None:
        return render_verdict_pill(None, NOT_JUDGED_TIP, _verdict_tip_id(group_name), "Not judged")
    return render_verdict_pill(entry["verdict"], entry["summary"], _verdict_tip_id(group_name))


def render_stale_flag(symbol: str, saved_at: str | None, group: str = "") -> str:
    """A "Saved" flag (a word and a glyph, not colour) on a row whose live
    fetch failed, with the date and time of the numbers it shows on hover
    or focus. Shares the verdict tip's markup so the page script places it."""
    try:
        saved = datetime.fromisoformat(saved_at) if saved_at else None
    except ValueError:
        saved = None
    if saved is not None and saved.tzinfo is not None:
        saved = saved.astimezone(timezone.utc)
    when = f"{saved.day} {saved:%b %Y, %H:%M} UTC" if saved else None
    tip = (f"The live update failed. These numbers (and the verdict) are from {when}." if when
           else "The live update failed. These numbers (and the verdict) are from an earlier save; its time was not recorded.")
    tip_id = _verdict_tip_id(group, symbol).replace("verdict-tip", "stale-tip", 1)
    return (f'<span class="verdict-wrap stale-wrap" tabindex="0" aria-describedby="{tip_id}">'
            f'<span class="stale-flag"><span aria-hidden="true">&#9201;</span> Saved</span>'
            f'<span class="verdict-tip" id="{tip_id}" role="tooltip">{escape(tip)}</span></span>')


def _render_ticker_row(card: dict, show_company_columns: bool, full: bool = False,
                       amount: float | None = None, invested_known: bool = True,
                       verdicts: dict | None = None) -> str:
    """`data-symbol`/`data-pct-in-range` on the `<tr>` are read by the
    page's own client-side sort script (see render_ticker_dashboard_page)
    so a click on the Ticker/% in Range header can reorder rows without a
    server round trip; `data-pct-in-range` is left empty for a pending or
    errored card, which the sort script treats as sorting last rather than
    as zero. `show_company_columns` mirrors whichever group's table this
    row belongs to -- see _INDIVIDUAL_GROUP."""
    symbol_attr = escape(card["symbol"], quote=True)
    in_range = pct_in_range(card["price"], card["week52_low"], card["week52_high"])
    pct_in_range_attr = "" if in_range is None else f"{in_range:.2f}"
    row_attrs = f' data-symbol="{symbol_attr}" data-pct-in-range="{pct_in_range_attr}"'
    if full:
        row_attrs += ' data-full-position="1"'
    verdicts = verdicts if verdicts is not None else ticker_verdicts.by_ticker(None)
    invested_cell = render_invested_cell(card["symbol"], amount, invested_known) if show_company_columns else ""
    trailing_cells = invested_cell + render_full_position_cell(card["symbol"], full) + f"<td>{_render_remove_ticker_button(card['symbol'], card['group'])}</td>"
    column_count = _TICKER_DATA_COLUMN_COUNT if show_company_columns else _TICKER_DATA_COLUMN_COUNT_FUND

    if card["pending"]:
        return f"""
              <tr{row_attrs}>
                <td>{escape(card['symbol'])}</td>
                <td colspan="{column_count}" class="muted">Loading&hellip;</td>
                {_render_verdict_cell(card, verdicts, False)}
                {trailing_cells}
              </tr>"""

    if card["error"]:
        return f"""
              <tr{row_attrs}>
                <td>{escape(card['symbol'])}</td>
                <td colspan="{column_count}" class="muted">Unable to load data.</td>
                {_render_verdict_cell(card, verdicts, False)}
                {trailing_cells}
              </tr>"""

    stale_flag = render_stale_flag(card["symbol"], card["stale_since"], card["group"]) if "stale_since" in card else ""
    company_cells = (
        f"""
                {render_market_cap_cell(card['market_cap'])}
                {render_pe_cell(card['pe_ratio'])}
                {render_peg_cell(card['peg_ratio'])}"""
        if show_company_columns
        else ""
    )
    return f"""
              <tr{row_attrs}>
                <td>{escape(card['symbol'])}{stale_flag}</td>
                <td class="num">${card['price']:,.2f}</td>
                {render_change_cell(card['change'], card['change_percent'])}
                <td class="range-bar-cell">{render_range_bar(card['symbol'], card['week52_low'], card['week52_high'], card['price'])}</td>
                {render_pct_in_range_cell(in_range)}
                {company_cells}
                {_render_verdict_cell(card, verdicts, True)}
                {trailing_cells}
              </tr>"""


def _render_add_ticker_form(group_name: str) -> str:
    """A small inline form under each group's table that posts to
    /api/tickers/add. Only adds within this existing group --
    creating a new group is still a hand-edit of config/tickers.json."""
    return f"""
          <form class="add-ticker-form" data-group="{escape(group_name)}">
            <input type="text" name="symbol" class="add-ticker-input" placeholder="Add ticker&hellip;" maxlength="10" autocomplete="off">
            <button type="submit">Add</button>
          </form>"""


def _render_ticker_groups(grouped_cards: dict, full_positions: frozenset = frozenset(),
                          amounts: dict | None = None, invested_known: bool = True,
                          verdicts: dict | None = None) -> str:
    """The group tables only -- shared by the full-page initial render
    and each group's own /api/tickers/groups/<name>/check fragment
    (called with a single-entry `grouped_cards` dict, which this
    function handles the same as the full one since it just loops).
    Group headers are derived from the config keys (see
    `_group_header`), never a fixed list, and a pending/errored ticker
    stands in for any row not yet fetched or whose fetch failed,
    without affecting the other rows.

    Each `.category-block` carries `data-group="<name>"` so the page's
    own script (see render_ticker_dashboard_page) can fetch and patch
    one group's block independently of the others -- a group with
    fewer tickers finishes and repaints before a slower one does,
    rather than the whole page waiting on one combined request.

    The Ticker and % in Range headers carry `class="sortable"` plus a
    `data-sort-key` the page's own client-side script uses to reorder a
    table's rows in place on click -- sorting is purely a DOM reshuffle
    of the rows already rendered here, not a server round trip, and
    each table sorts independently of the others.
    """
    lookup = ticker_verdicts.by_ticker(verdicts)
    sections = []
    for group_name, cards in grouped_cards.items():
        show_company_columns = group_name == _INDIVIDUAL_GROUP
        row_html = "".join(_render_ticker_row(card, show_company_columns, card["symbol"] in full_positions,
                                                   (amounts or {}).get(card["symbol"]), invested_known, lookup) for card in cards)
        company_headers = (
            """
                <th class="num">Market Cap</th>
                <th class="num">P/E</th>
                <th class="num">PEG</th>"""
            if show_company_columns
            else ""
        )
        invested_header = '<th class="num invested-head">Invested</th>' if show_company_columns else ""
        sections.append(f"""
        <div class="category-block" data-group="{escape(group_name, quote=True)}">
          <p class="category-label">{escape(_group_header(group_name))} {_render_group_verdict(group_name, lookup)}</p>
          <table class="indicator-table ticker-table">
            <thead>
              <tr>
                <th class="sortable" data-sort-key="symbol">Ticker</th>
                <th class="num">Price</th>
                <th class="num">Change</th>
                <th>52-Week Range</th>
                <th class="num sortable" data-sort-key="pctInRange">% in Range</th>
                {company_headers}
                <th>Verdict</th>
                {invested_header}
                <th>Full Position</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {row_html}
            </tbody>
          </table>
          {_render_add_ticker_form(group_name)}
        </div>""")
    return "".join(sections)


def _render_market_news(market_news: dict) -> str:
    """A single page-level feed of general market headlines shown once
    at the top of the Ticker Dashboard -- deliberately distinct from a
    per-ticker news column: one feed, not one list per row, avoids
    cluttering the table.
    """
    if market_news["pending"]:
        return """
        <section class="card">
          <p class="muted">Loading market news&hellip;</p>
        </section>"""

    headlines = market_news["headlines"]
    if not headlines:
        return """
        <section class="card">
          <p class="muted">Market news unavailable.</p>
        </section>"""

    items = []
    for h in headlines:
        source = f' <span class="muted">&middot; {escape(h["source"])}</span>' if h.get("source") else ""
        items.append(
            f'<li><a href="{escape(h["url"])}" target="_blank" rel="noopener">{escape(h["headline"])}</a>{source}</li>'
        )

    return f"""
        <section class="card">
          <p class="category-label">Market News</p>
          <ul class="market-news-list">{''.join(items)}</ul>
        </section>"""


def render_ticker_dashboard_page(
    grouped_cards: dict,
    market_news: dict,
    verdicts: dict | None = None,
    full_positions: frozenset = frozenset(),
    full_positions_known: bool = True,
    amounts: dict | None = None,
    invested_known: bool = True,
) -> str:
    """`grouped_cards` per ticker_dashboard.get_initial_ticker_page_data,
    `market_news` per ticker_dashboard.get_initial_market_news,
    `verdicts` per ticker_dashboard.compute_page_verdicts (None when
    nothing is cached yet) -- all three built entirely from local
    caches, so this renders instantly, same as the Indicator Digest
    Page. A ticker with no cached snapshot yet renders as a "Loading..."
    placeholder row. The page's own script then fetches each group's own
    /api/tickers/groups/<name>/check and /api/market-news/check
    independently in the background -- a group with fewer tickers
    finishes and repaints before a slower one does. A "Checking for
    updates..." indicator is shown until every one of those requests has
    settled, one way or another.

    `verdicts` are the Discount / Fair / Overpriced pills in each group's
    header and each row's Verdict column; they default to none (every
    row then reads "Not scored") so callers that don't care about them
    -- most existing tests -- don't need to pass them.

    `full_positions` is the set of symbols whose Full Position box is
    ticked (greyed rows); `full_positions_known` is False when that set
    could not be read, which adds a note instead of failing the page.
    """
    full_note = "" if full_positions_known else escape(full_position.UNREADABLE_NOTE)
    invested_note = "" if invested_known else escape(invested.UNREADABLE_NOTE)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ticker Dashboard</title>
  <link rel="stylesheet" href="{static_url('dashboard.css')}">
</head>
<body>
  <main class="page page-wide">
    {_render_nav("/tickers")}
    <header class="page-header">
      <h1>Ticker Dashboard</h1>
      <div class="header-meta">
        <span class="checking-indicator muted" id="checking-indicator">Checking for updates&hellip;</span>
      </div>
    </header>
    <div id="market-news">{_render_market_news(market_news)}</div>
    <p id="full-position-note" class="muted" role="status">{full_note}</p>
    <p id="full-position-error" class="muted" role="status"></p>
    <p id="invested-note" class="muted" role="status">{invested_note}</p>
    <p id="invested-error" class="muted" role="status"></p>
    <div id="ticker-groups">{_render_ticker_groups(grouped_cards, full_positions, amounts, invested_known, verdicts)}</div>
    <footer class="page-footer">
      <p class="muted">Price, change, and 52-week range from Finnhub &middot; free tier may lag by up to ~20 minutes</p>
      <p class="muted">Verdicts compare each ticker with its own 52-week range and its group; they are not an estimate of what a ticker is worth, and not personalized financial advice.</p>
    </footer>
  </main>
  {script_tag("tickers.js")}
</body>
</html>"""


def render_ticker_group_check_response(group_name: str, cards: list[dict], full_positions: frozenset = frozenset(),
                                       amounts: dict | None = None, invested_known: bool = True,
                                       verdicts: dict | None = None) -> dict:
    """HTML fragment for GET /api/tickers/groups/<group_name>/check,
    called once that group's own check_for_ticker_updates call finishes
    (it always re-fetches -- there's no "nothing changed" gate for
    tickers the way there is for the AI-backed indicator digest). Only
    this one group's block is returned, so the page's script can patch
    it without touching any other group's table."""
    return {"group_html": _render_ticker_groups({group_name: cards}, full_positions, amounts, invested_known, verdicts)}


def render_market_news_check_response(market_news: dict) -> dict:
    """HTML fragment for GET /api/market-news/check, independent of any
    ticker group's own check."""
    return {"news_html": _render_market_news(market_news)}


def render_check_response(content: dict) -> dict:
    """HTML fragments for /api/check once check_for_updates finds at
    least one indicator with a genuinely new value. `content` matches
    build_digest_content's return shape.

    `ai_html` is the computed read plus the AI's explanation when one
    on file still matches it; None only when there are no indicators to
    read.
    """
    read_view = content["read_view"]
    ai_html = _render_ai_section(read_view) if read_view is not None else None
    return {
        "table_html": _render_table_section(content["table"]),
        "countdown_html": _render_countdown_section(content["countdown"]),
        "ai_html": ai_html,
    }
