"""The digest page's "Reads over time" card: the three groups' saved
scores as SVG lines against the NBER recession months.

Pure rendering from what `reads_history` loads: nothing here reads
Redis. Two charts are rendered (10 years or all of it), each with every
curve moved by its fitted shift, and the page script shows one and swaps
on the toggle. Leading is shown by default; Coincident and Lagging are
hidden until their toggle is pressed. A month with no saved entry is a
gap in the line. The lines differ by dash pattern as well as colour,
each is labelled at its right end, and a table of the latest months
carries the same values as text.
"""

import os
import sys
from datetime import date
from html import escape

_WEB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_WEB_DIR, "..", "storage"))

from reads_history import GROUPS  # noqa: E402

RANGES = (("10y", "10 years", 120), ("all", "All since 1978", None))
SHOWN_BY_DEFAULT = ("leading",)
WIDTH, HEIGHT = 920, 250
LEFT, RIGHT, TOP, BOTTOM = 100, 175, 14, 34
LABEL_GAP = 15
# Where a group's word changes (`market_read.READ_THRESHOLD`; a test keeps the two equal).
THRESHOLD = 0.25
TABLE_MONTHS = 24
# Dash patterns tell the groups apart without colour.
DASH = {"leading": "", "coincident": "6 4", "lagging": "2 3"}
READ_WORDS = {"improving": "Improving", "mixed": "Mixed", "weakening": "Weakening"}


