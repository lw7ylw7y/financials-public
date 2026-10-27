"""Digest email rendering — plain-text and HTML bodies.

Kept separate from post_release.py's orchestration/throttling logic:
this module only turns already-computed data (AI result, table,
countdown) into email content. HTML uses inline styles and a
table-based layout throughout — the safe subset that renders
consistently across email clients (including older Outlook), which
don't reliably support <style> blocks, flexbox, or grid.
"""

from datetime import date
from html import escape

DISCLAIMER = (
    "This is automated commentary based on indicator trends, "
    "not personalized financial advice."
)
CATEGORY_ORDER = ["leading", "coincident", "lagging"]
CATEGORY_LABELS = {"leading": "Leading", "coincident": "Coincident", "lagging": "Lagging"}

# What the three words mean, appended to each group's explanation.
READ_MEANING = (
    " Improving means most of its indicators are moving the good way compared with their own "
    "past year, weakening the bad way, and mixed no clear direction (flat, or offsetting). "
    "A group changes to improving or weakening only when the read a month earlier agrees."
)

# What each group is, in the page's tooltips and the email's captions: `frame` is the
# time frame it speaks about, `info` the plain explanation. The three groups are read
# separately and never combined, because they look at different times.
CATEGORY_INFO = {
    "leading": {
        "frame": "Outlook: where the economy is heading",
        "info": (
            "Leading indicators usually turn months before the rest of the economy does, "
            "so they are an outlook, not a result. Each one is read by comparing the last "
            "90 days with the past 12 months; the yield curve is the exception and counts as "
            "unfavorable if it was inverted at any time in those 12 months."
            + READ_MEANING
        ),
    },
    "coincident": {
        "frame": "Now: how the economy is doing today",
        "info": (
            "Coincident indicators (jobs, output and the unemployment rate) move together with "
            "the economy, so they show what is happening now. Each one is read by comparing the last 90 days with the past "
            "12 months."
            + READ_MEANING
        ),
    },
    "lagging": {
        "frame": "Confirmation: the economy 6 to 12 months ago",
        "info": (
            "Lagging indicators (how long people stay unemployed, business loans) change "
            "after the economy has already moved, typically 6 to 12 months later, so they "
            "confirm the past rather than predict. Each one is "
            "read by comparing the last 90 days with the past 12 months."
            + READ_MEANING
        ),
    },
}

DIRECTIONAL_STYLE = {
    "improving": {"text": "#15803d", "bg": "#dcfce7", "accent": "#22c55e", "label": "Improving"},
    "weakening": {"text": "#b91c1c", "bg": "#fee2e2", "accent": "#ef4444", "label": "Weakening"},
    "mixed": {"text": "#475569", "bg": "#e2e8f0", "accent": "#94a3b8", "label": "Mixed"},
}

# Badge for a group's read that can't be computed yet (too little history).
NO_READ_STYLE = {"text": "#475569", "bg": "#e2e8f0", "accent": "#94a3b8", "label": "No read yet"}

FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def directional_style(read: str | None) -> dict:
    return DIRECTIONAL_STYLE[read] if read else NO_READ_STYLE


def summary_or_note(ai_result: dict) -> str:
    """The AI's explanation, or a note saying why there isn't one."""
    if ai_result["summary"]:
        return ai_result["summary"]
    if all(group["read"] is None for group in ai_result["groups"].values()):
        return "Not enough history on file yet to compute a read."
    return "Computed from the indicator data; AI commentary is unavailable right now."


def policy_line(policy: dict) -> str:
    """One sentence on how tight monetary policy is, from `policy_stance`'s
    result. It is context beside the three reads, not a fourth read: it says
    what the Fed is doing to credit, not how the economy is doing."""
    if policy["stance"] is None:
        return f"Policy stance: not available yet ({policy['reason']})."
    fed_funds_date = date.fromisoformat(policy["fed_funds_date"])
    # A reason comes with a stance only when the zero-rate rule set it.
    near_zero = f" It reads Accommodative because {policy['reason']}, whatever recent inflation was." if policy["reason"] else ""
    if policy["inflation"] is None:
        return (
            f"Policy stance: {policy['stance'].capitalize()}. The fed funds rate is {policy['fed_funds']:.2f}% "
            f"(as of {fed_funds_date.day} {fed_funds_date:%b %Y}).{near_zero} "
            "This describes what the Fed is doing to credit, not how the economy is doing."
        )
    if policy["gap"] == 0:
        position = "at"
    else:
        position = f"{abs(policy['gap']):.1f} points {'above' if policy['gap'] > 0 else 'below'}"
    cpi_date = date.fromisoformat(policy["cpi_date"])
    return (
        f"Policy stance: {policy['stance'].capitalize()}. The fed funds rate is {policy['fed_funds']:.2f}% "
        f"(as of {fed_funds_date.day} {fed_funds_date:%b %Y}) and recent inflation is {policy['inflation']:.1f}% "
        f"(CPI to {cpi_date:%b %Y}, six-month annualized), so the real rate is {policy['real_rate']:.1f}%, "
        f"{position} a neutral real rate of about {policy['neutral_real_rate']:.1f}%.{near_zero} "
        "This describes what the Fed is doing to credit, not how the economy is doing."
    )


