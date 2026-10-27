"""Discount / fair / overpriced verdicts for the watchlist, computed from
the numbers already cached for each ticker.

Every verdict is arithmetic on a ticker's own snapshot and on its peers in
the same group, so the same cache always gives the same verdicts and no
AI call is involved: the page shows these, with their reasons, as they
are. The words describe a relative position (a discount is cheaper than
the ticker's own year and its peers, fair in line, overpriced richer), not
an estimate of what the ticker is worth.

Nothing here is a fixed cutoff on a raw number (apart from one guard,
below): each input is a rank, either against the ticker's own 52-week
range or against the other tickers in its group, and a ticker scores +1 /
-1 for sitting in the favorable / unfavorable third (the cut is at a third
of the rank, so with few tickers or ties a bit more or less than a third
scores). By convention the `individual` group is the company stocks and
every other group holds funds, so a fund is compared with funds and a
stock with stocks.

- position: where the price sits in its own 52-week range (the bottom
  third is cheaper, the top third dearer). This needs no peers, so it is
  the one signal a ticker in a small group still has;
- return: 26-week price return ranked against the group (a laggard is
  cheaper, a leader stretched);
- individual stocks only:
  - PEG (a low PEG is cheaper; a non-positive PEG is not ranked);
  - quality: the average rank of ROE, net margin, revenue growth, EPS
    growth and debt/equity (lower is better). EPS growth is missing when
    earnings are negative, and then counts as the worst rank. The bottom
    third is "weak" and scores -1.

A total of +`VERDICT_SCORE` or more is "discount", -`VERDICT_SCORE` or less
"overpriced", else "fair": one signal alone is not enough. Two guards keep
a relative rank from overstating things: a ticker closer than
`MIN_DISCOUNT_OFF_HIGH_PCT` to its 52-week high is never a "discount",
and a discount that rests on weak quality is a value trap and is called
"fair".

A group is judged against its own history, not against other groups
(a bond fund's drawdown and an equity sector's are not comparable, and a
group's tickers all rank against each other, so their average score says
nothing about the group): the median, over its scored tickers, of where
each price sits in its own 52-week range. The bottom third of that range
is "discount", the top third "overpriced". A group with fewer than
`MIN_PEERS` tickers with a range can't be judged, and a ticker with no
usable input isn't scored, so nothing is guessed.

A fund has no P/E, so its verdict is a price-position read, and the
reasoning says so.
"""

# Smallest group in which a rank means anything.
MIN_PEERS = 3
# A ticker is in the favorable third at or past this share of its group,
# the unfavorable third at or below the other.
PEER_TOP = 2 / 3
PEER_BOTTOM = 1 / 3
# Fewest quality inputs a stock needs for a quality rank.
MIN_QUALITY_INPUTS = 2
# Never call a ticker closer than this to its 52-week high a discount.
MIN_DISCOUNT_OFF_HIGH_PCT = 3.0
# Total score at or beyond which a ticker is a discount / overpriced.
VERDICT_SCORE = 2

INDIVIDUAL_GROUP = "individual"
_RANK = {"discount": 0, "fair": 1, "overpriced": 2}
# (field, label, higher is better)
_QUALITY_FIELDS = (
    ("roe", "ROE", True),
    ("net_margin", "net margin", True),
    ("revenue_growth", "revenue growth", True),
    ("eps_growth", "EPS growth", True),
    ("debt_to_equity", "debt/equity", False),
)


def _percentile(value: float, values: list[float]) -> float:
    """Share of `values` below `value`, ties counting half."""
    below = sum(v < value for v in values)
    equal = sum(v == value for v in values)
    return (below + 0.5 * equal) / len(values)


def _ranked(card: dict, cards: list[dict], field: str, usable=lambda v: True) -> float | None:
    """`card`'s percentile for `field` among `cards`, or None when it or
    too many peers lack a usable value."""
    mine = card.get(field)
    if mine is None or not usable(mine):
        return None
    values = [c[field] for c in cards if c.get(field) is not None and usable(c[field])]
    return _percentile(mine, values) if len(values) >= MIN_PEERS else None


def _quality_figures(card: dict) -> str:
    """The five quality inputs as text, "n/a" for one that is missing."""
    def pct(field, signed=False):
        value = card.get(field)
        return "n/a" if value is None else f"{value:+.0f}%" if signed else f"{value:.0f}%"

    debt = card.get("debt_to_equity")
    return (f"ROE {pct('roe')}, net margin {pct('net_margin')}, revenue growth {pct('revenue_growth', True)}, "
            f"EPS growth {pct('eps_growth', True)}, debt/equity {'n/a' if debt is None else f'{debt:.1f}'}")


