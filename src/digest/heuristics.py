"""Named-heuristic calculations fed into the AI interpretation prompt.

Computed here rather than left for the model to infer.
"""


def sahm_rule_value(readings: list[dict]) -> float | None:
    """3-month average unemployment rate minus its 12-month low.

    `readings` is a chronologically ordered list of {"date", "value"}
    entries (monthly unemployment rate). A result >= 0.5 is the widely-used
    recession-signal threshold. Returns None if fewer than 12 readings are
    available to compute a reliable 12-month low.
    """
    if len(readings) < 12:
        return None

    values = [r["value"] for r in readings]
    last_3_avg = sum(values[-3:]) / 3
    twelve_month_low = min(values[-12:])
    return round(last_3_avg - twelve_month_low, 2)


def heuristic_for(key: str, history: list[dict]) -> dict | None:
    """The named heuristics `market_read.indicator_stats` takes for an
    indicator's history, or None when it has none."""
    if key == "unemployment_rate":
        value = sahm_rule_value(history)
        return {"sahm_rule_value": value} if value is not None else None
    return None