def group_basis(group: dict) -> str:
    """"2 of 3 indicators scored" for one group's read."""
    return f"{group['scored']} of {group['total']} indicators scored"


def render_subject(updated_names: list[str]) -> str:
    return f"[Indicator Digest] {len(updated_names)} update(s): {', '.join(updated_names)}"


def render_text(table: dict, countdown: dict, ai_result: dict | None) -> str:
    """Plain-text body — the multipart/alternative fallback."""
    lines = []
    if ai_result is not None:
        lines += [summary_or_note(ai_result), ""]
        for category in CATEGORY_ORDER:
            group = ai_result["groups"][category]
            read = directional_style(group["read"])["label"]
            lines.append(
                f"{CATEGORY_LABELS[category]} ({CATEGORY_INFO[category]['frame']}): {read}, {group_basis(group)}"
            )
        if ai_result["relationship"]:
            lines.append(ai_result["relationship"])
        lines.append(policy_line(ai_result["policy"]))
        lines += ["", DISCLAIMER, ""]

    for category in CATEGORY_ORDER:
        rows = table.get(category, [])
        if not rows:
            continue
        lines.append(f"{CATEGORY_LABELS[category]} ({CATEGORY_INFO[category]['frame']}):")
        for row in rows:
            prior = f"{row['prior_value']:g}" if row["prior_value"] is not None else "n/a"
            lines.append(
                f"  {row['name']}: {row['latest_value']:g} as of "
                f"{row['latest_date']} (prior: {prior})"
            )
        lines.append("")

    if countdown["entries"]:
        lines.append("Next releases:")
        soonest = countdown["soonest"]
        lines.append(
            f"  Next up: {soonest['name']} in {soonest['days_until']} day(s) "
            f"({soonest['next_release_date']})"
        )
        for entry in countdown["entries"]:
            if entry["key"] == soonest["key"]:
                continue
            lines.append(
                f"  {entry['name']}: in {entry['days_until']} day(s) "
                f"({entry['next_release_date']})"
            )

    return "\n".join(lines).rstrip() + "\n"


def _sparkline_img(cid: str | None) -> str:
    if not cid:
        return '<span style="color:#94a3b8;">&mdash;</span>'
    return (
        f'<img src="cid:{cid}" width="90" height="24" alt="trend" '
        f'style="display:block;border:0;">'
    )