def _quality_rank(card: dict, cards: list[dict]) -> float | None:
    """Mean percentile across the quality fields, or None with too few."""
    ranks = []
    for field, _, higher_is_better in _QUALITY_FIELDS:
        # Negative equity makes debt/equity negative, which is not "low debt".
        usable = (lambda v: v >= 0) if field == "debt_to_equity" else (lambda v: True)
        rank = _ranked(card, cards, field, usable)
        if rank is None and field == "eps_growth" and card.get("pe_ratio") is None:
            # Negative earnings: no growth rate and no P/E.
            rank = 0.0 if len([c for c in cards if c.get(field) is not None]) >= MIN_PEERS else None
        if rank is not None:
            ranks.append(rank if higher_is_better else 1 - rank)
    if len(ranks) < MIN_QUALITY_INPUTS:
        return None
    return sum(ranks) / len(ranks)


def range_position(price: float | None, low: float | None, high: float | None) -> float | None:
    """Where the price sits in its own 52-week range: 0 at the low, 1 at
    the high (a price outside a stored range clamps); None when the range
    or price is missing or degenerate."""
    if price is None or low is None or high is None or high <= low:
        return None
    return min(max((price - low) / (high - low), 0.0), 1.0)


def _range_position(card: dict) -> float | None:
    return range_position(card.get("price"), card.get("week52_low"), card.get("week52_high"))


def _score_ticker(card: dict, group_name: str, cards: list[dict]) -> dict | None:
    """{"score", "verdict", "reasoning", "value_trap"}, or None when the
    ticker has no usable input and so isn't scored."""
    score = 0
    facts = []
    evaluated = False

    position = _range_position(card)
    if position is not None:
        evaluated = True
        shown = f"price at {round(position * 100)}% of its own 52-week range"
        if card.get("pct_off_high") is not None:
            shown += f" ({round(card['pct_off_high'], 1)}% below its high)"
        if position <= PEER_BOTTOM:
            score += 1
            facts.append(f"{shown}, near its low")
        elif position >= PEER_TOP:
            score -= 1
            facts.append(f"{shown}, near its high")
        else:
            facts.append(f"{shown}, mid-range")

    momentum = _ranked(card, cards, "return_26w")
    if momentum is not None:
        evaluated = True
        r26 = round(card["return_26w"], 1)
        if momentum <= PEER_BOTTOM:
            score += 1
            facts.append(f"26-week return {r26}%, behind most of {group_name}")
        elif momentum >= PEER_TOP:
            score -= 1
            facts.append(f"26-week return {r26}%, ahead of most of {group_name} (stretched)")
        else:
            facts.append(f"26-week return {r26}%, mid-pack")

    weak = False
    if group_name == INDIVIDUAL_GROUP:
        peg = _ranked(card, cards, "peg_ratio", usable=lambda v: v > 0)
        if peg is not None:
            evaluated = True
            shown = round(card["peg_ratio"], 2)
            if peg <= PEER_BOTTOM:
                score += 1
                facts.append(f"PEG {shown}, lower than most peers")
            elif peg >= PEER_TOP:
                score -= 1
                facts.append(f"PEG {shown}, higher than most peers")
            else:
                facts.append(f"PEG {shown}, mid-pack")
        elif card.get("peg_ratio") is not None and card["peg_ratio"] > 0:
            facts.append(f"PEG {round(card['peg_ratio'], 2)}, too few peers with a PEG to rank it")
        else:
            shrinking = card.get("eps_growth") is not None and card["eps_growth"] < 0
            word = "not available" if card.get("peg_ratio") is None else "not meaningful (zero or negative)"
            facts.append(f"PEG {word}" + (" (earnings are shrinking)" if shrinking else ""))

        quality = _quality_rank(card, cards)
        figures = _quality_figures(card)
        if quality is not None:
            evaluated = True
            if quality <= PEER_BOTTOM:
                weak = True
                score -= 1
                facts.append(f"weak quality: bottom third of peers ({figures})")
            elif quality >= PEER_TOP:
                facts.append(f"strong quality: top third of peers ({figures})")
            else:
                facts.append(f"quality mid-pack ({figures})")
        else:
            facts.append(f"quality not rated, too few figures to rank ({figures})")

    if not evaluated:
        return None

    verdict = "fair"
    if score >= VERDICT_SCORE:
        verdict = "discount"
    elif score <= -VERDICT_SCORE:
        verdict = "overpriced"

    value_trap = False
    if verdict == "discount":
        off_high = card.get("pct_off_high")
        if off_high is not None and off_high < MIN_DISCOUNT_OFF_HIGH_PCT:
            verdict = "fair"
            facts.append(
                f"but within {MIN_DISCOUNT_OFF_HIGH_PCT:g}% of its high, which is not a discount"
            )
        elif weak:
            verdict = "fair"
            value_trap = True
            facts.append("looks cheap but quality is weak: a value trap, not a discount")

    reasoning = "; ".join(facts) or "Mid-pack against its peers on every input available"
    if group_name != INDIVIDUAL_GROUP:
        reasoning += " (a fund has no P/E, so this is a price-position read)"
    return {
        "score": score,
        "verdict": verdict,
        "reasoning": reasoning[0].upper() + reasoning[1:] + ".",
        "value_trap": value_trap,
    }