def _index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def _month(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _read_word(read: str | None) -> str:
    return READ_WORDS.get(read or "", "No read")


def _chart(reads: dict, recessions: dict, fit: dict, last: str, count: int | None,
           label: str, first_live: str | None) -> str:
    """One SVG. `count` months ending at `last` (None: from the first saved month)."""
    first = _index(min(reads)) if count is None else max(_index(last) - count + 1, _index(min(reads)))
    end = _index(last)
    n = end - first + 1
    plot_w = WIDTH - LEFT - RIGHT

    def x(i: float) -> float:
        return LEFT + plot_w * (i - first) / max(end - first, 1)

    def y(score: float) -> float:
        return TOP + (HEIGHT - TOP - BOTTOM) * (1 - (score + 1) / 2)

    out = [f'<svg class="history-chart" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
           f'aria-labelledby="hc-title-{label} hc-desc-{label}">',
           f'<title id="hc-title-{label}">Group reads over time, lined up with the recession dates</title>',
           f'<desc id="hc-desc-{label}">Score of the leading, coincident and lagging groups each month, from -1 '
           f'(weakening) to +1 (improving), with recession months shaded.</desc>']

    month = first
    while month <= end:
        if recessions.get(_month(month)):
            stop = month
            while stop + 1 <= end and recessions.get(_month(stop + 1)):
                stop += 1
            out.append(f'<rect class="history-band" x="{x(month) - 0.5:.1f}" y="{TOP}" width="{max(x(stop) - x(month), 2):.1f}" '
                       f'height="{HEIGHT - TOP - BOTTOM}"><title>Recession (NBER): {_month(month)} to {_month(stop)}</title></rect>')
            month = stop + 1
        else:
            month += 1

    # Faint lines at the thresholds where a group's word changes, a heavier line at 0 and at -1
    # (every scored indicator unfavorable), and the three zones named in the left margin.
    for level, text, css in ((1, "+1", ""), (THRESHOLD, "", " history-threshold"), (0, "0", " history-zero"),
                             (-THRESHOLD, "", " history-threshold"), (-1, "-1", " history-floor")):
        out.append(f'<line class="history-grid{css}" x1="{LEFT}" y1="{y(level):.1f}" x2="{WIDTH - RIGHT}" y2="{y(level):.1f}"/>')
        if text:
            out.append(f'<text class="history-axis" x="{LEFT - 6}" y="{y(level) + 4:.1f}" text-anchor="end">{text}</text>')
    for level, word in ((0.625, "Improving"), (0, "Mixed"), (-0.625, "Weakening")):
        out.append(f'<text class="history-zone" x="{LEFT - 30}" y="{y(level) + 4:.1f}" text-anchor="end">{word}</text>')
    step = 2 if n > 130 else 1
    for m in range(first, end + 1):
        if m % 12 == 0 and (m // 12) % step == 0:
            out.append(f'<text class="history-axis" x="{x(m):.1f}" y="{HEIGHT - 14}" text-anchor="middle">{m // 12}</text>')

    labels = []
    for group in GROUPS:
        shift = fit[group]["shift"] if fit.get(group, {}).get("applied") else 0
        path, drawn_to, drawn_score, previous = [], None, None, None
        # Months whose shifted position falls inside the chart, so a group drawn later still
        # starts at the left edge.
        for m in range(first - max(shift, 0), end - min(shift, 0) + 1):
            entry = reads.get(_month(m))
            score = None if entry is None else entry["groups"][group]["score"]
            at = m + shift
            if score is None or not first <= at <= end:
                previous = None
                continue
            path.append(f"{'L' if path and previous == m - 1 else 'M'}{x(at):.1f},{y(score):.1f}")
            drawn_to, drawn_score = at, score
            previous = m
        if not path:
            continue
        out.append(f'<path class="history-line history-line-{group}" d="{" ".join(path)}" stroke-dasharray="{DASH[group]}"/>')
        out.append(f'<circle class="history-dot history-dot-{group}" cx="{x(drawn_to):.1f}" cy="{y(drawn_score):.1f}" r="3.5"/>')
        latest = reads.get(last)
        word = _read_word(latest["groups"][group]["read"]) if latest else "No read"
        moved = f" ({-shift} mo earlier)" if shift < 0 else f" ({shift} mo later)" if shift > 0 else ""
        # A score past the threshold that still reads Mixed is held until last month's read agrees.
        latest_score = latest["groups"][group]["score"] if latest else None
        held = bool(latest) and latest["groups"][group]["read"] == "mixed" and latest_score is not None and abs(latest_score) >= THRESHOLD
        tip = (f"The score ({latest_score:+.2f}) is past {THRESHOLD if latest_score > 0 else -THRESHOLD:+.2f}, but the read a month "
               "earlier did not agree, so the group stays Mixed.") if held else ""
        labels.append((y(drawn_score), group, f"{group.capitalize()}: {word}{' (held)' if held else ''}{moved}", tip))

    placed = None
    for position, group, text, tip in sorted(labels):
        position = position if placed is None else max(position, placed + LABEL_GAP)
        placed = position
        title = f"<title>{escape(tip)}</title>" if tip else ""
        out.append(f'<text class="history-label history-label-{group}" x="{WIDTH - RIGHT + 10}" y="{position + 4:.1f}">{escape(text)}{title}</text>')

    if first_live and first <= _index(first_live) <= end:
        out.append(f'<line class="history-live-line" x1="{x(_index(first_live)):.1f}" y1="{TOP}" '
                   f'x2="{x(_index(first_live)):.1f}" y2="{HEIGHT - BOTTOM}"/>')
    out.append("</svg>")
    return "".join(out)


def _table(reads: dict, today: date | None) -> str:
    rows = []
    current = today.strftime("%Y-%m") if today else None
    for month in sorted(reads, reverse=True)[:TABLE_MONTHS]:
        groups = reads[month]["groups"]
        suffix = " (in progress)" if month == current and reads[month].get("source") == "live" else ""
        cells = "".join(f"<td>{escape(_read_word(groups[g]['read']))}</td>" for g in GROUPS)
        rows.append(f"<tr><td>{escape(month)}{suffix}</td>{cells}</tr>")
    return ("<details class=\"history-data\"><summary>Show the data (latest 24 months)</summary>"
            "<table class=\"indicator-table\"><thead><tr><th>Month</th><th>Leading</th><th>Coincident</th><th>Lagging</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></details>")


def _legend(has_recessions: bool) -> str:
    items = [f'<li class="history-legend-{g}"><svg width="34" height="10" aria-hidden="true"><line class="history-line history-line-{g}" x1="0" y1="5" x2="34" y2="5" '
             f'stroke-dasharray="{DASH[g]}"/></svg> {g.capitalize()}</li>' for g in GROUPS]
    if has_recessions:
        items.append('<li><svg width="22" height="12" aria-hidden="true"><rect class="history-band" width="22" height="12"/></svg> Recession (NBER)</li>')
    return f'<ul class="history-legend muted">{"".join(items)}</ul>'


def _buttons(label: str, name: str, options: list[tuple[str, str]], pressed: tuple[str, ...]) -> str:
    buttons = "".join(
        f'<button type="button" class="btn" data-{name}="{key}" aria-pressed="{"true" if key in pressed else "false"}">{escape(text)}</button>'
        for key, text in options)
    return f'<span role="group" aria-label="{label}">{buttons}</span>'


def _shell(inner: str, hidden_groups: tuple[str, ...] = ()) -> str:
    classes = "".join(f" history-hide-{g}" for g in hidden_groups)
    return f'<section class="card history-card{classes}"><div class="history-head"><p class="category-label">Reads over time</p></div>{inner}</section>'


def render_loading() -> str:
    return _shell('<p class="muted" role="status">Loading history&hellip;</p>')


def render_unavailable() -> str:
    return _shell('<p class="muted" role="status">History is unavailable right now.</p>')


def render_reads_history(reads: dict, recessions: dict, fit: dict, today: date | None = None) -> str:
    """The card. `reads` and `recessions` per `reads_history.load_reads` and
    `load_recessions`; `fit` per `reads_history.fit_alignment`."""
    if not reads:
        return _shell('<p class="muted">No reads have been saved yet. The next scheduled check saves the first one.</p>')

    last = max(reads)
    live = sorted(m for m, e in reads.items() if e.get("source") == "live")
    first_live = live[0] if live else None
    replayed = any(e.get("source") == "replay" for e in reads.values())

    panes = []
    for range_key, _, count in RANGES:
        hidden = "" if range_key == "10y" else " hidden"
        chart = _chart(reads, recessions, fit, last, count, range_key, first_live)
        panes.append(f'<div class="history-pane" data-range="{range_key}"{hidden}>{chart}</div>')

    seam = (f"Months before {first_live} were replayed from today's revised data, not from what was known at the time; "
            f"from {first_live} on they were saved as they happened." if replayed and first_live
            else "Earlier months have not been loaded yet. Only months saved since the first run are shown." if not replayed
            else "These months were replayed from today's revised data, not from what was known at the time.")
    return _shell(
        '<div class="history-controls">'
        + _buttons("Show", "group", [(g, g.capitalize()) for g in GROUPS], SHOWN_BY_DEFAULT)
        + _buttons("Range", "range", [(k, t) for k, t, _ in RANGES], ("10y",))
        + "</div>" + '<p class="muted history-empty" role="status" hidden>Press a group above to show its line.</p>'
        + "".join(panes) + _legend(bool(recessions))
        + f'<p class="muted history-note">{escape(seam)}</p>' + _table(reads, today),
        tuple(g for g in GROUPS if g not in SHOWN_BY_DEFAULT))