def _render_ai_section(ai_result: dict | None) -> str:
    if ai_result is None:
        return ""

    summary = escape(summary_or_note(ai_result))
    tiles = []
    for category in CATEGORY_ORDER:
        group = ai_result["groups"][category]
        style = directional_style(group["read"])
        tiles.append(f"""
                <td width="33%" valign="top" style="padding:0 6px;">
                  <div style="background:{style['bg']};border-top:3px solid {style['accent']};
                              border-radius:6px;padding:10px 12px;">
                    <p style="margin:0 0 6px 0;font-size:12px;font-weight:700;letter-spacing:.04em;
                              text-transform:uppercase;color:#334155;">{CATEGORY_LABELS[category]}</p>
                    <span style="display:inline-block;padding:2px 8px;border-radius:999px;background:#ffffff;
                                 color:{style['text']};font-size:12px;font-weight:700;letter-spacing:.04em;
                                 text-transform:uppercase;">{style['label']}</span>
                    <p style="margin:6px 0 0 0;font-size:12px;line-height:1.4;color:#475569;">
                      {escape(CATEGORY_INFO[category]['frame'])}</p>
                    <p style="margin:2px 0 0 0;font-size:11px;color:#64748b;">{escape(group_basis(group))}</p>
                  </div>
                </td>""")
    relationship = (
        f'<p style="margin:12px 6px 0 6px;font-size:14px;line-height:1.5;color:#334155;font-weight:600;">'
        f'{escape(ai_result["relationship"])}</p>'
        if ai_result["relationship"] else ""
    )
    policy = (
        f'<p style="margin:8px 6px 0 6px;font-size:13px;line-height:1.5;color:#475569;">'
        f'{escape(policy_line(ai_result["policy"]))}</p>'
    )
    return f"""
    <tr>
      <td style="padding:0 24px 20px 24px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:#f8fafc;border-left:4px solid #94a3b8;border-radius:6px;">
          <tr>
            <td style="padding:18px 14px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>{''.join(tiles)}
                </tr>
              </table>
              {relationship}
              {policy}
              <p style="margin:12px 6px 0 6px;font-size:15px;line-height:1.6;color:#1e293b;">
                {summary}
              </p>
              <p style="margin:12px 6px 0 6px;font-size:12px;line-height:1.5;color:#64748b;
                        font-style:italic;">
                {escape(DISCLAIMER)}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def _render_table_section(table: dict) -> str:
    sections = []
    for category in CATEGORY_ORDER:
        rows = table.get(category, [])
        if not rows:
            continue

        row_html = []
        for i, row in enumerate(rows):
            bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
            prior = f"{row['prior_value']:g}" if row["prior_value"] is not None else "n/a"
            row_html.append(f"""
            <tr style="background:{bg};">
              <td style="padding:10px 12px;font-size:14px;color:#1e293b;border-bottom:1px solid #e2e8f0;">
                {escape(row['name'])}
              </td>
              <td style="padding:10px 12px;font-size:14px;color:#1e293b;font-weight:600;
                        border-bottom:1px solid #e2e8f0;text-align:right;">
                {row['latest_value']:g}
              </td>
              <td style="padding:10px 12px;font-size:13px;color:#64748b;border-bottom:1px solid #e2e8f0;
                        text-align:right;">
                {escape(row['latest_date'])}
              </td>
              <td style="padding:10px 12px;font-size:13px;color:#94a3b8;border-bottom:1px solid #e2e8f0;
                        text-align:right;">
                prior: {prior}
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:right;">
                {_sparkline_img(row.get('sparkline_cid'))}
              </td>
            </tr>""")

        sections.append(f"""
    <tr>
      <td style="padding:0 24px 20px 24px;">
        <p style="margin:0 0 2px 0;font-size:13px;font-weight:700;letter-spacing:.04em;
                  text-transform:uppercase;color:#334155;">
          {CATEGORY_LABELS[category]}
        </p>
        <p style="margin:0 0 8px 0;font-size:12px;line-height:1.4;color:#64748b;">
          {escape(CATEGORY_INFO[category]['frame'])}. {escape(CATEGORY_INFO[category]['info'])}
        </p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #e2e8f0;border-radius:6px;overflow:hidden;">
          {''.join(row_html)}
        </table>
      </td>
    </tr>""")
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
          <td style="padding:6px 0;font-size:13px;color:#475569;">{escape(entry['name'])}</td>
          <td style="padding:6px 0;font-size:13px;color:#94a3b8;text-align:right;">
            in {entry['days_until']} day(s) &middot; {escape(entry['next_release_date'])}
          </td>
        </tr>""")

    return f"""
    <tr>
      <td style="padding:0 24px 24px 24px;">
        <p style="margin:0 0 8px 0;font-size:13px;font-weight:700;letter-spacing:.04em;
                  text-transform:uppercase;color:#334155;">
          Next Releases
        </p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:#eff6ff;border-radius:6px;">
          <tr>
            <td style="padding:14px 16px;">
              <span style="display:inline-block;padding:2px 8px;border-radius:999px;
                          background:#2563eb;color:#ffffff;font-size:11px;font-weight:700;
                          letter-spacing:.04em;text-transform:uppercase;margin-right:8px;">
                Next up
              </span>
              <span style="font-size:14px;color:#1e293b;font-weight:600;">
                {escape(soonest['name'])}
              </span>
              <span style="font-size:13px;color:#475569;">
                &mdash; in {soonest['days_until']} day(s) ({escape(soonest['next_release_date'])})
              </span>
            </td>
          </tr>
          {f'''<tr><td style="padding:0 16px 14px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              {''.join(other_rows)}
            </table>
          </td></tr>''' if other_rows else ''}
        </table>
      </td>
    </tr>"""


def render_html(table: dict, countdown: dict, ai_result: dict | None) -> str:
    return f"""<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f1f5f9;font-family:{FONT_STACK};">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
      <tr>
        <td align="center" style="padding:24px 12px;">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0"
                 style="width:100%;max-width:600px;background:#ffffff;border-radius:8px;
                        overflow:hidden;border:1px solid #e2e8f0;">
            <tr>
              <td style="padding:24px 24px 4px 24px;">
                <p style="margin:0;font-size:12px;font-weight:700;letter-spacing:.08em;
                          text-transform:uppercase;color:#2563eb;">
                  Indicator Digest
                </p>
              </td>
            </tr>
            {_render_ai_section(ai_result)}
            {_render_table_section(table)}
            {_render_countdown_section(countdown)}
            <tr>
              <td style="padding:16px 24px;border-top:1px solid #e2e8f0;">
                <p style="margin:0;font-size:11px;color:#94a3b8;">
                  Automated macro indicator digest &middot; data from FRED
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