def _median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


_GROUP_SUMMARY = {
    "discount": "Most of this group is trading near the low end of its own 52-week ranges, cheaper than it has been over the past year.",
    "fair": "Most of this group is trading in the middle of its own 52-week ranges, in line with the past year.",
    "overpriced": "Most of this group is trading near the high end of its own 52-week ranges, richer than it has been over the past year.",
}


def _score_groups(scored_cards: dict[str, list[dict]]) -> list[dict]:
    """Verdicts for the groups, each judged against its own history.

    A group's figure is the median, over its scored tickers, of where
    each price sits in its own 52-week range. That is a rank within the
    group's own last year, so a calm bond fund and a volatile sector
    fund are measured on the same scale without being compared with each
    other. The bottom third of the range is "discount", the top third
    "overpriced". A group needs `MIN_PEERS` tickers with a range.
    Sorted discount-first, then by position. Each entry is
    {"group", "verdict", "summary"}; the summary is plain words, with the
    tickers that stand out added by `compute_ticker_verdicts`.
    """
    groups = []
    for group_name, cards in scored_cards.items():
        positions = [p for p in map(_range_position, cards) if p is not None]
        if len(positions) < MIN_PEERS:
            continue
        median = _median(positions)
        verdict = "fair"
        if median <= PEER_BOTTOM:
            verdict = "discount"
        elif median >= PEER_TOP:
            verdict = "overpriced"
        groups.append({"group": group_name, "verdict": verdict, "summary": _GROUP_SUMMARY[verdict], "_position": median})
    groups.sort(key=lambda g: (_RANK[g["verdict"]], g["_position"]))
    for g in groups:
        del g["_position"]
    return groups


def compute_ticker_verdicts(cards_by_group: dict[str, list[dict]]) -> dict:
    """Return {"groups", "tickers_by_verdict", "unscored", "scores"}.

    `groups` holds only the groups that could be judged, sorted
    discount-first, each {"group", "verdict", "summary"}; a summary names
    the tickers in the group that stand out as cheaper or richer.
    `tickers_by_verdict` has every scored ticker's {"symbol", "group",
    "reasoning"} in its verdict's bucket, in `cards_by_group`' own order.
    `unscored` lists `{"symbol", "group"}` for tickers with nothing to
    score on (they are in no bucket). `scores` maps group -> symbol ->
    {"score", "verdict", "value_trap"}.
    """
    scores: dict[str, dict] = {}
    buckets = {"discount": [], "fair": [], "overpriced": []}
    unscored = []
    scored_cards: dict[str, list[dict]] = {}
    for group_name, cards in cards_by_group.items():
        if not cards:
            continue
        scores[group_name] = {}
        scored_cards[group_name] = []
        for card in cards:
            result = _score_ticker(card, group_name, cards)
            if result is None:
                unscored.append({"symbol": card["symbol"], "group": group_name})
                continue
            scored_cards[group_name].append(card)
            scores[group_name][card["symbol"]] = {
                "score": result["score"],
                "verdict": result["verdict"],
                "value_trap": result["value_trap"],
            }
            buckets[result["verdict"]].append(
                {"symbol": card["symbol"], "group": group_name, "reasoning": result["reasoning"]}
            )

    groups = _score_groups(scored_cards)
    for group in groups:
        standouts = []
        for verdict, label in (("discount", "Standing out as cheaper"), ("overpriced", "Standing out as richer")):
            names = [e["symbol"] for e in buckets[verdict] if e["group"] == group["group"]]
            if names:
                standouts.append(f"{label}: {', '.join(names)}.")
        group["summary"] = " ".join([group["summary"], *standouts])
    return {
        "groups": groups,
        "tickers_by_verdict": buckets,
        "unscored": unscored,
        "scores": scores,
    }


def by_ticker(computed: dict | None) -> dict:
    """The verdicts keyed for the page: {"tickers": {(group, symbol):
    {"verdict", "reasoning"}}, "groups": {group: {"verdict", "summary"}},
    "unscored": {(group, symbol)}}. None (nothing cached yet) gives empty
    maps, so every row shows no verdict."""
    computed = computed or {"groups": [], "tickers_by_verdict": {}, "unscored": []}
    return {
        "tickers": {
            (entry["group"], entry["symbol"]): {"verdict": verdict, "reasoning": entry["reasoning"]}
            for verdict, entries in computed["tickers_by_verdict"].items()
            for entry in entries
        },
        "groups": {g["group"]: {"verdict": g["verdict"], "summary": g["summary"]} for g in computed["groups"]},
        "unscored": {(u["group"], u["symbol"]) for u in computed["unscored"]},
    }
