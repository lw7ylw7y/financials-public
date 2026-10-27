"""Static mapping of the tracked indicators to their FRED series and category.

`fred_release_id` identifies the FRED *release* (e.g. "Employment
Situation") each series is published under, used to fetch the next
scheduled release date. Series that update continuously rather than on
a discrete release schedule (the yield curve spread) have no release ID
and are skipped for that lookup.

`favorable_direction` is which way a move is good for a long-term
investor ("higher", "lower", or None for a series with no inherent good
direction, which is shown as context and never scored). `kind` is how
the series is read: "level" uses the readings as they are, "change" uses the
percent change between consecutive readings, for cumulative series (an
index or a running total) whose level only drifts upward, and "inversion"
is a level read as a state (inverted or not).
"""

INDICATORS = {
    "initial_jobless_claims": {
        "name": "Initial Jobless Claims",
        "category": "leading",
        "favorable_direction": "lower",
        "kind": "level",
        "fred_series_id": "ICSA",
        "fred_release_id": "180",  # Unemployment Insurance Weekly Claims Report
    },
    "yield_curve_spread": {
        "name": "10yr-2yr Treasury Spread",
        "category": "leading",
        "favorable_direction": "higher",
        # Scored from its level, not its direction: unfavorable if it was inverted at any
        # point in the window (see market_read.indicator_stats). Its direction reads the
        # wrong way in a recession, when it steepens as the Fed cuts.
        "kind": "inversion",
        "fred_series_id": "T10Y2Y",
        "fred_release_id": None,  # updated daily, no discrete release
    },
    "building_permits": {
        "name": "Building Permits",
        "category": "leading",
        "favorable_direction": "higher",
        "kind": "level",
        "fred_series_id": "PERMIT",
        "fred_release_id": "27",  # New Residential Construction
    },
    "nonfarm_payrolls": {
        "name": "Nonfarm Payrolls",
        "category": "coincident",
        "favorable_direction": "higher",
        "kind": "change",
        "fred_series_id": "PAYEMS",
        "fred_release_id": "50",  # Employment Situation
    },
    "industrial_production": {
        "name": "Industrial Production",
        "category": "coincident",
        "favorable_direction": "higher",
        "kind": "change",
        "fred_series_id": "INDPRO",
        "fred_release_id": "13",  # G.17 Industrial Production and Capacity Utilization
    },
    "fed_funds_rate": {
        "name": "Fed Funds Rate",
        "category": "lagging",
        # No good direction as a signal of the economy: the Fed often cuts into weakness
        # and hikes into strength, so a falling rate is no sign of improvement. It
        # is shown as context, and `market_read.policy_stance` judges how tight it is
        # against inflation.
        "favorable_direction": None,
        "kind": "level",
        # The daily effective rate (DFF), not the monthly average
        # (FEDFUNDS): the monthly series only publishes once a month is
        # over and blends a rate change with the days before it, so a
        # change stayed invisible for weeks.
        "fred_series_id": "DFF",
        # No discrete release: a daily series, like the yield curve
        # spread. (H.15 publishes on nearly every business day since it
        # bundles many rate series, so a countdown against it is never
        # meaningful.)
        "fred_release_id": None,
    },
    "cpi": {
        "name": "CPI",
        "category": "lagging",
        # Context only: scored "lower is better" it did not separate recession from
        # expansion months, and `market_read.policy_stance` needs its history.
        "favorable_direction": None,
        "kind": "change",
        "fred_series_id": "CPIAUCSL",
        "fred_release_id": "10",  # Consumer Price Index
    },
    "unemployment_duration": {
        "name": "Median Weeks Unemployed",
        "category": "lagging",
        "favorable_direction": "lower",
        "kind": "level",
        "fred_series_id": "UEMPMED",
        "fred_release_id": "50",  # Employment Situation
    },
    "commercial_loans": {
        "name": "Commercial & Industrial Loans",
        "category": "lagging",
        "favorable_direction": "higher",
        "kind": "change",
        "fred_series_id": "BUSLOANS",
        "fred_release_id": "22",  # H.8 Assets and Liabilities of Commercial Banks
    },
    "unemployment_rate": {
        "name": "Unemployment Rate",
        "category": "coincident",
        "favorable_direction": "lower",
        "kind": "level",
        "fred_series_id": "UNRATE",
        "fred_release_id": "50",  # Employment Situation
    },
}
